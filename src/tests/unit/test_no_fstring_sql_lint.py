"""Regression lock for the BIN-135 "no f-string-built SQL" lint gate.

CLAUDE.md: "NEVER f-string SQL — parameterize." Column/fragment selection must
come from an enum/allow-list, never Python string interpolation. This test
runs the exact grep pattern wired into ``.pre-commit-config.yaml``
(``forbid-fstring-sql``) and ``scripts/agent/validate.sh`` (``run_lint``) so
a drift between the two copies, or a regression in ``src/``, fails fast in
unit CI rather than only showing up in a pre-commit/CI lint job.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# Kept identical to .pre-commit-config.yaml's forbid-fstring-sql entry and
# scripts/agent/validate.sh's run_lint step.
LINT_PATTERN = (
    r"(\btext\(\s*f['\"]|\bf['\"][^'\"]*\b(SELECT|INSERT|UPDATE|DELETE|WHERE|FROM|ORDER BY)\b)"
)


def _grep_src(root: Path) -> str:
    result = subprocess.run(
        ["grep", "-rnP", LINT_PATTERN, str(root / "src"), "--include=*.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    lines = [line for line in result.stdout.splitlines() if "/tests/" not in line]
    return "\n".join(lines)


@pytest.mark.unit
class TestNoFstringSqlLint:
    def test_current_src_is_clean(self):
        """Locks BIN-135: no f-string-built SQL left in src/ (excluding test assertions)."""
        matches = _grep_src(REPO_ROOT)
        assert matches == "", f"f-string-built SQL found:\n{matches}"

    def test_pattern_flags_text_f_string(self):
        """Sanity: the pattern still catches the exact shape BIN-135 removed."""
        assert re.search(LINT_PATTERN, 'sql = text(f"""SELECT * FROM properties""")')

    def test_pattern_flags_inline_f_string_fragment(self):
        """Sanity: catches an f-string SQL fragment even mid-concatenation."""
        assert re.search(LINT_PATTERN, '"FROM x " f"WHERE {where} " "ORDER BY y"')

    def test_pattern_ignores_plain_concatenation(self):
        """The BIN-135 fix pattern (plain ``+`` concatenation) must not trip the gate."""
        assert not re.search(LINT_PATTERN, '"SELECT " + columns + " FROM properties p WHERE " + where')

    def test_grep_gate_catches_injected_violation(self, tmp_path):
        """End-to-end: an injected ``text(f"...")`` violation is caught by the real grep gate."""
        probe_src = tmp_path / "src"
        probe_src.mkdir()
        (probe_src / "bad.py").write_text('sql = text(f"""SELECT * FROM properties""")\n')
        matches = _grep_src(tmp_path)
        assert "bad.py" in matches

    def test_grep_gate_ignores_test_assertions(self, tmp_path):
        """Test-file assertions on generated SQL text are not production f-string SQL."""
        probe_src = tmp_path / "src" / "tests"
        probe_src.mkdir(parents=True)
        (probe_src / "test_probe.py").write_text(
            'assert f"ORDER BY {column} DESC" in sql\n'
        )
        matches = _grep_src(tmp_path)
        assert matches == ""

    def test_pre_commit_config_defines_the_hook(self):
        """The hook must stay wired into .pre-commit-config.yaml (CI runs it via pre-commit)."""
        config = (REPO_ROOT / ".pre-commit-config.yaml").read_text()
        assert "forbid-fstring-sql" in config

    def test_validate_sh_defines_the_check(self):
        """validate.sh's run_lint must also run this check (fast local feedback)."""
        validate_sh = (REPO_ROOT / "scripts" / "agent" / "validate.sh").read_text()
        assert "no f-string-built SQL" in validate_sh
