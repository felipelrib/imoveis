"""Regression lock for finish-feature.sh's feature-doc gate key derivation.

setup-branch.sh sanitizes branch slugs (dots → dashes), so the gate must
derive canonical dotted story keys from BOTH `feat/v0.13-s1.1-…` and the
sanitized `feat/v0-13-s1-1-…` forms — otherwise every setup-branch-created
story branch silently skips the NON-NEGOTIABLE feature-doc gate
(v0.13-fu1 harness surgery, post-merge fix).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FINISH_SH = REPO_ROOT / "scripts" / "agent" / "finish-feature.sh"


def _derive(branch: str) -> tuple[int, str]:
    script = (
        f'source <(sed -n "/^derive_story_key/,/^}}/p" "{FINISH_SH}"); '
        f'BRANCH="{branch}"; derive_story_key'
    )
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=False
    )
    return result.returncode, result.stdout.strip()


@pytest.mark.unit
class TestDeriveStoryKey:
    @pytest.mark.parametrize(
        ("branch", "expected"),
        [
            ("feat/v0.13-s1.1-some-slug", "v0.13-s1.1"),
            ("feat/v0-13-s1-1-some-slug", "v0.13-s1.1"),  # sanitized form
            ("feat/v0.13-fu1-harness-surgery", "v0.13-fu1"),
            ("feat/v0-13-fu1-status-done", "v0.13-fu1"),  # sanitized form
            ("feat/v0.13-fu1", "v0.13-fu1"),  # bare key, no slug
            ("fix/bin-147-legacy-thing", "BIN-147"),
        ],
    )
    def test_derives_canonical_dotted_key(self, branch, expected):
        rc, key = _derive(branch)
        assert rc == 0
        assert key == expected

    @pytest.mark.parametrize("branch", ["chore/random-cleanup", "feat/no-key-here"])
    def test_keyless_branches_fail_derivation(self, branch):
        rc, _ = _derive(branch)
        assert rc != 0


@pytest.mark.unit
class TestBmadLoopBranchRefusal:
    """v0.13-fu11: bmad-loop worktree branches are merged by the bmad-loop
    orchestrator after its review pass — finish-feature.sh must refuse them
    with an explicit message, and the refusal must never be "fixed" by adding
    `bmad-loop` to VALID_BRANCH_TYPES (two merge machineries racing on one
    branch desyncs the orchestrator's run state)."""

    def test_finish_refuses_bmad_loop_branch_naming_the_orchestrator(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "init"], check=True)
        subprocess.run(
            git + ["checkout", "-q", "-b", "bmad-loop/20260812-0000-test/3-4-x"],
            check=True,
        )
        result = subprocess.run(
            ["bash", str(FINISH_SH), "--dry-run"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1
        assert "orchestrator" in result.stderr
        assert "DRY RUN" not in result.stdout  # died before doing anything

    def test_bmad_loop_is_not_a_valid_branch_type(self):
        lib = (REPO_ROOT / "scripts" / "agent" / "lib.sh").read_text()
        types_line = next(
            line for line in lib.splitlines() if line.startswith("VALID_BRANCH_TYPES=")
        )
        assert "bmad-loop" not in types_line
