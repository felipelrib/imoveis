"""Regression: docker-cleanup must drop feat/wt images and keep the primary stack."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_LIB = (
    Path(__file__).resolve().parents[3] / "scripts" / "agent" / "docker-cleanup-lib.sh"
)


def _should_remove(repo: str, active_projects: str = "") -> bool:
    script = f"""
set -euo pipefail
# shellcheck disable=SC1091
source "{_LIB}"
if should_remove_temporary_image_repo "{repo}" "{active_projects}"; then
  exit 0
fi
exit 1
"""
    completed = subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in (0, 1):
        pytest.fail(
            f"helper failed for repo={repo!r}: rc={completed.returncode} "
            f"stderr={completed.stderr!r}"
        )
    return completed.returncode == 0


@pytest.mark.unit
@pytest.mark.parametrize(
    ("repo", "active", "expect_remove"),
    [
        # Primary fixed stack — never remove
        ("imoveis-api", "", False),
        ("imoveis-postgres", "", False),
        ("imoveis-worker_scraper", "", False),
        ("imoveis", "", False),
        # Third-party / base — never treated as temporary
        ("redis", "", False),
        ("postgres", "", False),
        ("ghcr.io/github/github-mcp-server", "", False),
        # Leftover feature / worktree images — remove when idle
        ("feat-bin-64-english-listing-accuracy-api", "", True),
        ("fix-olx-backfill-script-postgres", "", True),
        ("imoveis-wt-bin-53-load-neighbourhood-polygons-api", "", True),
        ("chore-some-task-api", "", True),
        # Active parallel agent project — keep sibling images
        (
            "feat-bin-84-rent-sale-price-per-m2-cohorts-api",
            "feat-bin-84-rent-sale-price-per-m2-cohorts",
            False,
        ),
        (
            "feat-bin-84-rent-sale-price-per-m2-cohorts-postgres",
            "feat-bin-84-rent-sale-price-per-m2-cohorts",
            False,
        ),
        # Different feat project still removable while another is active
        (
            "feat-bin-64-english-listing-accuracy-api",
            "feat-bin-84-rent-sale-price-per-m2-cohorts",
            True,
        ),
        # Primary running should not protect unrelated feat images
        ("feat-old-feature-api", "imoveis", True),
        # Primary project must not shield imoveis-wt-* via prefix (feature 62)
        ("imoveis-wt-bin-53-load-neighbourhood-polygons-api", "imoveis", True),
        # Active worktree project keeps its own images
        (
            "imoveis-wt-bin-53-load-neighbourhood-polygons-api",
            "imoveis-wt-bin-53-load-neighbourhood-polygons",
            False,
        ),
    ],
)
def test_should_remove_temporary_image_repo(
    repo: str, active: str, expect_remove: bool
) -> None:
    assert _should_remove(repo, active) is expect_remove
