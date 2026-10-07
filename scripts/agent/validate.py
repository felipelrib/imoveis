#!/usr/bin/env python3
"""Tiered validation gate — the single entrypoint for every check before a push.

Usage (any shell, any OS — no Git Bash needed):

    python scripts/agent/validate.py                 # tier chosen from the diff
    python scripts/agent/validate.py --tier backend  # force a tier
    python scripts/agent/validate.py --required-tier # print the tier the diff needs
    python scripts/agent/validate.py --check-stamp   # exit 0 iff HEAD's tree carries a stamp >= required tier
    python scripts/agent/validate.py --down          # tear the ephemeral test stack down

Tiers (each includes the previous, except ``docs``):

    docs     mkdocs build --strict
    fast     pre-commit (all files) + unit tests (pytest-xdist when available)
    frontend fast + eslint + vite build + playwright e2e
    backend  fast + ephemeral PostGIS/Redis stack + integration + contract + alembic check
    full     backend + frontend

Path-triggered extra gates: scraper changes run the cassette suite + live dry-run,
AI prompt/client changes run the Ollama golden tests (skipped loudly when Ollama
is unreachable).

Primary-stack invariant: this script never touches the primary compose project.
DB/Redis come from the throwaway ``<workspace>-test`` compose project built from
``docker-compose.test.yml`` (docker-assigned ports, anonymous volumes only).

Environment: ``.env.local`` is read through a default-deny allowlist (DW-33) —
only workspace identity (ports, compose project, test credentials) reaches the
gate; never DATABASE_URL, REDIS_URL, GEMINI_API_KEY or any IMOVEIS_* override.

On success with a clean tree the gate writes ``.run/validated/<tree-sha>.<tier>``;
the push guard hook (``.claude/hooks/guard.py``) refuses ``git push`` to main
unless HEAD's tree carries a stamp for at least the tier the diff requires.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
PYTHON = sys.executable

TIERS = ["docs", "fast", "frontend", "backend", "full"]
TIER_RANK = {t: i for i, t in enumerate(TIERS)}

# ``.env.local`` keys the gate may see (DW-33). Everything else stays out.
WORKSPACE_ENV_ALLOWLIST = (
    "COMPOSE_PROJECT_NAME",
    "POSTGRES_PORT",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "POSTGRES_TEST_DB",
    "REDIS_PORT",
    "REDIS_TEST_DB",
    "API_PORT",
    "FRONTEND_PORT",
    "PLAYWRIGHT_PORT",
    "PLAYWRIGHT_BASE_URL",
    "API_KEY",
    "JWT_SECRET",
    "TEST_DATABASE_URL",
)
CONFIG_ENV_PREFIX = "IMOVEIS_"
PRESERVED_PREFIXED = {"IMOVEIS_ALLOW_PRIMARY_DB_WIPE", "IMOVEIS_ALLOW_PRIMARY_REDIS_WIPE"}
PRIMARY_COMPOSE_PROJECT = "imoveis"

# Paths that never need a code tier.
DOCS_PATTERNS = (
    re.compile(r"^docs/"),
    re.compile(r"^mkdocs\.yml$"),
    re.compile(r"^README\.md$"),
    re.compile(r"^_bmad-output/"),
    re.compile(r"^_bmad/"),
    re.compile(r"^\.agents/"),
    re.compile(r"\.md$"),
)
SCRAPER_PATTERNS = (re.compile(r"^src/adapters/scrapers/"), re.compile(r"^src/tests/unit/test_scraper_cassettes\.py$"))
AI_PATTERNS = (re.compile(r"^src/adapters/ai/"), re.compile(r"prompts\.py$"))
HARNESS_PATTERNS = (
    re.compile(r"^scripts/"),
    re.compile(r"^\.claude/"),
    re.compile(r"^\.pre-commit-config\.yaml$"),
    re.compile(r"^pytest\.ini$"),
    re.compile(r"^src/tests/(unit/test_(gate|audit|docker|finish|migrate|setup_worktree|windows|no_data|backfill_runner_hosting|claude)|shell_helpers)"),
)
FRONTEND_PREFIX = "frontend/"
# Harness/config-only changes are covered by the unit suite (gate tests live there).
FAST_ONLY_PATTERNS = (
    re.compile(r"^scripts/"),
    re.compile(r"^\.claude/"),
    re.compile(r"^\.pre-commit-config\.yaml$"),
    re.compile(r"^pytest\.ini$"),
    re.compile(r"^pyproject\.toml$"),
    re.compile(r"^\.flake8$"),
    re.compile(r"^\.isort\.cfg$"),
    re.compile(r"^\.gitignore$"),
    re.compile(r"^\.gitattributes$"),
    re.compile(r"^requirements.*\.(txt|in)$"),
    re.compile(r"^\.github/"),
    re.compile(r"^\.env\.local\.example$"),
)


# --------------------------------------------------------------------------- output
def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text


def log(msg: str) -> None:
    print(_c("36", f"> {msg}"), flush=True)


def ok(msg: str) -> None:
    print(_c("32", f"  [OK] {msg}"), flush=True)


def warn(msg: str) -> None:
    print(_c("33", f"  [WARN] {msg}"), flush=True)


def fail(msg: str) -> None:
    print(_c("31", f"  [FAIL] {msg}"), flush=True)


# --------------------------------------------------------------------------- env
def load_workspace_env(path: Path | None = None) -> dict[str, str]:
    """Read ``.env.local`` through the allowlist. Literal values, no expansion, last wins."""
    path = path or REPO_ROOT / ".env.local"
    loaded: dict[str, str] = {}
    if not path.is_file():
        return loaded
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        warn(f"{path} is not readable — skipping workspace env ({exc})")
        return loaded
    for raw in text.splitlines():
        line = raw.rstrip("\r").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        if key not in WORKSPACE_ENV_ALLOWLIST:
            continue
        value = value.strip()
        if value[:1] in ("'", '"') and value.count(value[0]) >= 2:
            quote = value[0]
            end = value.index(quote, 1)
            value = value[1:end]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        loaded[key] = value
    return loaded


def apply_gate_env() -> None:
    for key in list(os.environ):
        if key.startswith(CONFIG_ENV_PREFIX) and key not in PRESERVED_PREFIXED:
            del os.environ[key]
    for key, value in load_workspace_env().items():
        os.environ.setdefault(key, value)
    os.environ.setdefault("API_KEY", "test-local-api-key")
    os.environ.setdefault("JWT_SECRET", "test-local-jwt-secret")
    os.environ["PYTHONUTF8"] = "1"
    src = str(REPO_ROOT / "src")
    existing = os.environ.get("PYTHONPATH", "")
    if src not in existing.split(os.pathsep):
        os.environ["PYTHONPATH"] = src + (os.pathsep + existing if existing else "")


# --------------------------------------------------------------------------- git / diff
def git(*args: str, check: bool = False) -> str:
    res = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8")
    if check and res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr.strip()}")
    return res.stdout.strip()


def changed_paths() -> set[str]:
    """Union of committed-vs-origin/main, staged, unstaged and untracked paths."""
    subprocess.run(["git", "fetch", "origin", "main", "--quiet"], cwd=REPO_ROOT, capture_output=True)
    base = "origin/main" if git("rev-parse", "--verify", "-q", "origin/main") else "main"
    paths: set[str] = set()
    for out in (
        git("diff", "--name-only", f"{base}...HEAD"),
        git("diff", "--name-only", "HEAD"),
        git("ls-files", "--others", "--exclude-standard"),
    ):
        paths.update(p.strip().replace("\\", "/") for p in out.splitlines() if p.strip())
    return paths


def classify(paths: set[str]) -> tuple[str, set[str]]:
    """Return (tier, extra gates) the given changed paths require."""
    extras: set[str] = set()
    if any(any(p.match(x) for p in HARNESS_PATTERNS) for x in paths):
        extras.add("harness")
    if any(any(p.match(x) for p in SCRAPER_PATTERNS) for x in paths):
        extras.add("scrapers")
    if any(any(p.match(x) for p in AI_PATTERNS) for x in paths):
        extras.add("ai")
    code = [x for x in paths if not any(p.search(x) for p in DOCS_PATTERNS)]
    if not code:
        return ("docs" if paths else "fast"), extras
    fe = [x for x in code if x.startswith(FRONTEND_PREFIX)]
    be = [x for x in code if not x.startswith(FRONTEND_PREFIX)]
    harness_only = be and all(any(p.match(x) for p in FAST_ONLY_PATTERNS) for x in be)
    if fe and be and not harness_only:
        return "full", extras
    if fe:
        return "frontend", extras
    if harness_only:
        return "fast", extras
    return "backend", extras


def tree_sha() -> str:
    return git("rev-parse", "HEAD^{tree}")


def tree_is_clean() -> bool:
    return git("status", "--porcelain", "--untracked-files=no") == ""


def _stamp_dir() -> Path:
    """Stamps live in the PRIMARY checkout's .run/ so a worktree's validation (bmad-loop) counts after merge."""
    common = git("rev-parse", "--git-common-dir")
    base = Path(common).resolve().parent if common and common != ".git" else REPO_ROOT
    return base / ".run" / "validated"


STAMP_DIR = _stamp_dir()


def write_stamp(tier: str) -> None:
    if not tree_is_clean():
        warn("working tree has uncommitted changes — no validation stamp written (commit, then re-run or ship)")
        return
    STAMP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = STAMP_DIR / f"{tree_sha()}.{tier}"
    stamp.write_text(f"{time.strftime('%Y-%m-%dT%H:%M:%S')}\n", encoding="utf-8")
    ok(f"validation stamp {stamp.name}")


def stamped_tiers(sha: str | None = None) -> set[str]:
    sha = sha or tree_sha()
    if not STAMP_DIR.is_dir():
        return set()
    return {p.name.split(".", 1)[1] for p in STAMP_DIR.glob(f"{sha}.*")}


def check_stamp() -> int:
    required, _ = classify(changed_paths())
    have = stamped_tiers()
    best = max((TIER_RANK[t] for t in have if t in TIER_RANK), default=-1)
    if required == "docs":
        good = bool(have)
    else:
        good = best >= TIER_RANK[required]
    if good:
        print(f"stamp ok: required={required} have={sorted(have)}")
        return 0
    print(f"NO VALID STAMP: required tier {required}, have {sorted(have) or 'none'} for tree {tree_sha()[:12]}")
    return 1


# --------------------------------------------------------------------------- runners
class Gate:
    def __init__(self, soft: bool) -> None:
        self.soft = soft
        self.rc = 0
        self.timings: list[tuple[str, float, bool]] = []
        self._stack_env: dict[str, str] | None = None

    def run(self, name: str, cmd: list[str], *, cwd: Path | None = None, env: dict | None = None, gate: bool = True) -> bool:
        log(f"{name}: {' '.join(cmd)}")
        start = time.monotonic()
        res = subprocess.run(cmd, cwd=str(cwd or REPO_ROOT), env={**os.environ, **(env or {})})
        took = time.monotonic() - start
        passed = res.returncode == 0
        self.timings.append((name, took, passed))
        if passed:
            ok(f"{name} ({took:.0f}s)")
        elif gate:
            fail(f"{name} ({took:.0f}s)")
            self.rc = 1
        else:
            warn(f"{name} reported problems — informational only ({took:.0f}s)")
        return passed

    def require(self, tool: str) -> bool:
        if shutil.which(tool):
            return True
        if self.soft:
            warn(f"{tool} not installed — skipping (--soft)")
            return False
        fail(f"{tool} not installed — install it (requirements-windows.txt / requirements.txt dev tools)")
        self.rc = 1
        return False

    # ---- stages -----------------------------------------------------------
    def docs(self) -> None:
        if not self._module_available("mkdocs"):
            if self.soft:
                warn("mkdocs not installed — docs tier skipped (--soft)")
                return
            fail("mkdocs not installed — the docs tier cannot pass without it (pip install mkdocs-material mkdocs-minify-plugin)")
            self.rc = 1
            return
        self.run("docs: mkdocs build --strict", [PYTHON, "-m", "mkdocs", "build", "--strict", "-q"])

    def lint(self) -> None:
        if self._module_available("pre_commit"):
            self.run("lint: pre-commit (all files)", [PYTHON, "-m", "pre_commit", "run", "--all-files"])
        else:
            self.require("pre-commit")

    def unit(self) -> None:
        cmd = [PYTHON, "-m", "pytest", "src/tests/unit/", "-m", "not slow and not harness", "--timeout=30", "-q", "-o", "addopts=", "--tb=short", "--disable-warnings", "-p", "no:cacheprovider"]
        if self._module_available("xdist") and not os.environ.get("IMOVEIS_GATE_SERIAL"):
            workers = os.environ.get("IMOVEIS_GATE_WORKERS", "8")
            cmd += ["-n", workers]
        self.run("unit: pytest src/tests/unit (not harness)", cmd)

    def harness(self) -> None:
        """Tests that spawn the gate/operator shell scripts — serial, slow on Windows."""
        self.run(
            "harness: pytest -m harness (script spawns)",
            [PYTHON, "-m", "pytest", "src/tests/unit/", "-m", "harness", "--timeout=120", "-q", "-o", "addopts=", "--tb=short", "--disable-warnings", "-p", "no:cacheprovider"],
        )

    def test_stack(self) -> bool:
        if self._stack_env is not None:
            return True
        if not shutil.which("docker"):
            fail("docker not available — backend tier needs the ephemeral test stack")
            self.rc = 1
            return False
        proj = self._test_project()
        compose = ["docker", "compose", "-f", str(REPO_ROOT / "docker-compose.test.yml"), "-p", proj]
        log(f"test stack: up (project {proj}; primary never touched)")
        start = time.monotonic()
        up = subprocess.run([*compose, "up", "-d", "--wait", "postgres", "redis"], cwd=REPO_ROOT)
        if up.returncode != 0:
            fail("test stack failed to start")
            self.rc = 1
            return False
        pg = self._compose_port(compose, "postgres", "5432")
        rd = self._compose_port(compose, "redis", "6379")
        if not pg or not rd:
            fail("could not resolve test stack ports")
            self.rc = 1
            return False
        user = os.environ.get("POSTGRES_USER", "imoveis")
        pw = os.environ.get("POSTGRES_PASSWORD", "imoveis_local_dev")
        db = os.environ.get("POSTGRES_TEST_DB", "realestate_test")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", db):
            fail(f"refusing unsafe POSTGRES_TEST_DB name: {db}")
            self.rc = 1
            return False
        url = f"postgresql://{user}:{pw}@127.0.0.1:{pg}/{db}"
        admin_url = f"postgresql://{user}:{pw}@127.0.0.1:{pg}/{os.environ.get('POSTGRES_DB', 'realestate')}"
        self._stack_env = {
            "DATABASE_URL": url,
            "REDIS_URL": f"redis://127.0.0.1:{rd}/{os.environ.get('REDIS_TEST_DB', '15')}",
        }
        os.environ.update(self._stack_env)
        self.timings.append(("test stack up", time.monotonic() - start, True))
        ok(f"test stack up (postgres:{pg} redis:{rd}) → {db}")
        return self._ensure_test_db(admin_url, url, db)

    def _ensure_test_db(self, admin_url: str, url: str, db: str) -> bool:
        code = (
            "import sys\n"
            "from sqlalchemy import create_engine, text\n"
            "admin, url, db = sys.argv[1:4]\n"
            "e = create_engine(admin, isolation_level='AUTOCOMMIT')\n"
            "with e.connect() as c:\n"
            "    if not c.execute(text('SELECT 1 FROM pg_database WHERE datname = :n'), {'n': db}).scalar():\n"
            "        c.execute(text(f'CREATE DATABASE \"{db}\"'))\n"
            "e.dispose()\n"
            "e = create_engine(url, isolation_level='AUTOCOMMIT')\n"
            "with e.connect() as c:\n"
            "    c.execute(text('CREATE EXTENSION IF NOT EXISTS postgis'))\n"
            "    c.execute(text('CREATE EXTENSION IF NOT EXISTS vector'))\n"
            "e.dispose()\n"
        )
        if not self.run("test db: create + extensions", [PYTHON, "-c", code, admin_url, url, db]):
            return False
        return self.run("test db: alembic upgrade head", [PYTHON, "-m", "alembic", "upgrade", "head"], env={"DATABASE_URL": url})

    def integration(self) -> None:
        if not self.test_stack():
            return
        self.run("integration: pytest src/tests/integration", [PYTHON, "-m", "pytest", "src/tests/integration/", "-q", "-o", "addopts=", "--tb=short", "--disable-warnings", "-p", "no:cacheprovider"])

    def contract(self) -> None:
        if not self.test_stack():
            return
        self.run("contract: pytest src/tests/contract", [PYTHON, "-m", "pytest", "src/tests/contract/", "-q", "-o", "addopts=", "--tb=short", "--disable-warnings", "-p", "no:cacheprovider"])
        # PostGIS system tables always show as drift; informational only.
        self.run("contract: alembic check", [PYTHON, "-m", "alembic", "check"], gate=False)

    def frontend(self, e2e: bool = True) -> None:
        fe = REPO_ROOT / "frontend"
        npm = shutil.which("npm")
        if not npm:
            self.require("npm")
            return
        if self._needs_npm_ci(fe):
            self.run("frontend: npm ci", [npm, "ci"], cwd=fe)
        self.run("frontend: eslint", [npm, "run", "lint", "--silent"], cwd=fe)
        self.run("frontend: vite build", [npm, "run", "build", "--silent"], cwd=fe)
        if e2e:
            port = os.environ.get("PLAYWRIGHT_PORT") or str(_free_port(5177, 5299))
            self.run(f"e2e: playwright (port {port})", [npm, "run", "test:e2e", "--silent"], cwd=fe, env={"PLAYWRIGHT_PORT": port})

    def scrapers(self) -> None:
        files = [
            "src/tests/unit/test_scraper_cassettes.py",
            "src/tests/unit/test_olx.py",
            "src/tests/unit/test_zapimoveis.py",
            "src/tests/unit/test_scoring_and_fees.py",
            "src/tests/unit/test_registry.py",
        ]
        self.run("scrapers: cassette + unit tests", [PYTHON, "-m", "pytest", *files, "-q", "--timeout=30", "-o", "addopts=", "--tb=short", "--disable-warnings", "-p", "no:cacheprovider"])
        if os.environ.get("IMOVEIS_GATE_SKIP_LIVE"):
            warn("scrapers: live dry-run skipped (IMOVEIS_GATE_SKIP_LIVE set)")
            return
        if not self.run("scrapers: live dry-run (merge-blocking)", [PYTHON, "scripts/dev/test_scraper_dryrun.py"]):
            warn("If HTTP succeeded but parsing broke, refresh cassettes: python scripts/dev/record_scraper_cassettes.py")

    def ai(self) -> None:
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        try:
            urllib.request.urlopen(f"{host}/api/tags", timeout=5)
        except Exception as exc:  # noqa: BLE001 — any failure means "not reachable"
            warn(f"ai: Ollama not reachable at {host} ({exc.__class__.__name__}) — AI golden tests SKIPPED, not passed")
            self.timings.append(("ai: golden tests (skipped)", 0.0, True))
            return
        self.run("ai: golden tests (±0.15)", [PYTHON, "-m", "pytest", "src/tests/unit/test_ai_quality.py", "-q", "--timeout=120", "-o", "addopts=", "--tb=short", "--disable-warnings", "-p", "no:cacheprovider"])

    def down(self) -> None:
        proj = self._test_project()
        subprocess.run(["docker", "compose", "-f", str(REPO_ROOT / "docker-compose.test.yml"), "-p", proj, "down", "-v", "--remove-orphans"], cwd=REPO_ROOT)
        ok(f"test stack {proj} removed")

    # ---- helpers ------------------------------------------------------------
    @staticmethod
    def _module_available(mod: str) -> bool:
        return subprocess.run([PYTHON, "-c", f"import {mod}"], capture_output=True).returncode == 0

    @staticmethod
    def _test_project() -> str:
        name = re.sub(r"[^a-z0-9]+", "-", os.environ.get("COMPOSE_PROJECT_NAME", PRIMARY_COMPOSE_PROJECT).lower()).strip("-") or PRIMARY_COMPOSE_PROJECT
        common = git("rev-parse", "--git-common-dir")
        linked = common not in (".git", str(REPO_ROOT / ".git"), (REPO_ROOT / ".git").as_posix())
        suffix = "-" + hashlib.sha1(str(REPO_ROOT).encode()).hexdigest()[:6] if linked else ""
        proj = f"{name}-test{suffix}"
        if proj == PRIMARY_COMPOSE_PROJECT:
            raise SystemExit("test project resolves to the primary project — refusing")
        return proj

    @staticmethod
    def _compose_port(compose: list[str], service: str, port: str) -> str:
        out = subprocess.run([*compose, "port", service, port], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()
        return out.rsplit(":", 1)[-1] if ":" in out else ""

    @staticmethod
    def _needs_npm_ci(fe: Path) -> bool:
        marker = fe / "node_modules" / ".package-lock.json"
        lock = fe / "package-lock.json"
        return not marker.exists() or lock.stat().st_mtime > marker.stat().st_mtime


def _free_port(start: int, end: int) -> int:
    for port in range(start, end + 1):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


# --------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tier_pos", nargs="?", choices=TIERS + ["auto", "all"], help="tier (positional alias of --tier)")
    parser.add_argument("--tier", choices=TIERS + ["auto", "all"], default=None)
    parser.add_argument("--soft", action="store_true", help="skip missing tools instead of failing (docs/rules-only work)")
    parser.add_argument("--no-extras", action="store_true", help="do not run path-triggered scraper/AI gates")
    parser.add_argument("--only", choices=["scrapers", "ai", "harness"], help="run just one domain gate and exit (nightly canary, manual re-checks)")
    parser.add_argument("--required-tier", action="store_true", help="print the tier the current diff requires and exit")
    parser.add_argument("--check-stamp", action="store_true", help="exit 0 iff HEAD's tree carries a stamp for the required tier")
    parser.add_argument("--down", action="store_true", help="tear down the ephemeral test stack and exit")
    args = parser.parse_args(argv)

    os.chdir(REPO_ROOT)
    apply_gate_env()
    gate = Gate(soft=args.soft)

    if args.down:
        gate.down()
        return 0
    if args.required_tier:
        tier, extras = classify(changed_paths())
        print(tier + ("" if not extras else " +" + ",".join(sorted(extras))))
        return 0
    if args.check_stamp:
        return check_stamp()
    if args.only:
        getattr(gate, args.only)()
        (ok if gate.rc == 0 else fail)(f"{args.only.upper()} GATE {'PASSED' if gate.rc == 0 else 'FAILED'}")
        return gate.rc

    tier = args.tier or args.tier_pos or "auto"
    if tier == "all":
        tier = "full"
    extras: set[str] = set()
    if tier == "auto":
        tier, extras = classify(changed_paths())
        log(f"auto tier: {tier}" + (f" + {', '.join(sorted(extras))}" if extras else ""))
    if args.no_extras:
        extras = set()

    log(f"gate: tier={tier} platform={sys.platform} python={PYTHON}")
    started = time.monotonic()
    if tier == "docs":
        gate.docs()
    else:
        gate.lint()
        gate.unit()
        if tier in ("backend", "full"):
            gate.integration()
            gate.contract()
        if tier in ("frontend", "full"):
            gate.frontend()
    if tier != "docs" and ("harness" in extras or tier == "full"):
        gate.harness()
    if "scrapers" in extras:
        gate.scrapers()
    if "ai" in extras:
        gate.ai()

    total = time.monotonic() - started
    print()
    for name, took, passed in gate.timings:
        print(f"  {'PASS' if passed else 'FAIL'}  {took:7.1f}s  {name}")
    if gate.rc == 0:
        ok(f"VALIDATION PASSED (tier={tier}, {total:.0f}s)")
        write_stamp(tier)
    else:
        fail(f"VALIDATION FAILED (tier={tier}, {total:.0f}s)")
    return gate.rc


if __name__ == "__main__":
    sys.exit(main())
