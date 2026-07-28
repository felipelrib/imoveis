"""BIN-97 / BIN-101 — catalog stable scoring codes; numeric path is locale-invariant."""

from __future__ import annotations

from adapters.metrics.scoring import _sigmoid_undervalued, _stat_analysis, blend_combined_score
from core.entities import ScoringWeights

# Locked catalog for BIN-101 — snake_case codes; display copy lives in SPA catalogs.
STAT_BAND_CODES = {
    -2.0: "highly_undervalued",
    -0.5: "slightly_undervalued",
    0.0: "average",
    0.5: "slightly_overvalued",
    2.0: "highly_overvalued",
}


class TestStatAnalysisLocaleCatalog:
    def test_all_bands_match_stable_codes(self):
        for z, expected_cat in STAT_BAND_CODES.items():
            result = _stat_analysis(z)
            assert result["category"] == expected_cat
            assert result["reasoning"] == ""

    def test_numeric_sigmoid_and_blend_are_language_agnostic(self):
        low = _sigmoid_undervalued(-1.0)
        high = _sigmoid_undervalued(1.0)
        assert low > high  # cheaper → higher undervaluation score

        weights = ScoringWeights(stat_weight=0.5, ai_weight=0.3, neighbourhood_weight=0.2)
        a = blend_combined_score(0.8, 0.6, 0.4, weights)
        b = blend_combined_score(0.8, 0.6, 0.4, weights)
        assert a == b
        assert 0.0 <= a <= 1.0
