"""Regression: ``scripts/start.sh`` migrated the PRIMARY database unguarded (DW-32).

``start.sh`` ran ``alembic upgrade head`` in the ``api`` container of whatever
compose project it started. For the primary project that is the primary
``realestate`` database, with no migration lock and no heartbeat probe — the
race ``scripts/agent/migrate-primary.sh`` exists to close, reached through
another door. The fix: on the primary project ``start.sh`` only *reports* the
schema state and names ``migrate-primary.sh``; isolated projects (which own
their own Postgres volume and have no other migration path) migrate as before.

Two halves:

* the real ``start.sh`` driven over a throwaway tree with stub ``docker`` and
  ``curl`` executables first on ``PATH`` — what it *asked Docker to do* is the
  assertion;
* a scan of every helper script, hook, deploy unit, compose file and Dockerfile
  for a mutating alembic invocation outside the allowlist, so the next door
  somebody opens fails here, naming the file and line.

No test here reaches a real Docker daemon, database or Redis: each run first
proves that ``docker`` resolves to the stub and refuses to start otherwise.
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from infra.config import BackfillConfig
from tests.shell_helpers import BASH

# The tests that spawn the real start.sh are slow on Windows, so the fast tier
# skips them (see validate.py). The scan and the schema-check tests below are
# plain Python and carry no such mark on purpose: they have to run in every
# tier, because a Dockerfile or compose change does not select the harness gate.
_spawns_start_sh = pytest.mark.harness

_REPO = Path(__file__).resolve().parents[3]
_SCRIPTS = _REPO / "scripts"

_MIGRATE_PRIMARY_COMMAND = "bash scripts/agent/migrate-primary.sh"

# A schema-changing alembic call in any spelling: ``alembic upgrade head``,
# ``python -m alembic -c alembic.ini stamp head``, ``["alembic", "upgrade"]``,
# or the Python API ``command.upgrade(cfg, "head")``.
_MUTATING_ALEMBIC = re.compile(
    r"alembic\b[^|;&\n]{0,80}?\b(?:upgrade|downgrade|stamp)\b"
    r"|\bcommand\.(?:upgrade|downgrade|stamp)\s*\("
)

_STUB_MAGIC = "imoveis-stub-docker-v1"

# Stand-in for the Docker CLI. Appends every invocation to a log, answers the
# handful of questions ``start.sh`` and ``lib.sh`` ask, and plays the ``api``
# container for the read-only schema check (canned state line on stdout, the
# program it was handed on stdin kept for inspection).
_STUB_DOCKER = r"""#!/usr/bin/env bash
if [ "$*" = "__stub_probe__" ]; then echo "imoveis-stub-docker-v1"; exit 0; fi
printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG"
case "$*" in
  info|"compose version") exit 0 ;;
esac
args=" $* "
case "$args" in
  *" ps --services "*) echo api; exit 0 ;;
  *" ps postgres "*) echo "stub-postgres-1   Up 2 minutes (healthy)"; exit 0 ;;
  *" alembic upgrade "*|*" alembic downgrade "*|*" alembic stamp "*)
    echo "stub alembic output"
    exit "${FAKE_MIGRATE_RC:-0}" ;;
  *" run "*)
    cat >> "$FAKE_DOCKER_STDIN"
    printf '%s\n' "${FAKE_SCHEMA_STATE:-}"
    exit "${FAKE_SCHEMA_STATE_RC:-0}" ;;
esac
exit 0
"""

_STUB_CURL = "#!/usr/bin/env bash\nexit 0\n"

# Settings a developer shell (or the gate) may export that would change which
# project the script believes it is starting.
_SCRUBBED_ENV = ("COMPOSE_PROJECT_NAME", "PRIMARY_COMPOSE_PROJECT", "API_PORT", "FRONTEND_PORT")


def _stage_start(tmp_path: Path, *, env_local: str | None):
    """Throwaway tree with the real ``start.sh`` + ``lib.sh`` and the stubs."""
    tree = tmp_path / "tree"
    (tree / "scripts").mkdir(parents=True)
    for name in ("start.sh", "lib.sh"):
        shutil.copy(_SCRIPTS / name, tree / "scripts" / name)
    if env_local is not None:
        (tree / ".env.local").write_text(env_local, encoding="utf-8", newline="\n")

    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, body in (("docker", _STUB_DOCKER), ("docker-compose", _STUB_DOCKER), ("curl", _STUB_CURL)):
        stub = stubs / name
        stub.write_text(body, encoding="utf-8", newline="\n")
        stub.chmod(0o755)

    log = tmp_path / "docker_calls.log"
    stdin = tmp_path / "docker_stdin.txt"
    env = {key: value for key, value in os.environ.items() if key not in _SCRUBBED_ENV}
    env["PATH"] = str(stubs) + os.pathsep + env.get("PATH", "")
    env["FAKE_DOCKER_LOG"] = str(log)
    env["FAKE_DOCKER_STDIN"] = str(stdin)
    return tree, env, log, stdin


def _run_start(
    tmp_path: Path,
    *,
    env_local: str | None = None,
    state: str = "current",
    state_rc: int = 0,
    migrate_rc: int = 0,
    extra_env=None,
):
    tree, env, log, stdin = _stage_start(tmp_path, env_local=env_local)
    env["FAKE_SCHEMA_STATE"] = state
    env["FAKE_SCHEMA_STATE_RC"] = str(state_rc)
    env["FAKE_MIGRATE_RC"] = str(migrate_rc)
    env.update(extra_env or {})

    # The primary stack is live on the hosts this suite runs on. Never start
    # the script unless `docker` is provably the stub in this exact environment.
    probe = subprocess.run(
        [BASH, "-c", "docker __stub_probe__"],
        cwd=tree,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        stdin=subprocess.DEVNULL,
    )
    if probe.stdout.strip() != _STUB_MAGIC:
        pytest.fail(
            "the stub `docker` is not first on PATH — refusing to run start.sh against a "
            f"real Docker daemon.\nstdout: {probe.stdout}\nstderr: {probe.stderr}"
        )

    completed = subprocess.run(
        [BASH, str(tree / "scripts" / "start.sh"), "--no-frontend"],
        cwd=tree,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        stdin=subprocess.DEVNULL,
    )
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    program = stdin.read_text(encoding="utf-8") if stdin.exists() else ""
    return completed, calls, program


def _mutating(calls: list[str]) -> list[str]:
    return [call for call in calls if _MUTATING_ALEMBIC.search(call)]


def _lines_with(output: str, needle: str) -> list[str]:
    return [line for line in output.splitlines() if needle in line]


# The three ways a checkout is the primary project: no name of its own (lib.sh
# defaults it), the default name spelled out, or a renamed primary.
_PRIMARY_CHECKOUTS = {
    "no-env-local": (None, {}, "imoveis"),
    "named-imoveis": ("COMPOSE_PROJECT_NAME=imoveis\n", {}, "imoveis"),
    "renamed-primary": (
        "COMPOSE_PROJECT_NAME=casa\nPRIMARY_COMPOSE_PROJECT=casa\n",
        {},
        "casa",
    ),
}


@_spawns_start_sh
@pytest.mark.unit
@pytest.mark.parametrize("checkout", sorted(_PRIMARY_CHECKOUTS))
def test_start_on_the_primary_at_head_migrates_nothing(tmp_path: Path, checkout: str):
    env_local, extra_env, project = _PRIMARY_CHECKOUTS[checkout]
    completed, calls, program = _run_start(
        tmp_path, env_local=env_local, state="current", extra_env=extra_env
    )
    output = completed.stdout + completed.stderr

    assert completed.returncode == 0, output
    # The stack is still started, for the project the checkout names.
    assert [c for c in calls if f"-p {project} up -d --build" in c], calls
    assert not _mutating(calls), (
        "start.sh issued a schema-changing alembic command on the PRIMARY project — "
        f"only migrate-primary.sh may (DW-32).\n{calls}"
    )
    assert len(_lines_with(completed.stdout, "at head")) == 1, completed.stdout
    assert "[WARN]" not in output
    # The check it ran instead is read-only: it reads the version table and the
    # script directory, and is handed nothing that changes a schema.
    assert "alembic_version" in program
    assert "get_heads" in program
    assert not re.search(r"upgrade|downgrade|stamp|CREATE|INSERT|UPDATE|DELETE|ALTER", program)


@_spawns_start_sh
@pytest.mark.unit
def test_start_on_the_primary_with_a_pending_migration_warns_and_points(tmp_path: Path):
    completed, calls, _program = _run_start(tmp_path, state="pending:b65411932ef9->f3a7c81d5e42")
    output = completed.stdout + completed.stderr

    assert completed.returncode == 0, output  # a warning, not a failure
    assert [c for c in calls if "-p imoveis up -d --build" in c], calls
    assert not _mutating(calls), calls
    warnings = "\n".join(_lines_with(output, "[WARN]"))
    assert "b65411932ef9" in warnings
    assert "f3a7c81d5e42" in warnings
    assert _MIGRATE_PRIMARY_COMMAND in warnings
    assert "Stack is up" in completed.stdout
    assert not _MUTATING_ALEMBIC.search(output), "start.sh advised a migration by hand"


@_spawns_start_sh
@pytest.mark.unit
@pytest.mark.parametrize(
    ("state", "state_rc"),
    [("", 1), ("Traceback (most recent call last):", 0), ("current", 1), ("pending:", 0)],
    ids=["check-failed", "garbage", "failed-after-printing", "malformed-pending"],
)
def test_start_on_the_primary_with_unreadable_state_warns_and_points(
    tmp_path: Path, state: str, state_rc: int
):
    completed, calls, _program = _run_start(tmp_path, state=state, state_rc=state_rc)
    output = completed.stdout + completed.stderr

    assert completed.returncode == 0, output
    assert not _mutating(calls), calls
    warnings = "\n".join(_lines_with(output, "[WARN]"))
    assert "unknown" in warnings
    assert _MIGRATE_PRIMARY_COMMAND in warnings
    assert not _lines_with(completed.stdout, "at head")
    assert "Stack is up" in completed.stdout
    assert not _MUTATING_ALEMBIC.search(output)


@_spawns_start_sh
@pytest.mark.unit
def test_start_on_an_isolated_project_still_migrates_its_own_database(tmp_path: Path):
    """Another project name owns another Postgres volume — and has no other path."""
    completed, calls, _program = _run_start(
        tmp_path, env_local="COMPOSE_PROJECT_NAME=imoveis-wt-feat-x\n"
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    migrations = _mutating(calls)
    assert len(migrations) == 1, calls
    assert "-p imoveis-wt-feat-x run --rm api python -m alembic upgrade head" in migrations[0]
    assert "migrations applied" in completed.stdout
    assert _MIGRATE_PRIMARY_COMMAND not in completed.stdout  # that script refuses this checkout


@_spawns_start_sh
@pytest.mark.unit
def test_start_on_an_isolated_project_warns_when_its_migration_fails(tmp_path: Path):
    completed, calls, _program = _run_start(
        tmp_path, env_local="COMPOSE_PROJECT_NAME=imoveis-wt-feat-x\n", migrate_rc=1
    )
    output = completed.stdout + completed.stderr

    assert completed.returncode == 0, output
    assert len(_mutating(calls)) == 1
    assert "[WARN]" in output and "exit 1" in output
    assert "stamp" not in output  # the hand-run advice is gone on every project


# ---------------------------------------------------------------------------
# The scan: no other door.
# ---------------------------------------------------------------------------

# Files that may carry a mutating alembic invocation, and why.
_ALLOWED_ANYWHERE = {
    "scripts/agent/migrate-primary.sh",  # the guarded operator path
    "scripts/agent/validate.py",  # the gate's ephemeral test database only
}
# start.sh: exactly one, inside the function only the isolated-project branch calls.
_START = "scripts/start.sh"
_ISOLATED_FUNCTION = "migrate_isolated_project"

_SKIPPED_DIRS = {"__pycache__", "node_modules", ".git", ".venv"}


def _scanned_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for top in ("scripts", ".claude/hooks", "deploy"):
        base = root / top
        if not base.is_dir():
            continue
        for directory, subdirs, names in os.walk(base):
            subdirs[:] = [d for d in subdirs if d not in _SKIPPED_DIRS]
            files.extend(Path(directory) / name for name in names if not name.endswith(".pyc"))
    for pattern in ("Dockerfile*", "docker-compose*.y*ml", "compose*.y*ml"):
        files.extend(path for path in root.glob(pattern) if path.is_file())
    return sorted(set(files))


def _function_lines(lines: list[str], name: str) -> range:
    """1-based line numbers of the body of the shell function *name*."""
    for index, line in enumerate(lines):
        if re.match(rf"^{re.escape(name)}\(\)\s*\{{", line):
            for end in range(index + 1, len(lines)):
                if lines[end].startswith("}"):
                    return range(index + 2, end + 1)
    return range(0)


def _violations(root: Path) -> list[str]:
    """``path:line: text`` for every mutating alembic invocation off the allowlist."""
    found: list[str] = []
    for path in _scanned_files(root):
        relative = path.relative_to(root).as_posix()
        if relative in _ALLOWED_ANYWHERE:
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        hits = [number for number, line in enumerate(lines, 1) if _MUTATING_ALEMBIC.search(line)]
        if relative == _START:
            inside = _function_lines(lines, _ISOLATED_FUNCTION)
            allowed = [number for number in hits if number in inside][:1]
            hits = [number for number in hits if number not in allowed]
        found.extend(f"{relative}:{number}: {lines[number - 1].strip()}" for number in hits)
    return found


@pytest.mark.unit
def test_no_helper_migrates_outside_the_allowlist():
    scanned = {path.relative_to(_REPO).as_posix() for path in _scanned_files(_REPO)}
    # The scan is looking where the doors are.
    assert {_START, "scripts/setup.sh", "scripts/agent/migrate-primary.sh"} <= scanned
    assert "docker-compose.yml" in scanned
    assert any(name.startswith("Dockerfile") for name in scanned)
    assert any(name.startswith(".claude/hooks/") for name in scanned)

    violations = _violations(_REPO)
    assert not violations, (
        "a schema-changing alembic invocation outside scripts/agent/migrate-primary.sh "
        "(the only path that may migrate the primary database):\n" + "\n".join(violations)
    )


@pytest.mark.unit
def test_the_one_migration_in_start_sh_is_the_isolated_project_branch():
    lines = (_SCRIPTS / "start.sh").read_text(encoding="utf-8").splitlines()
    hits = [number for number, line in enumerate(lines, 1) if _MUTATING_ALEMBIC.search(line)]

    assert len(hits) == 1, [f"{n}: {lines[n - 1].strip()}" for n in hits]
    assert hits[0] in _function_lines(lines, _ISOLATED_FUNCTION)
    # Called from one place, and never on the primary project.
    calls = [line.strip() for line in lines if line.strip() == _ISOLATED_FUNCTION]
    assert len(calls) == 1
    # start.sh points at the guarded script; it never runs it.
    executed = [
        line
        for line in lines
        if "migrate-primary.sh" in line and not re.match(r"\s*(#|warn |ok |log )", line)
    ]
    assert not executed, f"start.sh must point at migrate-primary.sh, never run it:\n{executed}"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("relative", "line"),
    [
        ("scripts/dev.sh", 'compose_cmd run --rm api python -m alembic upgrade head'),
        ("scripts/ops/repair.sh", "alembic -c alembic.ini stamp head"),
        ("scripts/dev/fix_schema.py", 'subprocess.run([PYTHON, "-m", "alembic", "downgrade", "-1"])'),
        ("scripts/dev/fix_schema.py", 'command.upgrade(cfg, "head")'),
        (".claude/hooks/session_start.py", 'os.system("alembic upgrade head")'),
        ("deploy/systemd/imoveis-api.service", "ExecStartPre=/usr/bin/python -m alembic upgrade head"),
        ("docker-compose.yml", '    command: ["alembic", "upgrade", "head"]'),
        ("Dockerfile.api", "CMD alembic upgrade head && uvicorn api.main:app"),
        ("scripts/start.sh", "compose_cmd run --rm api python -m alembic upgrade head"),
    ],
)
def test_the_scan_names_the_file_and_line_of_a_new_door(tmp_path: Path, relative: str, line: str):
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"# header\n\n{line}\n", encoding="utf-8")

    assert _violations(tmp_path) == [f"{relative}:3: {line.strip()}"]


@pytest.mark.unit
def test_the_scan_allows_only_one_migration_in_the_isolated_branch(tmp_path: Path):
    """The allowlist is the function, not the file: a second call is a new door."""
    body = (
        "migrate_isolated_project() {\n"
        "  compose_cmd run --rm api python -m alembic upgrade head\n"
        "  compose_cmd run --rm api python -m alembic stamp head\n"
        "}\n"
    )
    target = tmp_path / "scripts" / "start.sh"
    target.parent.mkdir(parents=True)
    target.write_text(body, encoding="utf-8")

    assert _violations(tmp_path) == [
        "scripts/start.sh:3: compose_cmd run --rm api python -m alembic stamp head"
    ]


@_spawns_start_sh
@pytest.mark.unit
@pytest.mark.parametrize("spelling", ["Imoveis", "IMOVEIS", "imoveis."])
def test_a_differently_spelled_primary_is_still_the_primary(tmp_path: Path, spelling: str):
    """Compose normalizes project names; the v1 CLI turns all of these into ``imoveis``."""
    completed, calls, _program = _run_start(
        tmp_path, env_local=f"COMPOSE_PROJECT_NAME={spelling}\n", state="pending:aaa111->bbb222"
    )
    output = completed.stdout + completed.stderr

    assert completed.returncode == 0, output
    assert not _mutating(calls), calls
    assert _MIGRATE_PRIMARY_COMMAND in "\n".join(_lines_with(output, "[WARN]"))


@_spawns_start_sh
@pytest.mark.unit
@pytest.mark.parametrize("line", ["COMPOSE_PROJECT_NAME=", 'COMPOSE_PROJECT_NAME=""'])
def test_an_empty_project_name_is_never_migrated(tmp_path: Path, line: str):
    """``docker compose -p ""`` falls back to the directory name, which in the
    primary checkout is the primary project. An empty name is not "another
    project": it must take the reporting branch, never the migrating one."""
    completed, calls, _program = _run_start(
        tmp_path, env_local=line + "\n", state="pending:aaa111->bbb222"
    )
    output = completed.stdout + completed.stderr

    assert completed.returncode == 0, output
    assert not _mutating(calls), calls
    assert _MIGRATE_PRIMARY_COMMAND in "\n".join(_lines_with(output, "[WARN]"))


@_spawns_start_sh
@pytest.mark.unit
def test_start_on_the_primary_with_a_revision_this_code_does_not_know(tmp_path: Path):
    """A database newer than the code is not "behind", and nothing here can migrate it."""
    completed, calls, _program = _run_start(tmp_path, state="foreign:ffff00001111->f3a7c81d5e42")
    output = completed.stdout + completed.stderr

    assert completed.returncode == 0, output
    assert not _mutating(calls), calls
    warnings = "\n".join(_lines_with(output, "[WARN]"))
    assert "ffff00001111" in warnings and "f3a7c81d5e42" in warnings
    assert "behind" not in warnings
    assert _MIGRATE_PRIMARY_COMMAND not in output
    assert not _lines_with(completed.stdout, "at head")
    assert "Stack is up" in completed.stdout


# ---------------------------------------------------------------------------
# The read-only schema check, executed for real (no Docker, no Postgres).
# ---------------------------------------------------------------------------


def _schema_check_program() -> str:
    """The Python program start.sh pipes into the api container, verbatim."""
    text = (_SCRIPTS / "start.sh").read_text(encoding="utf-8")
    body = text[text.index("report_primary_schema_state() {") :]
    start = body.index("<<'PY'\n") + len("<<'PY'\n")
    return body[start : body.index("\nPY\n", start) + 1]


def _migration_revisions() -> tuple[str, str]:
    """(the single head, the revision just below it) of the repo's migrations."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(_REPO / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    (head,) = script.get_heads()
    below = script.get_revision(head).down_revision
    assert isinstance(below, str)
    return head, below


def _run_schema_check(tmp_path: Path, rows: list[str] | None) -> str:
    """Run the program against a SQLite file holding *rows* in alembic_version."""
    database = tmp_path / "schema.db"
    connection = sqlite3.connect(database)
    try:
        if rows is not None:
            connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
            connection.executemany("INSERT INTO alembic_version VALUES (?)", [(row,) for row in rows])
        connection.commit()
    finally:
        connection.close()
    before = database.read_bytes()
    env = dict(os.environ)
    env["DATABASE_URL"] = "sqlite:///" + database.as_posix()
    completed = subprocess.run(
        [sys.executable, "-"],
        input=_schema_check_program(),
        cwd=_REPO,  # alembic.ini and the migration scripts, as in the api image
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    assert database.read_bytes() == before, "the read-only check wrote to the database"
    return completed.stdout.strip()


@pytest.mark.unit
def test_the_schema_check_reports_what_the_database_actually_holds(tmp_path: Path):
    """Every other start.sh test cans this program's answer; this one runs it."""
    head, below = _migration_revisions()

    for case, (rows, expected) in enumerate(
        [
            (None, f"pending:none->{head}"),  # fresh database: no version table
            ([], f"pending:none->{head}"),
            ([head], "current"),
            ([below], f"pending:{below}->{head}"),
            (["ffff00001111"], f"foreign:ffff00001111->{head}"),
        ]
    ):
        case_dir = tmp_path / str(case)
        case_dir.mkdir()
        assert _run_schema_check(case_dir, rows) == expected


@pytest.mark.unit
def test_real_redis_py_reads_the_resolved_url_as_the_runner_does():
    """The keyspace proof runs on a fake server whose URL parser is the test's
    own. This pins the real client: built the script's way and the runner's way
    from one ``cfg.redis.url``, both address the same host, port, db and
    password. No connection is opened (redis-py connects on first command)."""
    import redis

    from infra.config import RedisConfig

    url = RedisConfig(host="redis.internal", port=6380, db=7, password="pw").url
    script_side = redis.Redis.from_url(url, socket_connect_timeout=3, socket_timeout=5)
    runner_side = redis.Redis.from_url(url, decode_responses=False)

    expected = {"host": "redis.internal", "port": 6380, "db": 7, "password": "pw"}
    for client in (script_side, runner_side):
        kwargs = client.connection_pool.connection_kwargs
        assert {key: kwargs.get(key) for key in expected} == expected


@pytest.mark.unit
def test_the_script_hardcodes_no_redis_endpoint_and_no_key_name():
    """Endpoint and keys come from the runner's config loader, never a literal.

    The earlier form of this test pinned two literal key names in the script to
    the *default* prefix, which kept the drift it described possible: any
    non-default ``REDIS_URL`` or ``backfill.redis_prefix`` still split the two
    sides (DW-8).
    """
    assert BackfillConfig().redis_prefix == "backfill:gemma"
    script = (_SCRIPTS / "agent" / "migrate-primary.sh").read_text(encoding="utf-8")

    hardcoded = {
        "key prefix": r"backfill:gemma",
        "redis host": r"REDIS_HOST\s*=|host\s*=\s*[\"']",
        "redis db": r"\bdb\s*=\s*\d",
        "redis port": r"REDIS_PRIMARY_PORT|\b6379\b",
        "client built from parts": r"redis\.Redis\((?!\))",
    }
    for what, pattern in hardcoded.items():
        hits = [
            f"{number}: {line.strip()}"
            for number, line in enumerate(script.splitlines(), 1)
            if re.search(pattern, line)
        ]
        assert not hits, f"migrate-primary.sh hardcodes a {what}:\n" + "\n".join(hits)

    assert "from infra.config import load_config" in script
    assert "cfg.redis.url" in script
    assert "cfg.backfill.redis_prefix" in script
    # Every client is built from the one resolved URL.
    assert len(re.findall(r"redis\.Redis\.from_url\(", script)) >= 6
    assert not re.findall(r"redis\.Redis(?!\.from_url\()", script)
    # Neither key is ever deleted outright; the only DEL is the token CAS.
    assert ".delete(" not in script
    assert script.count("redis.call('del',KEYS[1])") == 1
    assert "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('del',KEYS[1])" in script
