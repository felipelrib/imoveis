"""Regression: migrate-primary.sh's backfill guard was check-then-act (DW-3).

It read the advisory heartbeat ``backfill:gemma:active`` once and then ran
``alembic upgrade head`` with nothing holding the window, so a backfill runner
that started in the gap migrated against a live writer. The fix is a
migration-held key, ``backfill:gemma:migrating``, taken with ``SET NX EX`` and a
per-invocation token **before** the heartbeat probe, renewed for as long as the
upgrade runs, and released from an ``EXIT`` trap by token compare-and-swap.

These drive the real script over a throwaway git repo (``lib.sh`` derives
``REPO_ROOT`` from ``git rev-parse``) with a fake ``redis`` module *and* a stub
``alembic`` package on ``PYTHONPATH``, both recording into one ordered log — the
ordering *is* the fix, so it is what gets asserted, and it has to be asserted on
the **real** path: ``--dry-run`` returns before ``alembic`` ever runs, which is
precisely the window DW-3 is about. ``tmp_path`` has no ``.venv``, so the script
falls back to ``python3`` and the fakes shadow the real packages.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

from infra.config import BackfillConfig

_AGENT_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts" / "agent"
_MIGRATE_PRIMARY = _AGENT_SCRIPTS / "migrate-primary.sh"
_LIB = _AGENT_SCRIPTS / "lib.sh"

_MIGRATING_KEY = "backfill:gemma:migrating"
_HEARTBEAT_KEY = "backfill:gemma:active"

# Stand-in for the `redis` package. Records every call, in order, so the test can
# assert what the script did and when — including that the release is a token
# CAS and never a bare DEL of somebody else's key.
#
# It is a real *store*, backed by a JSON file because the script talks to Redis
# from a fresh Python process per call: a stateless double answers `get` with
# `None` no matter what was just written, which makes NX, the renewal CAS and the
# post-upgrade ownership re-check unassertable — and silently turns the happy
# path into one where the script warns that the upgrade ran unguarded.
_FAKE_REDIS = '''import json
import os

_LOG = os.environ["FAKE_REDIS_LOG"]
_STORE = os.environ["FAKE_REDIS_STORE"]
_MODE = os.environ.get("FAKE_REDIS_MODE", "idle")


def _record(op, key, **extra):
    entry = {"op": op, "key": key}
    entry.update(extra)
    with open(_LOG, "a", encoding="utf-8") as fh:
        print(json.dumps(entry), file=fh)


def _load():
    try:
        with open(_STORE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save(kv):
    with open(_STORE, "w", encoding="utf-8") as fh:
        json.dump(kv, fh)


class Redis:
    def __init__(self, **kwargs):
        if _MODE == "unreachable":
            raise ConnectionError("primary redis refused the connection")

    def get(self, key):
        _record("get", key)
        return _load().get(key)

    def set(self, key, value, nx=False, ex=None):
        _record("set", key, value=value, nx=bool(nx), ex=ex)
        kv = _load()
        if nx and key in kv:
            return None  # SET NX lost — somebody else holds it
        kv[key] = value
        _save(kv)
        return True

    def exists(self, key):
        _record("exists", key)
        return 1 if key in _load() else 0

    def delete(self, key):
        _record("delete", key)
        kv = _load()
        existed = kv.pop(key, None) is not None
        _save(kv)
        return 1 if existed else 0

    def eval(self, script, numkeys, key, *args):
        """Just enough Lua to be the two owner-token CAS scripts the guard uses."""
        args = [str(a) for a in args]
        _record("eval", key, script=script, args=args)
        kv = _load()
        if kv.get(key) != args[0]:
            return 0  # not ours: neither DEL nor EXPIRE may touch it
        if "redis.call('del',KEYS[1])" in script:
            kv.pop(key, None)
            _save(kv)
        return 1
'''

# Stub ``alembic`` package: ``python -m alembic upgrade head`` has to *succeed*
# under the fake, and it records into the same ordered log so "was the key still
# held while the upgrade ran?" is answerable.
_FAKE_ALEMBIC_MAIN = '''import json
import os
import sys
import time

_LOG = os.environ["FAKE_REDIS_LOG"]


def _record(op, **extra):
    entry = {"op": op, "key": " ".join(sys.argv[1:])}
    entry.update(extra)
    with open(_LOG, "a", encoding="utf-8") as fh:
        print(json.dumps(entry), file=fh)


_record("alembic_start")
if os.environ.get("FAKE_ALEMBIC_STEALS_LOCK"):
    # Stand-in for the lock expiring (or a second holder taking it) while the
    # DDL runs: the renewal CAS and the post-upgrade ownership check both have
    # to notice, and both branches were otherwise unreachable.
    with open(os.environ["FAKE_REDIS_STORE"], "w", encoding="utf-8") as fh:
        json.dump({"backfill:gemma:migrating": "migrate-primary:thief:9:1754500000"}, fh)
time.sleep(float(os.environ.get("FAKE_ALEMBIC_SECONDS", "0")))
_record("alembic_done")
sys.exit(int(os.environ.get("FAKE_ALEMBIC_RC", "0")))
'''


def _init_primary_repo(tmp_path: Path) -> Path:
    """Throwaway repo carrying just the two scripts under test."""
    primary = tmp_path / "primary_repo"
    (primary / "scripts" / "agent").mkdir(parents=True)
    run = lambda *args: subprocess.run(  # noqa: E731
        args, cwd=primary, check=True, capture_output=True, text=True
    )
    run("git", "init", "-q", "-b", "main")
    run("git", "config", "user.email", "test@example.com")
    run("git", "config", "user.name", "Test")
    for script in (_MIGRATE_PRIMARY, _LIB):
        shutil.copy(script, primary / "scripts" / "agent" / script.name)
    # This checkout must read as the PRIMARY one or the script refuses early.
    (primary / ".env.local").write_text("COMPOSE_PROJECT_NAME=imoveis\nREDIS_PORT=6379\n")
    run("git", "add", "-A")
    run("git", "commit", "-q", "-m", "init")
    return primary


# A migration that is already running when this invocation starts.
_FOREIGN_TOKEN = "migrate-primary:other-host:1:1754500000"

# Starting contents of the fake primary Redis, per scenario.
_SEEDS = {
    "idle": {},
    "alive": {_HEARTBEAT_KEY: "1"},
    "busy": {_MIGRATING_KEY: _FOREIGN_TOKEN},
    "held": {_MIGRATING_KEY: _FOREIGN_TOKEN},
    "unreachable": {},
}


def _stage_guard(
    tmp_path: Path, *, mode: str, ttl=None, alembic_seconds=None, extra_env=None
):
    """Throwaway repo + fake `redis`/`alembic` + the env that wires them up."""
    primary = _init_primary_repo(tmp_path)
    fake_pkg = tmp_path / "fake_site"
    (fake_pkg / "alembic").mkdir(parents=True)
    (fake_pkg / "redis.py").write_text(_FAKE_REDIS)
    (fake_pkg / "alembic" / "__init__.py").write_text("")
    (fake_pkg / "alembic" / "__main__.py").write_text(_FAKE_ALEMBIC_MAIN)
    log = tmp_path / "redis_calls.jsonl"
    store = tmp_path / "redis_store.json"
    store.write_text(json.dumps(_SEEDS[mode]))

    env = dict(os.environ)
    env["PYTHONPATH"] = str(fake_pkg)  # shadows the real redis/alembic packages
    env["FAKE_REDIS_LOG"] = str(log)
    env["FAKE_REDIS_STORE"] = str(store)
    env["FAKE_REDIS_MODE"] = mode
    if ttl is not None:
        env["MIGRATE_LOCK_TTL_SECONDS"] = str(ttl)
    if alembic_seconds is not None:
        env["FAKE_ALEMBIC_SECONDS"] = str(alembic_seconds)
    env.update(extra_env or {})
    return primary, env, log, store


def _entries(log: Path) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line]


def _run_guard(
    tmp_path: Path,
    *,
    mode: str,
    args=(),
    ttl=None,
    alembic_seconds=None,
    extra_env=None,
):
    primary, env, log, store = _stage_guard(
        tmp_path,
        mode=mode,
        ttl=ttl,
        alembic_seconds=alembic_seconds,
        extra_env=extra_env,
    )
    completed = subprocess.run(
        ["bash", str(primary / "scripts" / "agent" / "migrate-primary.sh"), *args],
        cwd=primary,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    return completed, _entries(log), json.loads(store.read_text())


def _index_of(entries, op, key=None) -> int:
    for i, entry in enumerate(entries):
        if entry["op"] == op and (key is None or entry["key"] == key):
            return i
    raise AssertionError(f"no {op} of {key} in {entries}")


def _renewals(entries) -> list[int]:
    """Indices of the token-CAS *renewal* evals (the EXPIRE script)."""
    return [
        i
        for i, e in enumerate(entries)
        if e["op"] == "eval"
        and "redis.call('expire',KEYS[1],ARGV[2])" in e.get("script", "")
    ]


def _releases(entries) -> list[int]:
    """Indices of the token-CAS *release* evals (the DEL script, not the renew)."""
    return [
        i
        for i, e in enumerate(entries)
        if e["op"] == "eval" and "redis.call('del',KEYS[1])" in e.get("script", "")
    ]


@pytest.mark.unit
def test_the_migration_key_is_taken_before_the_heartbeat_is_probed(tmp_path: Path):
    """Set-then-check: probing first leaves the whole upgrade window unguarded."""
    completed, entries, _store = _run_guard(tmp_path, mode="idle")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    took = _index_of(entries, "set", _MIGRATING_KEY)
    probed = _index_of(entries, "exists", _HEARTBEAT_KEY)
    assert took < probed, (
        "the heartbeat was probed before the migration key was held — a runner "
        f"starting in that gap sees an idle guard.\n{entries}"
    )
    acquire = entries[took]
    assert acquire["nx"] is True  # two invocations must not both win
    assert acquire["ex"] == 1800  # TTL, not a shutdown hook, frees a hard kill


@pytest.mark.unit
def test_the_key_is_still_held_while_alembic_runs_and_released_after(tmp_path: Path):
    """The window DW-3 is about: the *upgrade*, not the probe before it.

    Every other test drove ``--dry-run``, which returns before alembic is
    reached — so nothing covered a release that fired too early and handed a
    runner a green light halfway through the DDL.
    """
    completed, entries, store = _run_guard(tmp_path, mode="idle")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    upgrade = _index_of(entries, "alembic_start")
    assert entries[upgrade]["key"] == "upgrade head"
    took = _index_of(entries, "set", _MIGRATING_KEY)
    assert took < upgrade
    releases = _releases(entries)
    assert releases, f"the key was never released\n{entries}"
    assert all(i > _index_of(entries, "alembic_done") for i in releases), (
        "the migration key was handed back before alembic finished — a runner "
        f"starting then writes into the upgrade.\n{entries}"
    )
    # The CAS actually deleted it: a release that no-ops leaves the guard set
    # for its whole TTL and blocks every backfill until it expires.
    assert _MIGRATING_KEY not in store
    # The script's own verdict on the window it just ran. Asserted because a
    # stateless double made this warn on every green run, unnoticed.
    assert "was not ours when alembic finished" not in completed.stderr


@pytest.mark.unit
def test_the_lock_is_renewed_while_a_long_upgrade_runs(tmp_path: Path):
    """A fixed TTL silently loses exclusion when the upgrade outruns it.

    TTL 3s ⇒ the watchdog renews every 1s; the fake upgrade takes ~2.5s, so a
    non-renewing script would be holding an expired key by the time it finishes.
    """
    completed, entries, _store = _run_guard(
        tmp_path, mode="idle", ttl=3, alembic_seconds=2.5
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    start = _index_of(entries, "alembic_start")
    done = _index_of(entries, "alembic_done")
    renewals = _renewals(entries)
    assert [i for i in renewals if start < i < done], (
        f"the lock was never renewed during the upgrade\n{entries}"
    )
    # Renewal is an owner-token CAS: extending a key we no longer own would
    # steal a second migration's window.
    token = entries[_index_of(entries, "set", _MIGRATING_KEY)]["value"]
    assert entries[renewals[0]]["args"][0] == token
    assert entries[renewals[0]]["args"][1] == "3"


@pytest.mark.unit
def test_the_migration_key_is_released_on_exit_by_token_compare_and_swap(tmp_path: Path):
    completed, entries, store = _run_guard(tmp_path, mode="idle")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    release = entries[-1]
    assert release["op"] == "eval"
    assert release["key"] == _MIGRATING_KEY
    # Guarded delete only: an invocation must never drop a key it does not own.
    assert "redis.call('get',KEYS[1])==ARGV[1]" in release["script"]
    assert "redis.call('del',KEYS[1])" in release["script"]
    assert release["args"][0] == entries[_index_of(entries, "set", _MIGRATING_KEY)]["value"]
    assert release["args"][0].startswith("migrate-primary:")
    assert not [e for e in entries if e["op"] == "delete"]
    assert _MIGRATING_KEY not in store  # the CAS matched and the key is gone


@pytest.mark.unit
def test_a_live_backfill_heartbeat_still_refuses_and_hands_the_key_back(tmp_path: Path):
    completed, entries, store = _run_guard(tmp_path, mode="alive")

    assert completed.returncode == 1
    assert "heartbeat is ALIVE" in completed.stderr
    assert not [e for e in entries if e["op"] == "alembic_start"]
    # The refusal must not leave the key behind for its whole TTL.
    assert entries[-1]["op"] == "eval"
    assert entries[-1]["key"] == _MIGRATING_KEY
    assert _MIGRATING_KEY not in store
    assert store[_HEARTBEAT_KEY] == "1"  # the runner's key is never touched


@pytest.mark.unit
def test_a_second_invocation_refuses_without_deleting_the_holders_key(tmp_path: Path):
    """``SET NX`` lost → this process owns nothing, so its release is a no-op CAS."""
    completed, entries, store = _run_guard(tmp_path, mode="busy")

    assert completed.returncode == 1
    assert _MIGRATING_KEY in completed.stderr
    # Refused before the heartbeat probe, and never a bare DEL of the holder's key.
    assert not [e for e in entries if e["op"] == "exists"]
    assert not [e for e in entries if e["op"] == "delete"]
    assert not [e for e in entries if e["op"] == "alembic_start"]
    # The point of the token CAS: the live migration still holds its key.
    assert store[_MIGRATING_KEY] == _FOREIGN_TOKEN


@pytest.mark.unit
def test_a_lock_lost_during_the_upgrade_is_reported_not_hidden(tmp_path: Path):
    """The upgrade must never *silently* run unguarded.

    The lock can lapse under a long-enough upgrade (expiry, eviction, a second
    holder). Killing alembic over that would leave a half-applied migration —
    worse — so the contract is that the script says so, loudly, on both the
    renewal path and the post-upgrade ownership check.
    """
    completed, entries, store = _run_guard(
        tmp_path,
        mode="idle",
        ttl=3,
        alembic_seconds=2.5,
        extra_env={"FAKE_ALEMBIC_STEALS_LOCK": "1"},
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "MIGRATION LOCK LOST" in completed.stderr
    assert "was not ours when alembic finished" in completed.stderr
    # And the thief's key survives: the CAS release refuses to drop it.
    assert store[_MIGRATING_KEY] == "migrate-primary:thief:9:1754500000"
    assert not [e for e in entries if e["op"] == "delete"]


@pytest.mark.unit
def test_a_failed_upgrade_still_reports_whether_it_was_guarded(tmp_path: Path):
    """A half-applied migration is exactly when "was it guarded?" matters."""
    completed, entries, store = _run_guard(
        tmp_path, mode="idle", extra_env={"FAKE_ALEMBIC_RC": "1"}
    )

    assert completed.returncode == 1
    assert "alembic upgrade head FAILED" in completed.stderr
    assert "migrated to head" not in completed.stdout
    # Checked and released even on the failure path.
    assert [e for e in entries if e["op"] == "get" and e["key"] == _MIGRATING_KEY]
    assert _MIGRATING_KEY not in store


@pytest.mark.unit
def test_an_unusable_lock_ttl_is_refused_with_a_message_about_the_ttl(tmp_path: Path):
    """``ex=0`` made redis raise, which the acquire reported as "is Redis up?"."""
    completed, entries, _store = _run_guard(tmp_path, mode="idle", ttl=0)

    assert completed.returncode == 1
    assert "MIGRATE_LOCK_TTL_SECONDS" in completed.stderr
    assert "Redis" not in completed.stderr  # not blamed for an operator typo
    assert entries == []  # refused before touching the primary at all


@pytest.mark.unit
def test_an_unreachable_redis_still_fails_closed(tmp_path: Path):
    """No Redis ⇒ no mutual exclusion ⇒ no migration — unchanged from before."""
    completed, entries, _store = _run_guard(tmp_path, mode="unreachable")

    assert completed.returncode == 1
    assert "fail closed" in completed.stderr
    assert entries == []  # nothing was taken, nothing was probed


@pytest.mark.unit
def test_a_dry_run_probes_the_guard_without_taking_the_key(tmp_path: Path):
    """``--dry-run`` changes nothing — including Redis.

    Taking the key for the second or two the probe costs is enough to bounce a
    runner that starts in that window to exit 8, for a command whose entire
    contract is that it does not act.
    """
    completed, entries, store = _run_guard(tmp_path, mode="idle", args=("--dry-run",))

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert store == {}, f"--dry-run wrote to the primary Redis\n{store}"
    assert not [e for e in entries if e["op"] == "set"], (
        f"--dry-run wrote to the primary Redis\n{entries}"
    )
    assert not [e for e in entries if e["op"] in ("delete", "eval")]
    assert not [e for e in entries if e["op"] == "alembic_start"]
    # It still *reports* both halves of the guard.
    assert _index_of(entries, "get", _MIGRATING_KEY) >= 0
    assert _index_of(entries, "exists", _HEARTBEAT_KEY) >= 0
    assert "would run: alembic upgrade head" in completed.stdout


@pytest.mark.unit
def test_a_dry_run_reports_a_migration_already_in_progress(tmp_path: Path):
    completed, entries, store = _run_guard(tmp_path, mode="held", args=("--dry-run",))

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert _FOREIGN_TOKEN in completed.stdout
    assert not [e for e in entries if e["op"] == "set"]
    assert store[_MIGRATING_KEY] == _FOREIGN_TOKEN


@pytest.mark.unit
@pytest.mark.skipif(os.name != "posix", reason="process groups / SIGKILL semantics")
def test_a_hard_killed_migration_stops_renewing_so_the_key_self_clears(tmp_path: Path):
    """SIGKILL runs no EXIT trap, so only the TTL can free the key — and only if
    the renewal watchdog dies with its parent.

    An orphaned watchdog re-``EXPIRE``s ``:migrating`` forever: the key the
    contract says "self-clears, never delete it manually" would then block every
    backfill run until somebody found and killed a stray background shell.
    """
    primary, env, log, _store = _stage_guard(
        tmp_path, mode="idle", ttl=3, alembic_seconds=30
    )
    proc = subprocess.Popen(
        ["bash", str(primary / "scripts" / "agent" / "migrate-primary.sh")],
        cwd=primary,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        start_new_session=True,  # own process group: cleanup can never hit pytest
    )
    pgid = os.getpgid(proc.pid)  # captured before the kill: the pid gets reaped
    try:
        # Wait until the upgrade is actually under way and renewals are flowing.
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if any(e["op"] == "alembic_start" for e in _entries(log)):
                break
            time.sleep(0.2)
        else:  # pragma: no cover - the fake upgrade always starts
            pytest.fail(f"alembic never started\n{_entries(log)}")
        time.sleep(1.5)  # ≥ one renewal interval (ttl 3 ⇒ every 1s)
        assert _renewals(_entries(log)), "the watchdog was not renewing at all"

        proc.kill()  # SIGKILL: no EXIT trap, no release, watchdog left behind
        proc.wait(timeout=10)
        time.sleep(1.2)  # let an orphan wake up once
        after_kill = len(_renewals(_entries(log)))
        time.sleep(2.5)  # ...and twice more
        assert len(_renewals(_entries(log))) == after_kill, (
            "the renewal watchdog outlived the migration it was renewing for — "
            "the migration key would never expire"
        )
    finally:
        # Sweeps up the watchdog subshell if this assertion ever fails again.
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, signal.SIGKILL)


@pytest.mark.unit
def test_the_script_and_the_runner_key_off_the_same_prefix():
    """The two halves stop excluding each other the moment these drift.

    The shell script hardcodes the literals; the runner derives its keys from
    ``backfill.redis_prefix``. Nothing else connects them, and a silent rename on
    either side leaves both sides happily proceeding at once.
    """
    prefix = BackfillConfig().redis_prefix
    assert prefix == "backfill:gemma"
    script = _MIGRATE_PRIMARY.read_text()

    assert f'MIGRATE_LOCK_KEY="{prefix}:migrating"' in script
    assert f'HEARTBEAT_KEY="{prefix}:active"' in script
