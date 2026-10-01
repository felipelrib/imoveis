"""Native host gate behavior; run through validate.sh on Windows and POSIX."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.shell_helpers import BASH

ROOT = Path(__file__).resolve().parents[3]
LIB = ROOT / "scripts" / "agent" / "lib.sh"
pytestmark = pytest.mark.unit


def _bash(body: str, *, cwd: Path = ROOT, env: dict | None = None):
    result = subprocess.run(
        [BASH, "-c", f'source "{LIB.as_posix()}"; {body}'],
        cwd=cwd,
        env={**os.environ, **(env or {})},
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def test_native_primary_root_is_not_a_linked_worktree(tmp_path):
    primary = tmp_path / "primary with spaces"
    primary.mkdir()
    subprocess.run(["git", "init", "-q", str(primary)], check=True)
    result = _bash(
        'if in_linked_worktree; then echo linked; else echo primary; fi', cwd=primary
    )
    assert result == "primary"


@pytest.mark.parametrize("linked", [False, True])
def test_project_python_wins_and_paths_with_spaces_are_executable(tmp_path, linked):
    project = tmp_path / "project with spaces"
    # A real native virtualenv verifies execution, not just which path was chosen.
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(project / ".venv")], check=True)
    checkout = tmp_path / "linked checkout" if linked else project
    checkout.mkdir(exist_ok=True)
    result = _bash(
        f'REPO_ROOT="{checkout.as_posix()}"; PRIMARY_ROOT="{project.as_posix()}"; activate_project_python; '
        '"$PYTHON_BIN" -c "import sys; print(sys.prefix)"'
    )
    assert Path(result).resolve() == (project / ".venv").resolve()


def test_python_path_preserves_existing_native_paths_with_spaces(tmp_path):
    extra = tmp_path / "extra modules"
    extra.mkdir()
    (extra / "migration_probe.py").write_text("VALUE = 314\n", encoding="utf-8")
    result = _bash(
        'activate_project_python; prepend_python_path "$REPO_ROOT/src"; '
        '"$PYTHON_BIN" -c "import json,infra,migration_probe; '
        'print(json.dumps([infra.__path__[0], migration_probe.VALUE]))"',
        env={"PYTHONPATH": str(extra)},
    )
    actual, value = json.loads(result)
    assert Path(actual).resolve() == (ROOT / "src" / "infra").resolve()
    assert value == 314


def test_python_path_preserves_multiple_native_entries(tmp_path):
    extra = tmp_path / "first modules"
    other = tmp_path / "second modules"
    extra.mkdir()
    other.mkdir()
    (extra / "first_probe.py").write_text("VALUE = 1\n", encoding="utf-8")
    (other / "second_probe.py").write_text("VALUE = 2\n", encoding="utf-8")
    result = _bash(
        'activate_project_python; prepend_python_path "$REPO_ROOT/src"; '
        '"$PYTHON_BIN" -c "import first_probe,second_probe; '
        'print(first_probe.VALUE + second_probe.VALUE)"',
        env={"PYTHONPATH": os.pathsep.join([str(extra), str(other)])},
    )
    assert result == "3"
