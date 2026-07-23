"""Unit tests for scoring helpers and QuintoAndar fee extraction."""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import pytest

from adapters.metrics.scoring import (
    MIN_NEIGHBORHOOD_SAMPLE,
    _combined_score,
    _has_ai_score,
    _sample_is_insufficient,
    _sigmoid_undervalued,
    _stat_analysis_for_z,
)
from adapters.scrapers.quintoandar import QuintoAndarScraper
from core.entities import ScoringWeights


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


class TestSigmoidUndervalued:
    def test_zero_z_is_half(self):
        assert _sigmoid_undervalued(0.0) == pytest.approx(0.5)

    def test_negative_z_scores_higher(self):
        assert _sigmoid_undervalued(-2.0) > _sigmoid_undervalued(0.0)
        assert _sigmoid_undervalued(-2.0) == pytest.approx(1.0 / (1.0 + math.exp(-2.0)))

    def test_positive_z_scores_lower(self):
        assert _sigmoid_undervalued(2.0) < 0.5


class TestCombinedScore:
    def setup_method(self):
        self.weights = ScoringWeights(stat_weight=0.5, ai_weight=0.5)

    def test_renormalizes_when_ai_absent(self):
        assert _combined_score(0.9, None, self.weights) == pytest.approx(0.9)
        assert _combined_score(0.9, 0.0, self.weights) == pytest.approx(0.9)

    def test_blends_when_ai_present(self):
        assert _combined_score(1.0, 0.0, self.weights) == pytest.approx(1.0)
        assert _combined_score(1.0, 1.0, self.weights) == pytest.approx(1.0)
        assert _combined_score(0.8, 0.6, self.weights) == pytest.approx(0.7)

    def test_ai_only_when_stat_insufficient(self):
        assert _combined_score(None, 0.75, self.weights) == pytest.approx(0.75)

    def test_both_missing(self):
        assert _combined_score(None, None, self.weights) is None
        assert _combined_score(None, 0.0, self.weights) is None

    def test_has_ai_score(self):
        assert _has_ai_score(None) is False
        assert _has_ai_score(0.0) is False
        assert _has_ai_score(0.1) is True


class TestInsufficientSample:
    def test_below_min_count(self):
        assert _sample_is_insufficient(MIN_NEIGHBORHOOD_SAMPLE - 1, 10.0) is True

    def test_zero_stddev(self):
        assert _sample_is_insufficient(10, 0.0) is True
        assert _sample_is_insufficient(10, None) is True

    def test_enough_peers(self):
        assert _sample_is_insufficient(MIN_NEIGHBORHOOD_SAMPLE, 5.0) is False

    def test_stat_analysis_flag(self):
        analysis = _stat_analysis_for_z(None, insufficient=True)
        assert analysis["insufficient_sample"] is True
        assert analysis["category"] == "Insufficient Data"


# ---------------------------------------------------------------------------
# QuintoAndar fee extraction / normalize
# ---------------------------------------------------------------------------


@pytest.fixture
def qa_scraper():
    return QuintoAndarScraper(
        "quintoandar",
        {"rate_limit": 30, "extra": {"city_slug": "belo-horizonte-mg-brasil"}},
    )


def _qa_raw(**overrides):
    data = {
        "id": "895549038",
        "type": "Apartamento",
        "neighbourhood": "Alvorada",
        "address": {"address": "Rua Faria Pereira", "city": "Belo Horizonte"},
        "area": 38,
        "bedrooms": 1,
        "bathrooms": 1,
        "parkingSpaces": 0,
        "photos": [],
        "location": {"lat": -19.9, "lon": -43.9},
        "rentPrice": 750,
        "totalCost": 929,
        "salePrice": 0,
    }
    data.update(overrides)
    return data


class TestQuintoAndarFees:
    def test_derives_bundled_fees_from_total_minus_base(self, qa_scraper):
        result = qa_scraper.normalize(_qa_raw())
        rent = next(l for l in result["listings"] if l["listing_type"] == "rent")
        assert rent["price"] == 929
        assert rent["raw_json"]["partial_price"] == 750
        assert rent["condo_fee"] == pytest.approx(179.0)
        assert rent["iptu"] is None
        assert rent["raw_json"]["fees_bundled"] is True

    def test_separate_condo_and_iptu(self, qa_scraper):
        result = qa_scraper.normalize(
            _qa_raw(condoFee=120, iptu=59, condoIptu=None, totalCost=929)
        )
        rent = next(l for l in result["listings"] if l["listing_type"] == "rent")
        assert rent["condo_fee"] == pytest.approx(120.0)
        assert rent["iptu"] == pytest.approx(59.0)
        assert rent["raw_json"].get("fees_bundled") is None

    def test_bundled_condo_iptu_field(self, qa_scraper):
        result = qa_scraper.normalize(
            _qa_raw(condoIptu=179, totalCost=929, rentPrice=750)
        )
        rent = next(l for l in result["listings"] if l["listing_type"] == "rent")
        assert rent["condo_fee"] == pytest.approx(179.0)
        assert rent["iptu"] is None
        assert rent["raw_json"]["fees_bundled"] is True

    def test_unknown_fees_are_none_not_zero(self, qa_scraper):
        result = qa_scraper.normalize(
            _qa_raw(rentPrice=900, totalCost=900, condoFee=None, iptu=None, condoIptu=None)
        )
        rent = next(l for l in result["listings"] if l["listing_type"] == "rent")
        assert rent["condo_fee"] is None
        assert rent["iptu"] is None
        assert rent["price"] == 900

    def test_equal_total_and_base_no_phantom_fees(self, qa_scraper):
        """First screenshot case: total == base → no derived fees."""
        result = qa_scraper.normalize(_qa_raw(rentPrice=900, totalCost=900))
        rent = next(l for l in result["listings"] if l["listing_type"] == "rent")
        assert rent["condo_fee"] is None
        assert rent["iptu"] is None


# ---------------------------------------------------------------------------
# Bulk SQL syntax (mocked session still exercises query construction)
# ---------------------------------------------------------------------------


class TestComputeNeighborhoodStatsSql:
    def test_sql_starts_with_with(self):
        """Regression: CTE must start with WITH, not bare 'stats AS ('."""
        from adapters.metrics import scoring as scoring_mod

        captured = {}

        class FakeResult:
            def fetchall(self):
                return []

        class FakeSession:
            def execute(self, sql, params=None):
                captured["sql"] = str(sql)
                captured["params"] = params
                return FakeResult()

            def query(self, *a, **k):
                raise AssertionError("should not query when no rows")

            def flush(self):
                pass

        with patch.object(scoring_mod, "get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                scoring=MagicMock(stat_weight=0.5, ai_weight=0.5)
            )
            count = scoring_mod.compute_neighborhood_stats(FakeSession())

        assert count == 0
        sql_text = captured["sql"].strip().upper()
        assert sql_text.startswith("WITH STATS AS")
        assert "MIN_SAMPLE" in str(captured["params"]).upper() or captured["params"].get(
            "min_sample"
        ) == MIN_NEIGHBORHOOD_SAMPLE
