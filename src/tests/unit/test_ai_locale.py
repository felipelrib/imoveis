"""BIN-101 — stable AI category codes + legacy EN title normalization."""

from __future__ import annotations

import pytest

from core.ai_locale import (
    normalize_sentiment_category,
    normalize_stat_analysis_meta,
    normalize_stat_category,
    normalize_visual_category,
)


@pytest.mark.unit
class TestNormalizeStatCategory:
    def test_legacy_en_titles(self):
        assert normalize_stat_category("Highly Undervalued") == "highly_undervalued"
        assert normalize_stat_category("Slightly Overvalued") == "slightly_overvalued"
        assert normalize_stat_category("Average") == "average"

    def test_codes_passthrough(self):
        assert normalize_stat_category("highly_undervalued") == "highly_undervalued"

    def test_meta_clears_reasoning_for_known_codes(self):
        out = normalize_stat_analysis_meta(
            {"category": "Highly Undervalued", "reasoning": "old EN prose"}
        )
        assert out["category"] == "highly_undervalued"
        assert out["reasoning"] == ""


@pytest.mark.unit
class TestNormalizeVisualSentiment:
    def test_visual_legacy_and_codes(self):
        assert normalize_visual_category("Needs Renovation") == "needs_renovation"
        assert normalize_visual_category("pristine") == "pristine"
        assert normalize_visual_category("Pristine") == "pristine"

    def test_sentiment_legacy_and_codes(self):
        assert normalize_sentiment_category("Highly Desirable") == "highly_desirable"
        assert normalize_sentiment_category("undesirable") == "undesirable"
        assert normalize_sentiment_category("Standard") == "average"
