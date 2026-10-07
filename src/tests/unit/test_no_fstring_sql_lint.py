"""Regression lock for the forbidden-pattern lint hooks (BIN-135 and siblings).

CLAUDE.md: "NEVER f-string SQL — parameterize." Column/fragment selection must
come from an enum/allow-list, never Python string interpolation. These tests run
``scripts/agent/lint_forbidden.py`` — the script behind the local hooks in
``.pre-commit-config.yaml`` (executed by the gate's pre-commit lint stage) — so a
pattern drift, or a regression in ``src/``, fails fast in the unit stage.

The hooks used to be ``bash -c '! grep -rnP …'``. On Windows that passed with
nothing checked whenever grep rejected the locale (``-P`` needs UTF-8), so the
script must never depend on bash, grep or the locale.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
LINT_SCRIPT = REPO_ROOT / "scripts" / "agent" / "lint_forbidden.py"

_spec = importlib.util.spec_from_file_location("imoveis_lint_forbidden", LINT_SCRIPT)
lint_forbidden = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = lint_forbidden  # dataclasses resolves annotations through sys.modules
_spec.loader.exec_module(lint_forbidden)

LINT_PATTERN = lint_forbidden.FSTRING_SQL_PATTERN
LOCAL_HOOKS = {
    "forbid-hardcoded-secrets": "secrets",
    "forbid-only": "only",
    "forbid-print": "print",
    "forbid-fstring-sql": "fstring-sql",
}


def _run(check: str, root: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run the lint as the hook does: a child process, repo root as cwd."""
    return subprocess.run(
        [sys.executable, str(LINT_SCRIPT), check],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=env,
    )


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.mark.unit
class TestNoFstringSqlLint:
    def test_current_src_is_clean(self):
        """Locks BIN-135: no f-string-built SQL left in src/ (excluding test assertions)."""
        result = _run("fstring-sql", REPO_ROOT)
        assert result.returncode == 0, f"f-string-built SQL found:\n{result.stdout}{result.stderr}"

    def test_pattern_flags_text_f_string(self):
        """Sanity: the pattern still catches the exact shape BIN-135 removed."""
        assert re.search(LINT_PATTERN, 'sql = text(f"""SELECT * FROM properties""")')

    def test_pattern_flags_inline_f_string_fragment(self):
        """Sanity: catches an f-string SQL fragment even mid-concatenation."""
        assert re.search(LINT_PATTERN, '"FROM x " f"WHERE {where} " "ORDER BY y"')

    def test_pattern_ignores_plain_concatenation(self):
        """The BIN-135 fix pattern (plain ``+`` concatenation) must not trip the gate."""
        assert not re.search(LINT_PATTERN, '"SELECT " + columns + " FROM properties p WHERE " + where')

    def test_gate_catches_injected_violation(self, tmp_path):
        """End-to-end: an injected ``text(f"...")`` violation is caught and named."""
        _write(tmp_path, "src/bad.py", 'sql = text(f"""SELECT * FROM properties""")\n')
        result = _run("fstring-sql", tmp_path)
        assert result.returncode == 1
        assert "src/bad.py:1:" in result.stdout

    def test_gate_catches_violation_without_a_utf8_locale(self, tmp_path):
        """Regression: under a non-UTF-8 locale the grep hook errored and passed vacuously."""
        _write(tmp_path, "src/bad.py", 'sql = text(f"""SELECT * FROM properties""")\n')
        env = {k: v for k, v in os.environ.items() if not k.startswith(("LC_", "LANG"))}
        result = _run("fstring-sql", tmp_path, env={**env, "LC_ALL": "C", "LANG": "C"})
        assert result.returncode == 1
        assert "src/bad.py:1:" in result.stdout

    def test_gate_ignores_test_assertions(self, tmp_path):
        """Test-file assertions on generated SQL text are not production f-string SQL."""
        _write(tmp_path, "src/tests/test_probe.py", 'assert f"ORDER BY {column} DESC" in sql\n')
        result = _run("fstring-sql", tmp_path)
        assert result.returncode == 0, result.stdout

    def test_gate_fails_when_it_cannot_search(self, tmp_path):
        """A lint that could not run must not read as clean (no ``src/`` here)."""
        result = _run("fstring-sql", tmp_path)
        assert result.returncode == 2
        assert "search root not found" in result.stderr

    def test_pre_commit_config_defines_the_hook(self):
        """The hook must stay wired into .pre-commit-config.yaml (the gate runs it via pre-commit)."""
        config = (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        assert "forbid-fstring-sql" in config

    def test_validate_sh_runs_the_hook_via_pre_commit(self):
        """The gate's lint stage runs pre-commit on ALL files, which carries the
        forbid-fstring-sql hook (the inline grep copy was replaced by the single
        pre-commit source of truth). validate.sh is a wrapper over validate.py."""
        validate_py = (REPO_ROOT / "scripts" / "agent" / "validate.py").read_text(encoding="utf-8")
        assert '"pre_commit", "run", "--all-files"' in validate_py
        validate_sh = (REPO_ROOT / "scripts" / "agent" / "validate.sh").read_text(encoding="utf-8")
        assert "validate.py" in validate_sh


@pytest.mark.unit
class TestLocalHooksNeedNoShell:
    def test_every_local_hook_runs_the_lint_script(self):
        """No local hook may go back to bash/grep: that is what made them shell- and locale-dependent."""
        config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
        local = [hook for repo in config["repos"] if repo["repo"] == "local" for hook in repo["hooks"]]
        assert {hook["id"]: hook["entry"] for hook in local} == {
            hook_id: f"python scripts/agent/lint_forbidden.py {check}" for hook_id, check in LOCAL_HOOKS.items()
        }

    @pytest.mark.parametrize("check", sorted(LOCAL_HOOKS.values()))
    def test_current_tree_is_clean(self, check):
        result = _run(check, REPO_ROOT)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_secrets_check_flags_frontend_and_backend_files(self, tmp_path):
        forbidden = "imoveis_" + "secret"  # split so this file never carries the string
        _write(tmp_path, "src/app.py", f'PASSWORD = "{forbidden}"\n')
        _write(tmp_path, "frontend/src/api.ts", "const key = 'dev-" + "secret-key'\n")
        _write(tmp_path, "frontend/src/notes.md", f"{forbidden}\n")
        result = _run("secrets", tmp_path)
        assert result.returncode == 1
        assert "src/app.py:1:" in result.stdout and "frontend/src/api.ts:1:" in result.stdout
        assert "notes.md" not in result.stdout

    def test_print_check_flags_source_but_not_tests_or_comments(self, tmp_path):
        _write(tmp_path, "src/core/thing.py", "x = 1\nprint(x)\n# print(x)\n")
        _write(tmp_path, "src/tests/unit/test_thing.py", "print('debug')\n")
        _write(tmp_path, "src/core/__init__.py", "print('boot')\n")
        result = _run("print", tmp_path)
        assert result.returncode == 1
        assert result.stdout.splitlines() == ["src/core/thing.py:2:print(x)"]

    def test_only_check_flags_focused_tests(self, tmp_path):
        _write(tmp_path, "src/tests/e2e/a.spec.js", "test.on" + "ly('x', () => {})\n")  # split: src/tests is scanned
        result = _run("only", tmp_path)
        assert result.returncode == 1
        assert "src/tests/e2e/a.spec.js:1:" in result.stdout
