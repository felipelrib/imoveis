"""Drift lock between the coverage endpoint's SQL and the runner's (v0.13-s1.6).

``adapters.db.enrichment_coverage_queries`` hand-copies two things out of
``scripts/dev/backfill_gemma.py``: the candidate predicate (which rows still
need enriching) and the photo-gate threshold (how many photos a row needs before
the runner will touch it at all). The copy exists because the script is not
importable from the API container — but a copy nobody checks is how the
dashboard's ``remaining`` silently stops describing the queue the runner works,
which is the number the whole ETA hangs off.

Nothing here modifies the script; it is imported read-only, exactly the way
``test_backfill_gemma_cli.py`` does it. When this fails, the fix is to bring the
copy in ``enrichment_coverage_queries`` back in line with the script — never to
loosen the assertion.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from adapters.db import enrichment_coverage_queries as coverage_queries

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "dev" / "backfill_gemma.py"


def _load_runner_script():
    spec = importlib.util.spec_from_file_location("backfill_gemma_drift", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalized(sql: str) -> str:
    """Collapse whitespace so re-indentation is not reported as drift."""
    return re.sub(r"\s+", " ", sql).strip()


def _cfg(*, enabled=True, min_photos=None, floor_min=8, max_images=6, ratio=1.0):
    return SimpleNamespace(
        scraping=SimpleNamespace(
            photo_gate=SimpleNamespace(
                enabled=enabled,
                min_photos=min_photos,
                floor_min=floor_min,
                coverage_ratio=ratio,
            )
        ),
        ai=SimpleNamespace(max_images_per_property=max_images),
    )


def test_the_candidate_predicate_is_the_runners_own():
    """``remaining`` must count exactly the rows the runner would pick up."""
    runner = _load_runner_script()

    assert _normalized(coverage_queries._CANDIDATES_SUBQUERY) == _normalized(
        runner._CANDIDATES_SUBQUERY
    )


@pytest.mark.parametrize(
    "cfg_kwargs",
    [
        {},
        {"enabled": False},
        {"min_photos": 3},
        {"min_photos": 0},
        {"floor_min": 12, "max_images": 20, "ratio": 0.5},
        {"floor_min": 4, "max_images": 10, "ratio": 1.0},
    ],
    ids=[
        "defaults",
        "gate-off",
        "explicit-override",
        "override-below-one",
        "derived-from-ratio",
        "derived-floor-wins",
    ],
)
def test_the_photo_threshold_agrees_with_the_runner(cfg_kwargs):
    """A stricter threshold here would hide work; a looser one unreachable work."""
    runner = _load_runner_script()
    cfg = _cfg(**cfg_kwargs)

    assert coverage_queries._min_photos_required(cfg) == runner._min_photos_required(cfg)


def test_the_threshold_is_never_zero():
    """Both sides floor at 1: a gallery-less row has nothing for the visual stage."""
    runner = _load_runner_script()

    for cfg in (_cfg(enabled=False), _cfg(min_photos=0), _cfg(min_photos=-5)):
        assert coverage_queries._min_photos_required(cfg) >= 1
        assert runner._min_photos_required(cfg) >= 1
