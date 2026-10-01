"""Host the existing backfill supervisor under Windows Task Scheduler.

No enrichment logic lives here. The runner executes on the main thread, so a
local cooperative stop can invoke its existing SIGINT handlers: idle shutdown
clears the heartbeat; active shutdown drains and releases the run lease. Never
use TerminateProcess to implement a normal stop.
"""

from __future__ import annotations

import _thread
import argparse
import errno
import importlib.util
import io
import json
import logging
import os
import re
import signal
import sys
import threading
import time
import uuid
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]


class HostError(Exception):
    """Operator-safe message, containing no underlying exception/config value."""


def state_dir(repo_root: Path) -> Path:
    return repo_root / ".run" / "backfill-host"


class HostLock:
    """An OS-owned lock; a dead process cannot leave a false live PID behind."""

    def __init__(self, path: Path):
        self.path = path
        self.file = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        if self.file.seek(0, os.SEEK_END) == 0:
            self.file.write(b"\0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            self.file = None
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                return False
            raise
        return True

    def close(self):
        if self.file is not None:
            # Closing releases the native lock on both platforms. Never unlink
            # the lock file: another opener could otherwise lock a new inode.
            self.file.close()
            self.file = None

    def __enter__(self):
        if not self.acquire():
            raise HostError("Backfill host is already running for this checkout.")
        return self

    def __exit__(self, *_args):
        self.close()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        # Readers only hold the file briefly, but Windows can refuse replacement
        # during that interval. Retry the atomic replace, never truncate state.
        for attempt in range(5):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def status(repo_root: Path) -> dict:
    directory = state_dir(repo_root)
    if not (directory / "host.lock").exists():
        return {"running": False}
    lock = HostLock(directory / "host.lock")
    acquired = lock.acquire()
    lock.close()
    return {**_read_json(directory / "state.json"), "running": not acquired}


def request_stop(repo_root: Path, *, timeout: float | None = None) -> bool:
    current = status(repo_root)
    if not current["running"]:
        return True
    nonce = current.get("nonce")
    if not isinstance(nonce, str) or not nonce:
        raise HostError("Host ownership is still starting; retry the stop shortly.")
    seconds = max(900, int(current.get("stop_timeout", 900))) if timeout is None else max(0.0, timeout)
    write_json(state_dir(repo_root) / "stop.json", {"nonce": nonce})
    deadline = time.monotonic() + seconds
    while True:
        observed = status(repo_root)
        if not observed["running"]:
            return True
        if observed.get("nonce") != nonce:
            raise HostError("Host ownership changed during stop; the replacement was left running.")
        if time.monotonic() >= deadline:
            raise HostError("Backfill host is still running or draining; no process was killed. Inspect host.log and retry.")
        time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))


def _environment(repo_root: Path, env_file: Path) -> dict[str, str]:
    if not (repo_root / ".git").is_dir():
        raise HostError("Install from the permanent primary checkout, not a linked worktree.")
    if not env_file.is_file():
        raise HostError("The private environment file is missing.")
    # parse_stream preserves values literally (including ${...}), accepts LF
    # and CRLF, and exposes malformed lines without logging their contents.
    from dotenv.parser import parse_stream

    values = {}
    try:
        with env_file.open(encoding="utf-8-sig") as stream:
            for item in parse_stream(stream):
                if item.error or (item.key is not None and item.value is None):
                    raise HostError("The private environment file contains an invalid assignment.")
                if item.key is not None:
                    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", item.key):
                        raise HostError("The private environment file contains an invalid variable name.")
                    values[item.key] = item.value
    except (OSError, UnicodeError):
        raise HostError("The private environment file could not be read as UTF-8.") from None
    for key in ("GEMINI_API_KEY", "DATABASE_URL", "REDIS_URL"):
        if not values.get(key, "").strip():
            raise HostError(f"The private environment file must set {key}.")
    return values


def _load_runner(repo_root: Path, *, warning_sink=None):
    path = repo_root / "scripts" / "dev" / "backfill_gemma.py"
    spec = importlib.util.spec_from_file_location("imoveis_hosted_backfill", path)
    if spec is None or spec.loader is None:
        raise HostError("The existing backfill runner is unavailable.")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    runner.get_config.cache_clear()
    cfg = runner.get_config()
    runner._resolve_backfill_backend(cfg, runner.DEFAULT_BACKFILL_SCOPE)
    from infra.config import DatabaseConfig

    if warning_sink is not None and cfg.database.name == DatabaseConfig().name:
        warning_sink(
            "[WARN] DATABASE_URL selects the configuration default database; the primary corpus is realestate. "
            "Verify the intended database before starting."
        )
    return runner.main, max(900, cfg.backfill.lease_ttl_seconds)


def bootstrap(repo_root: Path, env_file: Path, *, runner_loader=None, environment=None, warning_sink=None):
    values = _environment(repo_root, env_file) if environment is None else environment
    os.environ.update(values)
    os.environ["PYTHONPATH"] = os.pathsep.join((str(repo_root / "src"), str(repo_root)))
    os.environ["PYTHONUNBUFFERED"] = "1"
    os.environ["PYTHONUTF8"] = "1"
    os.chdir(repo_root)
    try:
        if runner_loader is not None:
            return runner_loader(repo_root)
        return _load_runner(repo_root, warning_sink=warning_sink)
    except (Exception, SystemExit):
        # Pydantic errors and provider exceptions may contain original input.
        # The operator gets names of the relevant settings, never their values.
        raise HostError(
            "Runner preflight failed. Check the native dependencies, DATABASE_URL, REDIS_URL, "
            "GEMINI_API_KEY and IMOVEIS_AI__ENRICHMENT_ROUTING__ overrides "
            "(VISUAL, SENTIMENT and DEAL_VERDICT must use one cloud backend)."
        ) from None


def _secret_values(values: dict[str, str]) -> list[str]:
    secrets = set()
    for key, value in values.items():
        if value and re.search(r"KEY|TOKEN|SECRET|PASSWORD|PASS$", key, re.IGNORECASE):
            secrets.add(value)
        if value and "://" in value:
            try:
                password = urlsplit(value).password
                if password:
                    secrets.update((password, unquote(password)))
            except ValueError:
                pass
    secrets.update(json.dumps(value)[1:-1] for value in tuple(secrets))
    return sorted(secrets, key=len, reverse=True)


class _HostLog:
    """Line-buffered UTF-8 output for pythonw, with rotation and secret masking."""

    encoding = "utf-8"

    def __init__(self, path: Path, secrets: list[str]):
        self.handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        self.handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        self.secrets = secrets
        self.pending = ""
        self.lock = threading.RLock()

    def _emit(self, line):
        for secret in self.secrets:
            line = line.replace(secret, "[redacted]")
        self.handler.emit(logging.LogRecord("backfill-host", logging.INFO, "", 0, line, (), None))

    def write(self, text):
        with self.lock:
            self.pending += text
            while "\n" in self.pending:
                line, self.pending = self.pending.split("\n", 1)
                self._emit(line)
        return len(text)

    def flush(self):
        with self.lock:
            if self.pending:
                self._emit(self.pending)
                self.pending = ""
            self.handler.flush()

    def isatty(self):
        return False

    def close(self):
        self.flush()
        self.handler.close()


def run_host(repo_root: Path, env_file: Path, *, runner_loader=None, retry_seconds: float = 10.0) -> int:
    directory = state_dir(repo_root)
    with HostLock(directory / "host.lock"):
        record = {
            "pid": os.getpid(), "nonce": uuid.uuid4().hex,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "phase": "starting", "stop_timeout": 900,
        }
        write_json(directory / "state.json", record)
        # File logging exists before application imports, including pythonw's
        # otherwise absent stdout/stderr. No env values enter the state file.
        log = _HostLog(directory / "host.log", [])
        stop_requested = threading.Event()
        finished = threading.Event()
        previous_sigint = signal.signal(signal.SIGINT, signal.default_int_handler)

        def watch_stop():
            while not finished.wait(0.1):
                if _read_json(directory / "stop.json").get("nonce") == record["nonce"]:
                    stop_requested.set()
                    # This schedules the CURRENT Python handler on the main
                    # thread, not a Windows TerminateProcess/console event.
                    _thread.interrupt_main(signal.SIGINT)
                    return

        watcher = threading.Thread(target=watch_stop, name="backfill-host-stop", daemon=True)
        with redirect_stdout(log), redirect_stderr(log):
            watcher.start()
            try:
                values = _environment(repo_root, env_file)
                log.secrets = _secret_values(values)
                runner_main, stop_timeout = bootstrap(
                    repo_root, env_file, runner_loader=runner_loader, environment=values,
                    warning_sink=lambda message: print(message, flush=True),
                )
                record["stop_timeout"] = stop_timeout
                while not stop_requested.is_set():
                    signal.signal(signal.SIGINT, signal.default_int_handler)
                    record["phase"] = "running"
                    write_json(directory / "state.json", record)
                    print("Backfill supervisor started.", flush=True)
                    try:
                        result = runner_main(["--serve"])
                        if result == 0:
                            break  # the existing supervisor's deliberate clean exit
                        print("Backfill supervisor exited unexpectedly; retrying.", flush=True)
                    except (Exception, SystemExit) as exc:
                        print(f"Backfill supervisor failed ({type(exc).__name__}); retrying.", flush=True)
                    if stop_requested.is_set():
                        break
                    record["phase"] = "retrying"
                    write_json(directory / "state.json", record)
                    stop_requested.wait(retry_seconds)
                return 0
            except KeyboardInterrupt:
                # Idle/import/retry shutdown. Active runs catch the scheduled
                # signal themselves, drain and return through the loop above.
                return 0
            except HostError as exc:
                print(str(exc), flush=True)
                return 1
            finally:
                finished.set()
                watcher.join(timeout=1)
                signal.signal(signal.SIGINT, previous_sigint)
                record["phase"] = "stopped"
                write_json(directory / "state.json", record)
                print("Backfill host stopped.", flush=True)
                log.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "status", "run", "stop"))
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--timeout", type=float, help="Stop wait in seconds; expiry never kills the process")
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    env_file = (args.env_file or root / ".env.local").resolve()
    try:
        if args.mode == "run":
            return run_host(root, env_file)
        if args.mode == "check":
            warnings = []
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                bootstrap(root, env_file, warning_sink=warnings.append)
            for warning in warnings:
                print(warning)
            print("Preflight passed. Configuration validated; services were not contacted.")
        elif args.mode == "status":
            current = status(root)
            print(json.dumps(current))
            return 0 if current["running"] else 1
        else:
            request_stop(root, timeout=args.timeout)
            print("Backfill host stopped; no process was killed.")
        return 0
    except HostError as exc:
        if sys.stderr is not None:
            print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        if sys.stderr is not None:
            print("Backfill host operation failed. Check paths, permissions and the native Python environment.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
