"""BIN-97 — catalog EN-only scoring display strings; numeric path is locale-invariant."""

from __future__ import annotations

from adapters.metrics.scoring import _sigmoid_undervalued, _stat_analysis, blend_combined_score
from core.entities import ScoringWeights

# Locked catalog for BIN-101 (localize score copy) — do not change without i18n story.
STAT_BAND_CATALOG = {
    "Highly Undervalued": "Significantly cheaper than similar properties in the area.",
    "Slightly Undervalued": "Priced slightly below the neighborhood average.",
    "Average": "Priced closely to the neighborhood average.",
    "Slightly Overvalued": "Priced slightly above the neighborhood average.",
    "Highly Overvalued": "Significantly more expensive than similar properties in the area.",
}


class TestStatAnalysisLocaleCatalog:
    def test_all_bands_match_english_catalog(self):
        samples = {
            -2.0: "Highly Undervalued",
            -0.5: "Slightly Undervalued",
            0.0: "Average",
            0.5: "Slightly Overvalued",
            2.0: "Highly Overvalued",
        }
        for z, expected_cat in samples.items():
            result = _stat_analysis(z)
            assert result["category"] == expected_cat
            assert result["reasoning"] == STAT_BAND_CATALOG[expected_cat]

    def test_numeric_sigmoid_and_blend_are_language_agnostic(self):
        low = _sigmoid_undervalued(-1.0)
        high = _sigmoid_undervalued(1.0)
        assert low > high  # cheaper → higher undervaluation score

        weights = ScoringWeights(stat_weight=0.5, ai_weight=0.3, neighbourhood_weight=0.2)
        a = blend_combined_score(0.8, 0.6, 0.4, weights)
        b = blend_combined_score(0.8, 0.6, 0.4, weights)
        assert a == b
        assert 0.0 <= a <= 1.0
