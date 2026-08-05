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
