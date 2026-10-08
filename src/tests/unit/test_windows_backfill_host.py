"""Native hosting lifecycle, using the real runner's signal/serve handlers.

The child-process fixture replaces only enrichment and Redis with the existing
CLI doubles. No test imports the operator env, calls cloud AI, or starts a task.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
HOST = ROOT / "scripts/windows/backfill_host.py"
INSTALLER = ROOT / "scripts/install-backfill-runner.ps1"
pytestmark = [pytest.mark.unit, pytest.mark.harness]

# These tests hand the real checkout to the host as ``--repo-root``. The host
# refuses a linked git worktree by design ("Install from the permanent primary
# checkout"), so from one (a bmad-loop story worktree, for example) they cannot
# pass whatever the code does. They run from the primary checkout.
_needs_primary_checkout = pytest.mark.skipif(
    not (ROOT / ".git").is_dir(),
    reason="the backfill host refuses a linked git worktree by design; run from the primary checkout",
)


def _module():
    spec = importlib.util.spec_from_file_location("windows_backfill_host", HOST)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def host():
    return _module()


@pytest.fixture
def checkout(tmp_path):
    repo = tmp_path / "checkout with spaces"
    repo.mkdir()
    (repo / ".git").mkdir()
    env = repo / ".env.local"
    env.write_text(
        "GEMINI_API_KEY='literal-${UNEXPANDED}-credential'\r\n"
        "DATABASE_URL=postgresql://operator:fixture-pass@localhost:1234/fixture\r\n"
        "REDIS_URL=redis://localhost:1235/9\r\n",
        encoding="utf-8",
    )
    return repo, env


def test_bootstrap_env_is_literal_and_precedes_import(host, checkout, monkeypatch):
    repo, env = checkout
    before = dict(os.environ)
    monkeypatch.setattr(os, "environ", before.copy())
    seen = {}

    def loader(root):
        seen.update(root=root, key=os.environ["GEMINI_API_KEY"], cwd=Path.cwd())
        return lambda argv: 0, 900

    old_cwd = Path.cwd()
    try:
        host.bootstrap(repo, env, runner_loader=loader)
    finally:
        os.chdir(old_cwd)
    assert seen == {"root": repo, "key": "literal-${UNEXPANDED}-credential", "cwd": repo}
    assert os.environ["PYTHONUNBUFFERED"] == "1"


@pytest.mark.parametrize("body", ["GEMINI_API_KEY=\n", "not a valid assignment\n"])
def test_bad_env_fails_before_runner_import(host, checkout, monkeypatch, body):
    repo, env = checkout
    env.write_text(body)
    monkeypatch.setattr(os, "environ", {})
    called = []
    with pytest.raises(host.HostError):
        host.bootstrap(repo, env, runner_loader=lambda root: called.append(root))
    assert called == []


def test_linked_checkout_refused_before_loading_env(host, tmp_path):
    (tmp_path / ".git").write_text("gitdir: disposable/worktree\n")
    with pytest.raises(host.HostError, match="primary checkout"):
        host.bootstrap(tmp_path, tmp_path / "missing-env")


@_needs_primary_checkout
@pytest.mark.parametrize("routes,ok", [
    ([], False),
    (["gemma", "gemma", "gemini"], False),
    (["GEMMA", "gemma", "gemma"], False),
    (["gemma", "gemma", "gemma"], True),
])
def test_real_config_preflight_rejects_bad_routing_without_contacting_services(checkout, routes, ok):
    _repo, env = checkout
    with env.open("a", encoding="utf-8") as stream:
        for task_class, backend in zip(("VISUAL", "SENTIMENT", "DEAL_VERDICT"), routes):
            stream.write(f"IMOVEIS_AI__ENRICHMENT_ROUTING__{task_class}={backend}\n")
    result = subprocess.run(
        [sys.executable, str(HOST), "check", "--repo-root", str(ROOT), "--env-file", str(env)],
        capture_output=True, text=True, timeout=20,
    )
    assert (result.returncode == 0) is ok, (result.stdout, result.stderr)
    assert "literal-${UNEXPANDED}-credential" not in result.stdout + result.stderr
    assert "fixture-pass" not in result.stdout + result.stderr
    if ok:
        assert "services were not contacted" in result.stdout


@_needs_primary_checkout
@pytest.mark.parametrize("database,warn", [("imoveis", True), ("realestate", False), ("custom_corpus", False)])
def test_check_warns_only_for_config_default_database_without_exposing_values(checkout, database, warn):
    _repo, env = checkout
    with env.open("a", encoding="utf-8") as stream:
        stream.write(f"DATABASE_URL=postgresql://operator:fixture-pass@localhost:1234/{database}\n")
        for task_class in ("VISUAL", "SENTIMENT", "DEAL_VERDICT"):
            stream.write(f"IMOVEIS_AI__ENRICHMENT_ROUTING__{task_class}=gemma\n")
    result = subprocess.run(
        [sys.executable, str(HOST), "check", "--repo-root", str(ROOT), "--env-file", str(env)],
        capture_output=True, text=True, timeout=20,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output  # parity is advisory, not a database-name prohibition
    assert ("[WARN] DATABASE_URL" in output) is warn
    if warn:
        assert "realestate" in output
        assert "configuration default database" in output
    assert "literal-${UNEXPANDED}-credential" not in output
    assert "fixture-pass" not in output
    assert "postgresql://" not in output


def test_exclusive_lock_and_stopped_status_do_not_trust_stale_pid(host, checkout):
    repo, _env = checkout
    with host.HostLock(host.state_dir(repo) / "host.lock"):
        assert host.status(repo)["running"] is True
        with pytest.raises(host.HostError, match="already running"):
            with host.HostLock(host.state_dir(repo) / "host.lock"):
                pass
    host.write_json(host.state_dir(repo) / "state.json", {"pid": os.getpid(), "nonce": "old"})
    assert host.status(repo)["running"] is False


CHILD = r'''
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
import pytest

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

root, checkout, env, mode = map(str, sys.argv[1:])
root, checkout, env = Path(root), Path(checkout), Path(env)
sys.path[:0] = [str(root), str(root / "src")]
host = load(root / "scripts/windows/backfill_host.py", "host")
helpers = load(root / "src/tests/unit/test_backfill_gemma_cli.py", "cli_helpers")
runner = helpers._load_module()
redis = helpers._RecordingSetRedis()
cfg = helpers._wire(runner, pytest.MonkeyPatch(), api_key="fixture", routing=helpers._CLOUD_ROUTING, redis=redis)
cfg.backfill.control_poll_seconds = 0.05
control = runner._control_for(cfg, redis)
lease = runner._lease_for(cfg, redis)
calls = 0

def active_run(argv):
    assert lease.acquire()
    runner._install_stop_signals(control)
    (checkout / "ready").write_text("active")
    while not control.should_stop():
        time.sleep(0.03)
    time.sleep(0.25)
    (checkout / "drained").write_text("finished in-flight work")
    control.clear_stop()
    assert lease.release()
    return runner.EXIT_STOPPED

runner.main = active_run

def serve(argv):
    global calls
    assert argv == ["--serve"]
    calls += 1
    (checkout / "owner-pid").write_text(str(os.getpid()))
    (checkout / "calls").write_text(str(calls))
    if mode == "crash" and calls == 1:
        print("literal-${UNEXPANDED}-credential")
        raise RuntimeError("literal-${UNEXPANDED}-credential")
    if mode == "active":
        control.request_start("fixture")
    else:
        (checkout / "ready").write_text("idle")
    try:
        return runner._serve(cfg, redis, helpers._serve_args(), sleep_fn=time.sleep)
    finally:
        (checkout / "result.json").write_text(json.dumps({
            "heartbeat": redis.get("t:supervisor:active"),
            "lease": lease.holder(),
            "signal": runner._STOP_SIGNAL_RECEIVED,
        }))

raise SystemExit(host.run_host(checkout, env, runner_loader=lambda root: (serve, 900), retry_seconds=0.05))
'''


def wait_for(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("native fixture did not reach the expected state")


@pytest.mark.parametrize("mode", ["idle", "active", "crash"])
def test_native_process_stop_drains_and_clears_real_heartbeat(host, checkout, tmp_path, mode):
    repo, env = checkout
    child = tmp_path / "child.py"
    child.write_text(CHILD, encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, str(child), str(ROOT), str(repo), str(env), mode],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        wait_for(lambda: (repo / "ready").exists() or process.poll() is not None)
        assert process.poll() is None, process.communicate()
        state = host.status(repo)
        # The Windows venv executable may be a launcher parent. Compare the
        # lock owner's state to the interpreter actually executing the runner.
        assert state["running"] and state["pid"] == int((repo / "owner-pid").read_text())
        host.write_json(host.state_dir(repo) / "stop.json", {"nonce": "previous-process"})
        time.sleep(0.4)
        assert process.poll() is None, "a stale stop request stopped this process"
        assert host.request_stop(repo, timeout=10) is True
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, (stdout, stderr)
        result = json.loads((repo / "result.json").read_text())
        assert result["heartbeat"] is None
        assert result["lease"] is None
        assert result["signal"] is (mode == "active")
        if mode == "active":
            assert (repo / "drained").exists()
        assert (repo / "calls").read_text() == ("2" if mode == "crash" else "1")
        assert host.status(repo)["running"] is False
        assert "literal-${UNEXPANDED}-credential" not in stdout + stderr
        assert "literal-${UNEXPANDED}-credential" not in (host.state_dir(repo) / "host.log").read_text()
        if mode == "crash":
            assert "[redacted]" in (host.state_dir(repo) / "host.log").read_text()
    finally:
        if process.poll() is None:
            host.request_stop(repo, timeout=3)
            process.wait(timeout=5)


def test_stop_timeout_preserves_owner_and_nonce(host, checkout):
    repo, _env = checkout
    with host.HostLock(host.state_dir(repo) / "host.lock"):
        host.write_json(host.state_dir(repo) / "state.json", {"pid": os.getpid(), "nonce": "fixture", "stop_timeout": 900})
        with pytest.raises(host.HostError, match="still running"):
            host.request_stop(repo, timeout=0.05)
        assert host.status(repo)["running"] is True
        assert json.loads((host.state_dir(repo) / "stop.json").read_text())["nonce"] == "fixture"


@_needs_primary_checkout
@pytest.mark.skipif(sys.platform != "win32", reason="native Task Scheduler rendering requires Windows")
def test_task_plan_uses_pythonw_and_safe_signin_settings():
    powershell = shutil.which("powershell.exe")
    assert powershell
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-File", str(INSTALLER), "-Mode", "Print"],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert Path(plan["execute"]).name == "pythonw.exe"
    assert plan["working_directory"] == str(ROOT)
    assert plan["logon_type"] == "Interactive"
    assert plan["multiple_instances"] == "IgnoreNew"
    assert plan["execution_time_limit"] == "PT0S"
    assert plan["allow_hard_terminate"] is False
    assert plan["stop_on_battery"] is False
    assert plan["disallow_start_on_battery"] is False
    assert "GEMINI_API_KEY" not in result.stdout
