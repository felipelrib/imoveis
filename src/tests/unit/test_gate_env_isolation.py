"""The gate's environment is narrowed to workspace identity (story v0.13-s3.5, DW-33).

``.env.local`` is dual-purpose: this workspace's compose/port identity *and* the
``EnvironmentFile=`` of the host-side cloud backfill runner (ADR 0006). While the
gate scripts sourced it wholesale, every variable an operator added for the
runner became ambient pytest env — the cloud key, the **primary** ``DATABASE_URL``
(seen by unit tests, which run before the ephemeral stack exports its own), and
the generic ``IMOVEIS_*`` config-override channel that rewrites config underneath
any ``load_config()`` call on a fixture YAML.

Two layers are locked here:

* ``scripts/agent/lib.sh::load_workspace_env`` — a **default-deny** allowlist
  reader, exercised by really running it in bash over fixture env files, so
  nothing an operator puts in ``.env.local`` reaches the gate process unless it
  is listed;
* ``src/tests/conftest.py`` — the invocation-independent net, whose selection
  rule (strip the whole ``IMOVEIS_*`` prefix, keep the named
  ``IMOVEIS_ALLOW_PRIMARY_*`` escape hatches) is asserted both as a pure function
  and as an observable property of ``os.environ`` inside a running test. It is
  the layer that covers variables the operator exported in their own shell, which
  no file-reading loader can unset.

Plus a source pin: any edit that lets a gate script inherit a file's environment
wholesale again — ``set -a``, sourcing an unsanctioned path (literal *or*
variable), ``eval`` of a file read — fails a test naming DW-33.

Hermetic: no container runtime, no network, never the developer's own
``.env.local`` — every bash invocation gets an explicit fixture file and a
minimal starting environment.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import PRESERVED_ENV_VARS, should_strip_env_var

REPO_ROOT = Path(__file__).resolve().parents[3]
LIB_SH = REPO_ROOT / "scripts" / "agent" / "lib.sh"
VALIDATE_SH = REPO_ROOT / "scripts" / "agent" / "validate.sh"
FINISH_SH = REPO_ROOT / "scripts" / "agent" / "finish-feature.sh"
ENV_EXAMPLE = REPO_ROOT / ".env.local.example"

_SECRET = "not-a-real-key-7b2e0d"

#: Everything the runner needs that must NOT reach the gate: the cloud key, the
#: primary DB/Redis URLs, and the config-override channel.
OPERATOR_ONLY_KEYS = (
    "GEMINI_API_KEY",
    "DATABASE_URL",
    "REDIS_URL",
    "IMOVEIS_AI__ENRICHMENT_ROUTING__VISUAL",
    "IMOVEIS_AI__ENRICHMENT_ROUTING__SENTIMENT",
    "IMOVEIS_AI__ENRICHMENT_ROUTING__DEAL_VERDICT",
)

#: Workspace identity the gate legitimately needs, with values owned by THIS test
#: rather than copied out of `.env.local.example` — editing that operator template
#: must never redden the unit stage.
WORKSPACE_FIXTURE_ENV = {
    "COMPOSE_PROJECT_NAME": "imoveis-fixture-ws",
    "POSTGRES_PORT": "55432",
    "POSTGRES_USER": "fixture-user",
    "POSTGRES_PASSWORD": "fixture-pw-not-real",
    "POSTGRES_DB": "fixture-primary",
    "POSTGRES_TEST_DB": "fixture-primary_test",
    "REDIS_PORT": "56379",
    "REDIS_TEST_DB": "14",
    "API_PORT": "58000",
    "FRONTEND_PORT": "55173",
    "PLAYWRIGHT_PORT": "55187",
    "API_KEY": "fixture-api-key",
    "TEST_DATABASE_URL": "postgresql://fixture-user:fixture-pw-not-real@localhost:55432/fixture-primary_test",
}

#: A key assignment in an env file (`export ` prefix optional).
_ASSIGNMENT_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=")


def _load_workspace_env(env_file: Path, preset: dict[str, str] | None = None) -> dict[str, str]:
    """Run ``load_workspace_env`` in a real bash and return the resulting environment.

    The starting environment is deliberately minimal (``PATH``/``HOME`` only, plus
    *preset*), so anything else in the result was put there by the loader.
    """
    script = (
        "set -euo pipefail\n"
        f'source "{LIB_SH}"\n'
        f'load_workspace_env "{env_file}"\n'
        f'exec "{sys.executable}" -c "import json,os;print(json.dumps(dict(os.environ)))"\n'
    )
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", "/tmp"),
            **(preset or {}),
        },
    )
    assert result.returncode == 0, f"load_workspace_env failed: {result.stderr}"
    return json.loads(result.stdout)


def _allowlisted_keys() -> set[str]:
    """``WORKSPACE_ENV_ALLOWLIST`` as lib.sh itself defines it."""
    result = subprocess.run(
        ["bash", "-c", f'source "{LIB_SH}"; printf "%s\\n" "$WORKSPACE_ENV_ALLOWLIST"'],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _assigned_keys(text: str) -> set[str]:
    """Every key an env file actually assigns (commented-out lines are not assignments)."""
    return {match.group(1) for line in text.splitlines() if (match := _ASSIGNMENT_RE.match(line))}


def _runner_contract_lines() -> list[str]:
    """The host-side runner's whole env contract (ADR 0006) — none of it may pass."""
    return [
        f"GEMINI_API_KEY={_SECRET}",
        "DATABASE_URL=postgresql://imoveis:pw-not-real@localhost:5432/realestate",
        "REDIS_URL=redis://localhost:6379/0",
        "IMOVEIS_AI__ENRICHMENT_ROUTING__VISUAL=gemma",
        "IMOVEIS_AI__ENRICHMENT_ROUTING__SENTIMENT=gemma",
        "IMOVEIS_AI__ENRICHMENT_ROUTING__DEAL_VERDICT=gemma",
    ]


def _operator_env_file(tmp_path: Path) -> Path:
    """A fully-populated operator ``.env.local``: workspace identity + runner contract."""
    path = tmp_path / "env.local"
    path.write_text(
        "\n".join([f"{key}={value}" for key, value in WORKSPACE_FIXTURE_ENV.items()] + _runner_contract_lines() + [""]),
        encoding="utf-8",
    )
    return path


def _uncommented_lines(script: Path) -> list[str]:
    return [line for line in script.read_text(encoding="utf-8").splitlines() if not line.strip().startswith("#")]


@pytest.mark.unit
class TestWorkspaceEnvAllowlist:
    def test_operator_env_file_yields_workspace_identity_only(self, tmp_path):
        """The whole point: workspace keys in, the runner's contract stays out.

        Asserted on KEYS and on this fixture's own values — never on whatever
        `.env.local.example` happens to ship, so editing that template cannot
        redden the gate for an unrelated reason.
        """
        loaded = _load_workspace_env(_operator_env_file(tmp_path))

        for key, value in WORKSPACE_FIXTURE_ENV.items():
            assert loaded.get(key) == value, f"{key} did not survive the allowlist"

        for key in OPERATOR_ONLY_KEYS:
            assert key not in loaded, f"{key} reached the gate environment (DW-33)"
        assert not [key for key in loaded if key.startswith("IMOVEIS_")]
        assert _SECRET not in json.dumps(loaded), "the cloud key leaked into the gate environment"

    def test_allowlist_never_carries_the_runner_contract(self):
        """The list itself is the contract: it must never gain an operator-only key."""
        allowlist = _allowlisted_keys()

        assert allowlist, "lib.sh must define WORKSPACE_ENV_ALLOWLIST"
        for key in OPERATOR_ONLY_KEYS:
            assert key not in allowlist, f"{key} was allowlisted — that re-opens DW-33"
        assert not [key for key in allowlist if key.startswith("IMOVEIS_")]

    def test_real_env_template_is_filtered_by_the_declared_allowlist(self, tmp_path):
        """The shipped operator template, checked structurally — keys, not values.

        Every key `.env.local.example` assigns survives exactly when lib.sh lists
        it; the runner contract appended below never does. Nothing here pins a
        value the operator template is free to change.
        """
        template = ENV_EXAMPLE.read_text(encoding="utf-8")
        env_file = tmp_path / "env.local"
        env_file.write_text(template + "\n" + "\n".join(_runner_contract_lines()) + "\n", encoding="utf-8")

        allowlist = _allowlisted_keys()
        template_keys = _assigned_keys(template)
        assert template_keys, "the template stopped assigning anything — this test would be vacuous"

        loaded = _load_workspace_env(env_file)
        for key in template_keys:
            if key in allowlist:
                assert key in loaded, f"allowlisted {key} was dropped"
            else:
                assert key not in loaded, f"unlisted {key} reached the gate (DW-33)"
        for key in OPERATOR_ONLY_KEYS:
            assert key not in loaded, f"{key} reached the gate environment (DW-33)"

    def test_unlisted_variable_is_denied_by_default(self, tmp_path):
        """Default-deny: a variable an operator adds tomorrow does not reach pytest."""
        env_file = tmp_path / "env.local"
        env_file.write_text(
            "API_PORT=8123\nSOME_FUTURE_OPERATOR_KNOB=on\nIMOVEIS_AI__BACKEND=gemma\n",
            encoding="utf-8",
        )
        loaded = _load_workspace_env(env_file)

        assert loaded["API_PORT"] == "8123"
        assert "SOME_FUTURE_OPERATOR_KNOB" not in loaded
        assert "IMOVEIS_AI__BACKEND" not in loaded

    def test_missing_env_file_is_a_no_op(self, tmp_path):
        """The primary checkout runs without any .env.local — that must stay silent."""
        loaded = _load_workspace_env(tmp_path / "absent")
        assert "API_PORT" not in loaded
        assert "COMPOSE_PROJECT_NAME" not in loaded

    @pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root can read a 0o000 file")
    def test_unreadable_env_file_warns_and_carries_on(self, tmp_path):
        """A present-but-unreadable file used to no-op silently behind grep errors.

        The gate must still run (it has a default for every key it needs), but the
        operator has to be told why their ports were ignored.
        """
        env_file = tmp_path / "env.local"
        env_file.write_text("API_PORT=8123\n", encoding="utf-8")
        env_file.chmod(0o000)

        script = f'source "{LIB_SH}"\nload_workspace_env "{env_file}"\necho "rc=$?"\n'
        result = subprocess.run(
            ["bash", "-c", script],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
            env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "/tmp")},
        )

        assert result.returncode == 0, result.stderr
        assert "rc=0" in result.stdout, "an unreadable env file must not abort the gate"
        assert str(env_file) in result.stderr and "readable" in result.stderr, (
            f"the skip must say which file and why: {result.stderr!r}"
        )
        assert "API_PORT" not in _load_workspace_env(env_file), "an unreadable file must not be half-applied"

    @pytest.mark.parametrize(
        "line, expected",
        [
            ("API_PORT=8000\n", "8000"),
            ("API_PORT=8000 # picked by setup-worktree.sh\n", "8000"),
            ('API_PORT="8000"\n', "8000"),
            ("API_PORT='8000'\n", "8000"),
            ('API_PORT="8000" # picked by setup-worktree.sh\n', "8000"),
            ("API_PORT='8000' # picked by setup-worktree.sh\n", "8000"),
            ("export API_PORT=8000\n", "8000"),
            ("  API_PORT=8000  \n", "8000"),
            ("API_PORT=8000\r\n", "8000"),
            ('API_PORT="8000"\r\n', "8000"),
        ],
    )
    def test_value_parsing_matches_the_env_file_dialect(self, tmp_path, line, expected):
        env_file = tmp_path / "env.local"
        env_file.write_text(line, encoding="utf-8")
        assert _load_workspace_env(env_file)["API_PORT"] == expected

    def test_quoted_value_with_an_inline_comment_keeps_neither_quotes_nor_comment(self, tmp_path):
        """`API_KEY="k" # generated` is the value `k`, exactly as `set -a; source` reads it.

        Regression: the surrounding-quote case ran *before* comment stripping, so
        a quoted value carrying a comment matched neither branch cleanly and was
        exported with its quotes still attached — the gate then authenticated with
        a literal `"k"` while Compose used `k`.
        """
        env_file = tmp_path / "env.local"
        env_file.write_text(
            'API_KEY="local dev key" # generated by setup-worktree.sh\n'
            "API_PORT=8000 # unquoted, comment still stripped\n"
            'POSTGRES_PASSWORD="pw#1"  # a hash INSIDE the quotes is part of the value\n',
            encoding="utf-8",
        )
        loaded = _load_workspace_env(env_file)

        assert loaded["API_KEY"] == "local dev key"
        assert loaded["API_PORT"] == "8000"
        assert loaded["POSTGRES_PASSWORD"] == "pw#1"

    def test_last_assignment_wins(self, tmp_path):
        env_file = tmp_path / "env.local"
        env_file.write_text("API_PORT=8000\nAPI_PORT=8123\n", encoding="utf-8")
        assert _load_workspace_env(env_file)["API_PORT"] == "8123"

    def test_values_are_literal_not_shell_expanded(self, tmp_path):
        """This is not `source`: no expansion, and nothing in the file executes."""
        env_file = tmp_path / "env.local"
        canary = tmp_path / "executed"
        env_file.write_text(
            f"POSTGRES_PASSWORD=$HOME\nAPI_KEY=$(touch '{canary}')\n",
            encoding="utf-8",
        )
        loaded = _load_workspace_env(env_file)

        assert loaded["POSTGRES_PASSWORD"] == "$HOME"
        assert loaded["API_KEY"] == "$(touch '" + str(canary) + "')"
        assert not canary.exists(), "the env file's command substitution was executed"


#: The only files a gate script may source: committed helpers in scripts/agent/
#: that carry no operator values.
SANCTIONED_SOURCES = ("lib.sh", "setup-tools.sh")

#: `source <path>` / `. <path>`, however the path is written.
_SOURCE_RE = re.compile(r"(?:^|[;&|(]|\s)(?:source|\.)\s+(?P<target>\S+)")

#: `set -a` (or `set -o allexport`) makes every later assignment an export —
#: the other half of the `set -a; source` bleed.
_ALLEXPORT_RE = re.compile(r"\bset\s+(?:-[a-zA-Z]*a[a-zA-Z]*|-o\s+allexport)\b")

#: `eval "$(cat …)"` / `eval "$(< …)"` is `source` spelled differently.
_EVAL_OF_A_FILE_RE = re.compile(r"\beval\b.*(?:\$\(\s*(?:cat|<)|`\s*cat\b|\.env)")

_DW33 = (
    "that hands the backfill runner's operator env (GEMINI_API_KEY, the primary "
    "DATABASE_URL, IMOVEIS_* config overrides) straight to pytest (DW-33). "
    "Read .env.local through load_workspace_env instead."
)


@pytest.mark.unit
class TestGateScriptsDoNotRawSourceEnvLocal:
    """Source pin: a future edit that reintroduces the bleed fails here, naming DW-33.

    Pinning the literal string ``.env.local`` was not enough — ``source
    "$ENV_FILE"``, ``eval "$(cat …)"`` or ``set -a`` before any assignment block
    reintroduce exactly the same bleed while the literal never appears.
    """

    @pytest.mark.parametrize("script", [VALIDATE_SH, FINISH_SH], ids=lambda p: p.name)
    def test_gate_script_uses_the_allowlist_loader(self, script):
        body = "\n".join(_uncommented_lines(script))
        assert "load_workspace_env" in body, f"{script.name} must read .env.local through the allowlist (DW-33)"

    @pytest.mark.parametrize("script", [VALIDATE_SH, FINISH_SH], ids=lambda p: p.name)
    def test_gate_script_sources_nothing_but_the_shared_helpers(self, script):
        offenders = [
            line
            for line in _uncommented_lines(script)
            if any(
                Path(match.group("target").strip("\"'")).name not in SANCTIONED_SOURCES
                for match in _SOURCE_RE.finditer(line)
            )
        ]
        assert not offenders, (
            f"{script.name} sources something other than {list(SANCTIONED_SOURCES)} — {_DW33} {offenders}"
        )

    @pytest.mark.parametrize("script", [VALIDATE_SH, FINISH_SH], ids=lambda p: p.name)
    def test_gate_script_never_turns_on_allexport(self, script):
        offenders = [line for line in _uncommented_lines(script) if _ALLEXPORT_RE.search(line)]
        assert not offenders, f"{script.name} enables allexport (`set -a`) — {_DW33} {offenders}"

    @pytest.mark.parametrize("script", [VALIDATE_SH, FINISH_SH], ids=lambda p: p.name)
    def test_gate_script_never_evals_a_file(self, script):
        offenders = [line for line in _uncommented_lines(script) if _EVAL_OF_A_FILE_RE.search(line)]
        assert not offenders, f"{script.name} evals a file's contents — {_DW33} {offenders}"

    @pytest.mark.parametrize(
        "snippet",
        [
            'source "$ENV_FILE"',
            "set -a; source ./.env.local; set +a",
            '. "$REPO_ROOT/.env.local"',
            'eval "$(cat .env.local)"',
            'eval "$(< "$ENV_FILE")"',
        ],
        ids=["source-variable", "set-a-source", "dot-variable", "eval-cat", "eval-read"],
    )
    def test_the_pin_would_catch_a_reintroduced_bleed(self, snippet):
        """The pin's own regression: each of these used to slip past the literal grep."""
        caught = (
            any(
                Path(match.group("target").strip("\"'")).name not in SANCTIONED_SOURCES
                for match in _SOURCE_RE.finditer(snippet)
            )
            or _ALLEXPORT_RE.search(snippet)
            or _EVAL_OF_A_FILE_RE.search(snippet)
        )
        assert caught, f"the source pin would not notice: {snippet}"

    def test_the_pin_tolerates_the_sanctioned_helper_sourcing(self):
        """Both gate scripts legitimately source lib.sh — the pin must not cry wolf."""
        for snippet in ('source "$HERE/lib.sh"', 'source "$HERE/setup-tools.sh" 2>/dev/null || true'):
            assert not [
                match
                for match in _SOURCE_RE.finditer(snippet)
                if Path(match.group("target").strip("\"'")).name not in SANCTIONED_SOURCES
            ], f"the pin flags its own sanctioned form: {snippet}"


@pytest.mark.unit
class TestSuiteWideOverrideStrip:
    """The conftest net: the whole ``IMOVEIS_*`` prefix, minus the named exceptions.

    ``_apply_env_overrides`` applies **every** ``IMOVEIS_*`` variable, not only the
    ``__``-nested ones — ``IMOVEIS_AI=x`` replaces the entire ``ai`` section with a
    string and breaks ``load_config()`` for every test after it. Default-deny over
    the prefix is therefore the rule; ``IMOVEIS_ALLOW_PRIMARY_*_WIPE`` (BIN-71 /
    BIN-117) are the only survivors, and they are read by fixtures, never by the
    config loader.
    """

    @pytest.mark.parametrize(
        "name",
        [
            "IMOVEIS_AI__ENRICHMENT_ROUTING__VISUAL",
            "IMOVEIS_AI__BACKEND",
            "IMOVEIS_APP__DEBUG",
            "IMOVEIS_DATABASE__NAME",
            # No `__`, and still an override: this addresses the TOP-LEVEL `ai`
            # key, replacing the whole section with a string.
            "IMOVEIS_AI",
            "IMOVEIS_BACKFILL",
            # Not a config leaf at all — but default-deny does not have to know that.
            "IMOVEIS_SUITE_SENTINEL",
        ],
    )
    def test_prefixed_names_are_stripped(self, name):
        assert should_strip_env_var(name)

    @pytest.mark.parametrize(
        "name",
        [
            # BIN-71 / BIN-117 destructive-action escape hatches: the suite and the
            # scripts set these for themselves and nothing in infra.config reads them.
            "IMOVEIS_ALLOW_PRIMARY_DB_WIPE",
            "IMOVEIS_ALLOW_PRIMARY_REDIS_WIPE",
            "DATABASE_URL",
            "API_KEY",
            "IMOVEIS",
        ],
    )
    def test_non_override_names_survive(self, name):
        assert not should_strip_env_var(name)

    def test_the_preserved_set_is_exactly_the_two_escape_hatches(self):
        """Adding a name here re-opens the DW-33 channel for it — make that deliberate."""
        assert PRESERVED_ENV_VARS == {"IMOVEIS_ALLOW_PRIMARY_DB_WIPE", "IMOVEIS_ALLOW_PRIMARY_REDIS_WIPE"}

    def test_no_config_override_is_visible_inside_a_test(self):
        """Whatever the invocation, a test body never sees the operator's overrides.

        The module-scoped fixture below plants them *before* this runs, so an
        absent variable proves the autouse strip ran — not that it was never set.
        """
        leaked = [key for key in os.environ if should_strip_env_var(key)]
        assert not leaked, f"config overrides visible to the suite (DW-33): {leaked}"

    def test_a_prefixed_name_without_the_nesting_channel_is_stripped_too(self):
        """``IMOVEIS_AI=x`` would replace the whole ``ai`` section with a string."""
        assert "IMOVEIS_AI" not in os.environ

    def test_the_destructive_action_escape_hatches_survive(self):
        """BIN-71 / BIN-117: the suite's own guards must reach the isolation fixtures."""
        assert os.environ.get("IMOVEIS_ALLOW_PRIMARY_DB_WIPE") == "0"


@pytest.fixture(autouse=True, scope="module")
def _operator_overrides_planted():
    """Simulate an operator env that reached the interpreter, for this module only.

    Module scope means it is set up *before* the function-scoped conftest guard,
    which is exactly the ordering the guard exists for. The escape hatch is
    planted at ``"0"``: ``db_isolation`` honours it only at the literal ``"1"``,
    so survival is observable without ever granting consent to wipe anything.
    """
    planted = {
        "IMOVEIS_AI__ENRICHMENT_ROUTING__VISUAL": "gemma",
        "IMOVEIS_AI": "not-a-mapping",
        "IMOVEIS_ALLOW_PRIMARY_DB_WIPE": "0",
    }
    previous = {key: os.environ.get(key) for key in planted}
    os.environ.update(planted)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
