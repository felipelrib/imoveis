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
falls back to the ``python`` on ``PATH`` (the gate interpreter, put first there)
and the fakes shadow the real packages.

DW-8 (v0.14-s1.4): the script used to address ``localhost:${REDIS_PORT}`` db 0
with two literal key names while the runner takes its endpoint from
``REDIS_URL`` and its keys from ``backfill.redis_prefix``. Only the Redis
*server* is faked here: the fake keeps one keyspace per ``host:port/db``, the
script resolves endpoint and prefix through the real ``infra.config`` (the repo
``src`` is on ``PYTHONPATH`` behind the fakes), and the runner side of the proof
is the real ``get_redis`` / ``Heartbeat`` / ``MigrationGate``. A mismatch in
host, port, db or prefix therefore shows up as a key the other side cannot see.
No test here opens a connection to a real Redis, database or Docker daemon.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Spawns the real shell scripts: slow on Windows, so the fast tier skips it (see validate.py).
pytestmark = pytest.mark.harness

from tests.shell_helpers import BASH

_AGENT_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts" / "agent"
_MIGRATE_PRIMARY = _AGENT_SCRIPTS / "migrate-primary.sh"
_LIB = _AGENT_SCRIPTS / "lib.sh"
_SRC = Path(__file__).resolve().parents[2]
_REPO = _SRC.parent

_MIGRATING_KEY = "backfill:gemma:migrating"
_HEARTBEAT_KEY = "backfill:gemma:active"
# The fake server keeps one keyspace per endpoint; this is the default one.
_DEFAULT_ENDPOINT = "localhost:6379/0"

# The non-default keyspace of the DW-8 proof: another db *and* another prefix.
_ALT_REDIS_URL = "redis://localhost:6379/7"
_ALT_ENDPOINT = "localhost:6379/7"
_ALT_PREFIX = "backfill:alt"
_ALT_MIGRATING_KEY = f"{_ALT_PREFIX}:migrating"
_ALT_HEARTBEAT_KEY = f"{_ALT_PREFIX}:active"
_PRIMARY_ENV_LOCAL = "COMPOSE_PROJECT_NAME=imoveis\nREDIS_PORT=6379\n"
_ALT_ENV_LOCAL = (
    _PRIMARY_ENV_LOCAL
    + f"REDIS_URL={_ALT_REDIS_URL}\n"
    + f"IMOVEIS_BACKFILL__REDIS_PREFIX={_ALT_PREFIX}\n"
)
# Inherited settings that would move the endpoint, the prefix or the project
# identity under a test that did not ask for it (the gate exports REDIS_URL for
# its own ephemeral stack).
_SCRUBBED_ENV = ("REDIS_URL", "REDIS_PORT", "COMPOSE_PROJECT_NAME", "PRIMARY_COMPOSE_PROJECT")

# Stand-in for the `redis` package. Records every call, in order, so the test can
# assert what the script did and when — including that the release is a token
# CAS and never a bare DEL of somebody else's key.
#
# It is a real *store*, backed by a JSON file because the script talks to Redis
# from a fresh Python process per call: a stateless double answers `get` with
# `None` no matter what was just written, which makes NX, the renewal CAS and the
# post-upgrade ownership re-check unassertable — and silently turns the happy
# path into one where the script warns that the upgrade ran unguarded.
#
# The store is keyed by endpoint (`host:port/db`) and every call records the
# endpoint it went to, so a client built for another host, port or db reads an
# empty keyspace exactly as it would against real servers (DW-8).
_FAKE_REDIS = '''import json
import os
from urllib.parse import urlparse

_LOG = os.environ["FAKE_REDIS_LOG"]
_STORE = os.environ["FAKE_REDIS_STORE"]
_MODE = os.environ.get("FAKE_REDIS_MODE", "idle")


def _load_all():
    try:
        with open(_STORE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_all(everything):
    with open(_STORE, "w", encoding="utf-8") as fh:
        json.dump(everything, fh)


class Redis:
    def __init__(self, host="localhost", port=6379, db=0, **kwargs):
        if _MODE == "unreachable":
            raise ConnectionError("primary redis refused the connection")
        self._endpoint = f"{host}:{int(port)}/{int(db)}"

    @classmethod
    def from_url(cls, url, **kwargs):
        parsed = urlparse(url)
        db = int((parsed.path or "/0").lstrip("/") or "0")
        return cls(host=parsed.hostname or "localhost", port=parsed.port or 6379, db=db, **kwargs)

    def _record(self, op, key, **extra):
        entry = {"op": op, "key": key, "endpoint": self._endpoint}
        entry.update(extra)
        with open(_LOG, "a", encoding="utf-8") as fh:
            print(json.dumps(entry), file=fh)

    def _load(self):
        return _load_all().get(self._endpoint, {})

    def _save(self, kv):
        everything = _load_all()
        everything[self._endpoint] = kv
        _save_all(everything)

    def get(self, key):
        self._record("get", key)
        return self._load().get(key)

    def set(self, key, value, nx=False, ex=None):
        self._record("set", key, value=value, nx=bool(nx), ex=ex)
        kv = self._load()
        if nx and key in kv:
            return None  # SET NX lost — somebody else holds it
        kv[key] = value
        self._save(kv)
        return True

    def exists(self, key):
        self._record("exists", key)
        return 1 if key in self._load() else 0

    def delete(self, key):
        self._record("delete", key)
        kv = self._load()
        existed = kv.pop(key, None) is not None
        self._save(kv)
        return 1 if existed else 0

    def eval(self, script, numkeys, key, *args):
        """Just enough Lua to be the two owner-token CAS scripts the guard uses."""
        args = [str(a) for a in args]
        self._record("eval", key, script=script, args=args)
        kv = self._load()
        if kv.get(key) != args[0]:
            return 0  # not ours: neither DEL nor EXPIRE may touch it
        if "redis.call('del',KEYS[1])" in script:
            kv.pop(key, None)
            self._save(kv)
        return 1
'''

# Stub ``alembic`` package: ``python -m alembic upgrade head`` has to *succeed*
# under the fake, and it records into the same ordered log so "was the key still
# held while the upgrade ran?" is answerable.
#
# With FAKE_ALEMBIC_RUNNER_PROBE it also plays the backfill runner for a moment:
# it runs while the script holds the lock, in the script's own environment, and
# asks the runner's real ``MigrationGate`` (built from ``get_redis()`` and
# ``get_config()``) whether a migration is in progress.
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
    with open(os.environ["FAKE_REDIS_STORE"], encoding="utf-8") as fh:
        everything = json.load(fh)
    everything.setdefault("localhost:6379/0", {})["backfill:gemma:migrating"] = (
        "migrate-primary:thief:9:1754500000"
    )
    with open(os.environ["FAKE_REDIS_STORE"], "w", encoding="utf-8") as fh:
        json.dump(everything, fh)
if os.environ.get("FAKE_ALEMBIC_RUNNER_PROBE"):
    from core.backfill_runner import MigrationGate
    from infra.config import get_config
    from infra.redis_client import get_redis

    gate = MigrationGate(get_redis(), prefix=get_config().backfill.redis_prefix)
    holder = gate.holder_token()
    _record("runner_gate", gate_key=gate.key, migrating=gate.is_migrating(), holder=holder)
time.sleep(float(os.environ.get("FAKE_ALEMBIC_SECONDS", "0")))
_record("alembic_done")
sys.exit(int(os.environ.get("FAKE_ALEMBIC_RC", "0")))
'''


def _init_primary_repo(tmp_path: Path, env_local: str = _PRIMARY_ENV_LOCAL) -> Path:
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
    (primary / ".env.local").write_text(env_local)
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
    tmp_path: Path,
    *,
    mode: str,
    ttl=None,
    alembic_seconds=None,
    extra_env=None,
    env_local: str = _PRIMARY_ENV_LOCAL,
):
    """Throwaway repo + fake `redis`/`alembic` + the env that wires them up."""
    primary = _init_primary_repo(tmp_path, env_local)
    fake_pkg = tmp_path / "fake_site"
    (fake_pkg / "alembic").mkdir(parents=True)
    (fake_pkg / "redis.py").write_text(_FAKE_REDIS)
    (fake_pkg / "alembic" / "__init__.py").write_text("")
    (fake_pkg / "alembic" / "__main__.py").write_text(_FAKE_ALEMBIC_MAIN)
    log = tmp_path / "redis_calls.jsonl"
    store = tmp_path / "redis_store.json"
    store.write_text(json.dumps({_DEFAULT_ENDPOINT: _SEEDS[mode]}))

    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _SCRUBBED_ENV and not key.startswith("IMOVEIS_")
    }
    # The throwaway repo has no .venv, so the script takes `python` from PATH:
    # it has to be the gate interpreter, which carries pydantic and PyYAML for
    # the real `infra.config`.
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    # The fakes come first and shadow the real redis/alembic packages; the repo
    # behind them is the real config loader and the real runner classes (the
    # root too: `infra.config` imports `src.core.*`, which the script gets from
    # running in its checkout and the throwaway repo does not have).
    env["PYTHONPATH"] = os.pathsep.join((str(fake_pkg), str(_REPO), str(_SRC)))
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
    env_local: str = _PRIMARY_ENV_LOCAL,
    endpoint: str | None = _DEFAULT_ENDPOINT,
):
    """Run the real script; return (completed, call log, keyspace).

    The third value is the keyspace of *endpoint* — the default one, so the
    DW-3 tests read it as the flat store it used to be — or every keyspace,
    keyed by endpoint, when *endpoint* is ``None``.
    """
    primary, env, log, store = _stage_guard(
        tmp_path,
        mode=mode,
        ttl=ttl,
        alembic_seconds=alembic_seconds,
        extra_env=extra_env,
        env_local=env_local,
    )
    completed = subprocess.run(
        [BASH, str(primary / "scripts" / "agent" / "migrate-primary.sh"), *args],
        cwd=primary,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    everything = json.loads(store.read_text())
    return completed, _entries(log), everything if endpoint is None else everything.get(endpoint, {})


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
        [BASH, str(primary / "scripts" / "agent" / "migrate-primary.sh")],
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


# ---------------------------------------------------------------------------
# DW-8: the script and the runner resolve one endpoint and one prefix.
# ---------------------------------------------------------------------------

# The runner side, as the host-side runner process would do it: the endpoint
# from ``get_redis()`` (``REDIS_URL``), the prefix from ``get_config()``.
_RUNNER_BEATS = """
from core.backfill_runner import Heartbeat
from infra.config import get_config
from infra.redis_client import get_redis

Heartbeat(get_redis(), prefix=get_config().backfill.redis_prefix).beat()
"""


def _own_token(entries) -> str:
    """The per-invocation token this run took the lock with."""
    return entries[_index_of(entries, "set")]["value"]


def _assert_only_own_token_cas(entries) -> None:
    """No bare ``DEL`` at all, and no compare-and-swap on anybody else's token."""
    assert not [e for e in entries if e["op"] == "delete"], entries
    evals = [e for e in entries if e["op"] == "eval"]
    if not evals:
        return
    token = _own_token(entries)
    assert token.startswith("migrate-primary:")
    for call in evals:
        assert "redis.call('get',KEYS[1])==ARGV[1]" in call["script"], call
        assert call["args"][0] == token, call
        assert call["key"].endswith(":migrating"), call


@pytest.mark.unit
def test_a_non_default_db_and_prefix_move_the_lock_and_the_probe(tmp_path: Path):
    """``REDIS_URL`` db 7 + prefix ``backfill:alt``: every call lands there.

    Before the fix the script wrote ``backfill:gemma:migrating`` at db 0 whatever
    the runner was configured with, so the two never met.
    """
    completed, entries, stores = _run_guard(
        tmp_path, mode="idle", env_local=_ALT_ENV_LOCAL, endpoint=None
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    took = _index_of(entries, "set", _ALT_MIGRATING_KEY)
    probed = _index_of(entries, "exists", _ALT_HEARTBEAT_KEY)
    assert took < probed < _index_of(entries, "alembic_start")
    redis_calls = [e for e in entries if "endpoint" in e]
    assert redis_calls
    assert {e["endpoint"] for e in redis_calls} == {_ALT_ENDPOINT}, entries
    assert {e["key"] for e in redis_calls} == {_ALT_MIGRATING_KEY, _ALT_HEARTBEAT_KEY}
    # Nothing at db 0 and nothing under the default prefix anywhere.
    assert stores.get(_DEFAULT_ENDPOINT, {}) == {}
    assert "backfill:gemma" not in json.dumps(stores)
    assert "backfill:gemma" not in json.dumps(entries)
    # Taken, held through the upgrade, and handed back by its own token.
    assert _ALT_MIGRATING_KEY not in stores[_ALT_ENDPOINT]
    assert "was not ours when alembic finished" not in completed.stderr
    _assert_only_own_token_cas(entries)


@pytest.mark.unit
def test_the_runner_sees_the_scripts_key_on_a_non_default_keyspace(tmp_path: Path):
    """Script → runner: the runner's own ``MigrationGate`` reads the held key.

    The stub ``alembic`` runs while the lock is held and asks the gate the
    runner builds from ``get_redis()`` + ``get_config()``. With the script on
    db 0 / ``backfill:gemma`` the gate answered "no migration" and the runner
    launched rows into the upgrade.
    """
    completed, entries, stores = _run_guard(
        tmp_path,
        mode="idle",
        env_local=_ALT_ENV_LOCAL,
        endpoint=None,
        extra_env={"FAKE_ALEMBIC_RUNNER_PROBE": "1"},
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    verdict = entries[_index_of(entries, "runner_gate")]
    assert verdict["gate_key"] == _ALT_MIGRATING_KEY
    assert verdict["migrating"] is True, (
        "the runner's MigrationGate saw no migration while alembic was running — "
        f"the script and the runner are in different keyspaces.\n{entries}"
    )
    assert verdict["holder"] == entries[_index_of(entries, "set", _ALT_MIGRATING_KEY)]["value"]
    assert stores.get(_DEFAULT_ENDPOINT, {}) == {}
    _assert_only_own_token_cas(entries)


@pytest.mark.unit
def test_a_heartbeat_the_runner_beat_on_a_non_default_keyspace_refuses(tmp_path: Path):
    """Runner → script: a ``Heartbeat.beat()`` at db 7 / ``backfill:alt`` blocks.

    With the script probing ``backfill:gemma:active`` at db 0 it read "idle" and
    migrated under the live writer.
    """
    primary, env, log, store = _stage_guard(tmp_path, mode="idle", env_local=_ALT_ENV_LOCAL)
    # The runner reads the same file as its environment; the script sources it.
    runner_env = dict(env)
    runner_env["REDIS_URL"] = _ALT_REDIS_URL
    runner_env["IMOVEIS_BACKFILL__REDIS_PREFIX"] = _ALT_PREFIX
    subprocess.run(
        [sys.executable, "-c", _RUNNER_BEATS],
        cwd=tmp_path,
        env=runner_env,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    beat = _entries(log)
    assert [(e["op"], e["key"], e["endpoint"]) for e in beat] == [
        ("set", _ALT_HEARTBEAT_KEY, _ALT_ENDPOINT)
    ]

    completed = subprocess.run(
        [BASH, str(primary / "scripts" / "agent" / "migrate-primary.sh")],
        cwd=primary,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    entries = _entries(log)[len(beat) :]
    stores = json.loads(store.read_text())

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "heartbeat is ALIVE" in completed.stderr
    assert not [e for e in entries if e["op"] == "alembic_start"]
    assert {e["endpoint"] for e in entries} == {_ALT_ENDPOINT}
    # The runner's key is untouched; the script's own key was handed back.
    assert stores[_ALT_ENDPOINT] == {_ALT_HEARTBEAT_KEY: "1"}
    assert stores.get(_DEFAULT_ENDPOINT, {}) == {}
    _assert_only_own_token_cas(entries)


@pytest.mark.unit
@pytest.mark.parametrize("args", [(), ("--dry-run",)], ids=["real", "dry-run"])
@pytest.mark.parametrize(
    "broken_line",
    ["REDIS_URL=redis://localhost:not-a-port/0", "IMOVEIS_BACKFILL__REDIS_PREFIX="],
    ids=["config-raises", "empty-prefix"],
)
def test_an_unresolvable_guard_endpoint_fails_closed(tmp_path: Path, args, broken_line):
    """No endpoint or no prefix ⇒ no guard ⇒ no migration, and no Redis call.

    Falling back to ``localhost:6379/0`` + ``backfill:gemma`` here would be the
    DW-8 bug again, reached through a typo.
    """
    completed, entries, stores = _run_guard(
        tmp_path,
        mode="idle",
        args=args,
        env_local=_PRIMARY_ENV_LOCAL + broken_line + "\n",
        endpoint=None,
    )

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "could not be resolved" in completed.stderr
    assert "fail closed" in completed.stderr
    assert entries == []  # refused before any Redis call and before alembic
    assert stores == {_DEFAULT_ENDPOINT: {}}


@pytest.mark.unit
def test_a_disagreeing_redis_port_follows_the_runner_and_says_so(tmp_path: Path):
    """``REDIS_PORT`` is the compose port mapping; the runner never reads it."""
    completed, entries, _stores = _run_guard(
        tmp_path,
        mode="idle",
        args=("--dry-run",),
        env_local="COMPOSE_PROJECT_NAME=imoveis\nREDIS_PORT=6380\n",
        endpoint=None,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert entries
    assert {e["endpoint"] for e in entries} == {_DEFAULT_ENDPOINT}
    warning = [line for line in completed.stdout.splitlines() if "REDIS_PORT" in line]
    assert warning and "6380" in warning[0] and "[WARN]" in warning[0], completed.stdout


@pytest.mark.unit
def test_the_redis_password_never_reaches_the_output(tmp_path: Path):
    """The endpoint is logged as ``host:port/db``; the URL stays in the environment."""
    completed, entries, _stores = _run_guard(
        tmp_path,
        mode="alive",
        env_local=_PRIMARY_ENV_LOCAL + "REDIS_URL=redis://:hunter2-guard-pw@localhost:6379/0\n",
    )

    assert completed.returncode == 1  # a live heartbeat: every log line is exercised
    assert "heartbeat is ALIVE" in completed.stderr
    assert {e["endpoint"] for e in entries} == {_DEFAULT_ENDPOINT}
    assert _DEFAULT_ENDPOINT in completed.stdout
    assert "hunter2-guard-pw" not in completed.stdout + completed.stderr


@pytest.mark.unit
@pytest.mark.parametrize("args", [(), ("--dry-run",)], ids=["real", "dry-run"])
@pytest.mark.parametrize(
    "password_line",
    [
        "REDIS_URL=redis://:hunter2/guard-pw@localhost:6379/0",
        "IMOVEIS_REDIS__PASSWORD=hunter2/guard-pw",
    ],
    ids=["redis-url", "password-override"],
)
def test_a_password_that_breaks_the_url_is_refused_without_being_quoted(
    tmp_path: Path, args, password_line
):
    """An unencoded ``/`` in the password makes URL parsing fail, and the
    parser's message quotes what stood in front of it: half the password. The
    script refuses once, in its own words, before any Redis call."""
    completed, entries, _stores = _run_guard(
        tmp_path,
        mode="idle",
        args=args,
        env_local=_PRIMARY_ENV_LOCAL + password_line + "\n",
        endpoint=None,
    )
    output = completed.stdout + completed.stderr

    assert completed.returncode == 1, output
    assert "could not be resolved" in completed.stderr
    assert "hunter2" not in output
    assert "guard-pw" not in output
    assert entries == []


@pytest.mark.unit
def test_a_dry_run_probes_the_non_default_keyspace_too(tmp_path: Path):
    """The dry run is the on-host confirmation of the resolution: same endpoint, same keys."""
    completed, entries, stores = _run_guard(
        tmp_path, mode="idle", args=("--dry-run",), env_local=_ALT_ENV_LOCAL, endpoint=None
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert [(e["op"], e["key"], e["endpoint"]) for e in entries] == [
        ("get", _ALT_MIGRATING_KEY, _ALT_ENDPOINT),
        ("exists", _ALT_HEARTBEAT_KEY, _ALT_ENDPOINT),
    ]
    assert _ALT_ENDPOINT in completed.stdout
    assert stores == {_DEFAULT_ENDPOINT: {}}  # nothing written anywhere


@pytest.mark.unit
def test_a_failing_config_names_the_field_but_never_echoes_its_input(tmp_path: Path):
    """The loader's validation errors quote their input — for a section-level
    error that is the whole section, API keys included. The refusal keeps the
    location and the message and hides the value."""
    completed, entries, _stores = _run_guard(
        tmp_path,
        mode="idle",
        env_local=_PRIMARY_ENV_LOCAL + "IMOVEIS_AI__ENRICHMENT_ROUTING__VISUAL=no-such-backend\n",
        endpoint=None,
    )

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "could not be resolved" in completed.stderr
    assert "enrichment_routing" in completed.stderr  # still says what is wrong
    assert "input_value=<hidden>" in completed.stderr
    assert "input_value={" not in completed.stdout + completed.stderr
    assert entries == []


@pytest.mark.unit
def test_the_script_finds_the_config_loader_in_its_own_checkout(tmp_path: Path):
    """Every other test here hands the script the real repo on ``PYTHONPATH``.

    This one does not: the throwaway repo carries its own ``src`` and
    ``configs``, and only the fakes are on ``PYTHONPATH`` — so the loader is
    importable only because the script puts its own checkout on the path
    *before* the resolution. Without that the only sanctioned migration path
    refuses on every run.
    """
    primary, env, log, _store = _stage_guard(tmp_path, mode="idle", env_local=_ALT_ENV_LOCAL)
    ignore = shutil.ignore_patterns("__pycache__")
    for package in ("core", "infra"):
        shutil.copytree(_SRC / package, primary / "src" / package, ignore=ignore)
    shutil.copy(_SRC / "__init__.py", primary / "src" / "__init__.py")
    (primary / "configs").mkdir()
    shutil.copy(_REPO / "configs" / "app_config.yaml", primary / "configs" / "app_config.yaml")
    env["PYTHONPATH"] = str(tmp_path / "fake_site")

    completed = subprocess.run(
        [BASH, str(primary / "scripts" / "agent" / "migrate-primary.sh"), "--dry-run"],
        cwd=primary,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert {e["endpoint"] for e in _entries(log)} == {_ALT_ENDPOINT}
    assert {e["key"] for e in _entries(log)} == {_ALT_MIGRATING_KEY, _ALT_HEARTBEAT_KEY}
