"""Unit tests for dual listing-type stat/z/combined scores (BIN-83)."""

from adapters.metrics.scoring import (
    _compute_type_scores,
    primary_listing_type_for_ppm,
)
from core.entities import ScoringWeights


class TestComputeTypeScores:
    def test_undervalued_rent_higher_stat_score(self):
        weights = ScoringWeights(stat_weight=0.6, ai_weight=0.4)
        stat, z, pct, combined = _compute_type_scores(
            ppm=40.0,
            mean=50.0,
            stddev=5.0,
            pct_rank=0.2,
            ai_score=0.8,
            weights=weights,
        )
        assert z < 0
        assert stat > 0.5
        assert pct == 0.2
        assert combined == stat * 0.6 + 0.8 * 0.4

    def test_overvalued_sale_lower_stat_score(self):
        weights = ScoringWeights(stat_weight=0.6, ai_weight=0.4)
        stat, z, pct, combined = _compute_type_scores(
            ppm=5000.0,
            mean=4000.0,
            stddev=500.0,
            pct_rank=0.9,
            ai_score=0.5,
            weights=weights,
        )
        assert z > 0
        assert stat < 0.5
        assert combined == stat * 0.6 + 0.5 * 0.4

    def test_none_ppm_returns_nones(self):
        weights = ScoringWeights(stat_weight=0.6, ai_weight=0.4)
        assert _compute_type_scores(
            ppm=None,
            mean=50.0,
            stddev=5.0,
            pct_rank=0.5,
            ai_score=0.0,
            weights=weights,
        ) == (None, None, None, None)


class TestDualListedDistinctScores:
    """Rent undervalued vs sale overvalued on the same property."""

    def test_rent_undervalued_sale_overvalued(self):
        weights = ScoringWeights(stat_weight=0.6, ai_weight=0.4)
        rent = _compute_type_scores(
            ppm=40.0,
            mean=50.0,
            stddev=5.0,
            pct_rank=0.1,
            ai_score=0.7,
            weights=weights,
        )
        sale = _compute_type_scores(
            ppm=5000.0,
            mean=4000.0,
            stddev=500.0,
            pct_rank=0.95,
            ai_score=0.7,
            weights=weights,
        )
        assert rent[0] != sale[0]
        assert rent[0] > sale[0]
        assert primary_listing_type_for_ppm(40.0, 5000.0) == "rent"
        assert rent[0] > 0.5
        assert sale[0] < 0.5
