"""Unit tests for photo gate heuristic (BIN-78)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.entities import PropertyCandidate
from core.photo_gate import (
    count_photos,
    effective_min_photos,
    passes_photo_gate,
    photo_gate_kwargs_from_config,
)


@pytest.mark.unit
class TestEffectiveMinPhotos:
    def test_defaults_match_stock_ai_budget(self):
        # floor 8, ceil(8 * 1.0) = 8 → 8
        assert effective_min_photos() == 8

    def test_scales_with_larger_vlm_budget(self):
        # floor 8, ceil(12 * 1.0) = 12 → 12
        assert effective_min_photos(max_images_per_property=12) == 12

    def test_floor_dominates_when_budget_small(self):
        # floor 8, ceil(5 * 0.4) = 2 → 8
        assert effective_min_photos(
            floor_min=8, max_images_per_property=5, coverage_ratio=0.4
        ) == 8

    def test_zero_budget_falls_back_to_floor(self):
        assert effective_min_photos(max_images_per_property=0, floor_min=8) == 8

    def test_coverage_clamped(self):
        assert effective_min_photos(coverage_ratio=2.0, max_images_per_property=8) == 8


@pytest.mark.unit
class TestPassesPhotoGate:
    def _cand(self, n: int) -> PropertyCandidate:
        urls = [f"https://cdn.example/{i}.jpg" for i in range(n)]
        return PropertyCandidate(
            platform="olx",
            platform_id=f"p-{n}",
            price=2000.0,
            image_urls=urls,
        )

    def test_rejects_empty_gallery(self):
        ok, reason, count, required = passes_photo_gate(self._cand(0))
        assert ok is False
        assert count == 0
        assert required == 8
        assert reason and reason.startswith("too_few_photos")

    def test_rejects_seven_photos(self):
        ok, reason, count, required = passes_photo_gate(self._cand(7))
        assert ok is False
        assert count == 7
        assert required == 8
        assert "7<8" in (reason or "")

    def test_allows_eight_photos(self):
        ok, reason, count, required = passes_photo_gate(self._cand(8))
        assert ok is True
        assert reason is None
        assert count == 8
        assert required == 8

    def test_disabled_always_allows(self):
        ok, reason, count, required = passes_photo_gate(self._cand(0), enabled=False)
        assert ok is True
        assert reason is None
        assert count == 0
        assert required == 8

    def test_min_photos_override(self):
        ok, _, count, required = passes_photo_gate(self._cand(4), min_photos=5)
        assert ok is False
        assert count == 4
        assert required == 5

    def test_ignores_blank_urls(self):
        cand = SimpleNamespace(image_urls=["https://a.jpg", "", "  ", None, "https://b.jpg"])
        assert count_photos(cand.image_urls) == 2
        ok, _, count, _ = passes_photo_gate(cand, min_photos=2)
        assert ok is True
        assert count == 2


@pytest.mark.unit
def test_photo_gate_kwargs_from_config():
    scraping = SimpleNamespace(enabled=True, floor_min=8, coverage_ratio=1.0, min_photos=None)
    ai = SimpleNamespace(max_images_per_property=8)
    kwargs = photo_gate_kwargs_from_config(scraping, ai)
    urls = [f"https://cdn.example/{i}.jpg" for i in range(8)]
    ok, _, _, required = passes_photo_gate(SimpleNamespace(image_urls=urls), **kwargs)
    assert ok is True
    assert required == 8
