"""Regression: setup-worktree.sh must not create a nested worktree when the
current session is already inside one (BIN-worktree-isolation-detection).

Root cause: PRIMARY_ROOT (scripts/agent/lib.sh) always resolves to the
original checkout regardless of the current working tree, so
setup-workspace.sh's solo/parallel decision only ever looked at the
*primary's* busy/idle state. A session already isolated in its own linked
worktree (e.g. via Claude Code's EnterWorktree / Agent `isolation:
"worktree"`, or Cursor's background-agent dispatch) would still see "primary
busy" and try to `git worktree add` a second, sibling worktree relative to
primary - redundant, and a relocation outside any product-sanctioned
worktree root.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_AGENT_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts" / "agent"
_SETUP_WORKTREE = _AGENT_SCRIPTS / "setup-worktree.sh"
_LIB = _AGENT_SCRIPTS / "lib.sh"


def _init_primary_repo(tmp_path: Path) -> Path:
    primary = tmp_path / "primary_repo"
    primary.mkdir()
    run = lambda *args: subprocess.run(  # noqa: E731
        args, cwd=primary, check=True, capture_output=True, text=True
    )
    run("git", "init", "-q", "-b", "main")
    run("git", "config", "user.email", "test@example.com")
    run("git", "config", "user.name", "Test")
    (primary / "README.md").write_text("test repo\n")
    run("git", "add", "README.md")
    run("git", "commit", "-q", "-m", "init")
    return primary


@pytest.mark.unit
def test_in_linked_worktree_true_inside_worktree_false_in_primary(tmp_path: Path):
    primary = _init_primary_repo(tmp_path)
    worktree = tmp_path / "primary_repo-wt-existing"
    subprocess.run(
        ["git", "worktree", "add", "-b", "feat/existing", str(worktree)],
        cwd=primary,
        check=True,
        capture_output=True,
        text=True,
    )

    def _check(cwd: Path) -> int:
        # lib.sh runs under `set -euo pipefail`, so a bare `in_linked_worktree`
        # returning 1 would trip errexit before `echo "RC=$?"` ever runs.
        script = f'source "{_LIB}"; in_linked_worktree && echo "RC=0" || echo "RC=1"'
        completed = subprocess.run(
            ["bash", "-c", script],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        assert "RC=" in completed.stdout, completed.stdout + completed.stderr
        return int(completed.stdout.strip().rsplit("RC=", maxsplit=1)[-1])

    assert _check(primary) == 1  # primary is NOT a linked worktree
    assert _check(worktree) == 0  # linked worktree IS a linked worktree


@pytest.mark.unit
def test_setup_worktree_skips_nested_creation_when_already_isolated(tmp_path: Path):
    primary = _init_primary_repo(tmp_path)
    worktree = tmp_path / "primary_repo-wt-existing"
    subprocess.run(
        ["git", "worktree", "add", "-b", "worktree-random-name", str(worktree)],
        cwd=primary,
        check=True,
        capture_output=True,
        text=True,
    )

    before = subprocess.run(
        ["git", "worktree", "list"], cwd=primary, check=True, capture_output=True, text=True
    ).stdout

    completed = subprocess.run(
        ["bash", str(_SETUP_WORKTREE), "fix/some-slug"],
        cwd=worktree,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    after = subprocess.run(
        ["git", "worktree", "list"], cwd=primary, check=True, capture_output=True, text=True
    ).stdout
    assert before.count("\n") == after.count("\n"), (
        "setup-worktree.sh created a NEW worktree even though the session was "
        f"already isolated in one.\nbefore:\n{before}\nafter:\n{after}"
    )

    sibling_path = tmp_path / "primary_repo-wt-fix-some-slug"
    assert not sibling_path.exists(), (
        "setup-worktree.sh created a redundant sibling worktree directory "
        f"at {sibling_path} instead of configuring the current worktree in place"
    )

    assert (worktree / ".env.local").exists(), (
        "already-isolated path must still configure ports/.env.local in the "
        "CURRENT worktree"
    )

    # Last stdout line is the machine-readable worktree path — must be the
    # CURRENT worktree, not a new sibling path.
    last_line = completed.stdout.strip().splitlines()[-1]
    assert last_line == str(worktree)

    # Branch got renamed to match Conventional Branch (was "worktree-random-name").
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=worktree,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert branch == "fix/some-slug"


@pytest.mark.unit
def test_setup_worktree_still_creates_sibling_when_not_already_isolated(tmp_path: Path):
    """Unchanged behavior: invoked from the PRIMARY (not already isolated),
    setup-worktree.sh must still create the sibling worktree as before."""
    primary = _init_primary_repo(tmp_path)

    completed = subprocess.run(
        ["bash", str(_SETUP_WORKTREE), "feat/still-sibling"],
        cwd=primary,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    sibling_path = tmp_path / "primary_repo-wt-still-sibling"
    assert sibling_path.exists(), (
        "expected a new sibling worktree to be created when NOT already isolated"
        f"\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    last_line = completed.stdout.strip().splitlines()[-1]
    assert last_line == str(sibling_path)
