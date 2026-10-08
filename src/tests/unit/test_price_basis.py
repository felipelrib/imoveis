"""Cohort price basis rules (Story 1.3, AD-3) — written before ``core/price_basis.py``.

A rent Listing contributes its fee-exclusive ``rent_monthly`` when it has one
and its headline ``price`` otherwise; a Property keeps its lowest cohort price
per listing type and the basis of the Listing that supplied it.
"""

from __future__ import annotations

import ast
import statistics
from pathlib import Path

import pytest

from adapters.metrics.scoring import _compute_type_scores
from core.entities import ScoringWeights
from core.price_basis import (
    COHORT_PRICE_FOR_TYPE_SQL,
    COHORT_PRICE_SQL,
    PRICE_BASES,
    PRICE_BASIS_HEADLINE,
    PRICE_BASIS_HEADLINE_SQL,
    PRICE_BASIS_RENT_MONTHLY,
    CohortPrice,
    listing_cohort_price,
    property_cohort_prices,
    row_price_basis,
)

pytestmark = pytest.mark.unit

MODULE_PATH = Path(__file__).resolve().parents[2] / "core" / "price_basis.py"
AREA_M2 = 100.0


def _rent(price, rent_monthly=None, *, active=True) -> dict:
    return {
        "listing_type": "rent",
        "price": price,
        "rent_monthly": rent_monthly,
        "active": active,
    }


def _sale(price, rent_monthly=None, *, active=True) -> dict:
    return {
        "listing_type": "sale",
        "price": price,
        "rent_monthly": rent_monthly,
        "active": active,
    }


class TestContract:
    def test_vocabulary(self):
        assert PRICE_BASIS_RENT_MONTHLY == "rent_monthly"
        assert PRICE_BASIS_HEADLINE == "headline"
        assert set(PRICE_BASES) == {"rent_monthly", "headline"}
        assert PRICE_BASIS_HEADLINE_SQL == "'headline'"

    def test_module_imports_no_adapters_api_or_infra(self):
        """AD-1: the definition module is pure — no outer-layer import, lazy or not."""
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"), filename=str(MODULE_PATH))
        forbidden = ("adapters", "api", "infra")
        offenders: list[str] = []
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, "relative imports are not used in core"
                names = [node.module or ""]
            offenders.extend(name for name in names if name.split(".")[0] in forbidden)
        assert offenders == []

    def test_scoring_selects_no_listing_price_of_its_own(self):
        """The cohort price comes from this module; scoring.py never reads ``pl.price``."""
        scoring = MODULE_PATH.parents[1] / "adapters" / "metrics" / "scoring.py"
        source = scoring.read_text(encoding="utf-8")
        assert "pl.price" not in source
        assert "MIN(pl." not in source

    def test_sql_is_static_text_with_one_bound_parameter(self):
        """BIN-135: constants only; the per-type relation binds ``:lt``."""
        for sql in (COHORT_PRICE_SQL, COHORT_PRICE_FOR_TYPE_SQL):
            assert isinstance(sql, str)
            assert "{" not in sql and "%" not in sql
            assert "rent_monthly" in sql
            for forbidden in ("total_monthly_cost", "condo_fee", "iptu"):
                assert forbidden not in sql
        assert ":lt" in COHORT_PRICE_FOR_TYPE_SQL
        assert ":" not in COHORT_PRICE_SQL


class TestListingCohortPrice:
    def test_rent_listing_with_unbundled_rent(self):
        assert listing_cohort_price(**_rent(3800, 3000)) == CohortPrice(3000.0, "rent_monthly")

    def test_rent_listing_without_it_keeps_the_headline(self):
        assert listing_cohort_price(**_rent(3500, None)) == CohortPrice(3500.0, "headline")

    @pytest.mark.parametrize("rent_monthly", [0, 0.0, -1, -3000.0])
    def test_zero_or_negative_rent_is_absent(self, rent_monthly):
        assert listing_cohort_price(**_rent(3500, rent_monthly)) == CohortPrice(3500.0, "headline")

    def test_rent_above_the_headline_is_still_the_rent(self):
        """The rule is 'the unbundled rent when known', not 'the lower figure'."""
        assert listing_cohort_price(**_rent(3000, 3200)) == CohortPrice(3200.0, "rent_monthly")

    def test_sale_listing_is_always_the_published_price(self):
        assert listing_cohort_price(**_sale(500_000)) == CohortPrice(500_000.0, "headline")
        # A stray rent figure on a sale row never changes a sale cohort.
        assert listing_cohort_price(**_sale(500_000, 3000)) == CohortPrice(500_000.0, "headline")

    @pytest.mark.parametrize("price", [0, -1, None])
    def test_unpriced_listing_contributes_nothing(self, price):
        assert listing_cohort_price(**_rent(price, 3000)) is None

    @pytest.mark.parametrize("active", [False, None])
    def test_inactive_listing_contributes_nothing(self, active):
        assert listing_cohort_price(**_rent(3500, 1000, active=active)) is None

    def test_unknown_listing_type_contributes_nothing(self):
        assert (
            listing_cohort_price(listing_type="season", price=3500, rent_monthly=3000, active=True)
            is None
        )


class TestPropertyCohortPrices:
    def test_two_rent_listings_both_with_rent(self):
        prices = property_cohort_prices([_rent(3900, 3000), _rent(4100, 3200)])
        assert prices == {"rent": CohortPrice(3000.0, "rent_monthly")}

    def test_mixed_listings_headline_lower(self):
        prices = property_cohort_prices([_rent(3800, 3000), _rent(2500, None)])
        assert prices == {"rent": CohortPrice(2500.0, "headline")}

    def test_mixed_listings_rent_lower(self):
        prices = property_cohort_prices([_rent(3800, 3000), _rent(3500, None)])
        assert prices == {"rent": CohortPrice(3000.0, "rent_monthly")}

    @pytest.mark.parametrize("order", [(0, 1), (1, 0)])
    def test_exact_tie_goes_to_rent_monthly_in_any_order(self, order):
        listings = [_rent(3800, 3000), _rent(3000, None)]
        prices = property_cohort_prices([listings[i] for i in order])
        assert prices == {"rent": CohortPrice(3000.0, "rent_monthly")}

    def test_inactive_listing_holding_the_rent_is_ignored(self):
        prices = property_cohort_prices([_rent(1800, 1000, active=False), _rent(3500, None)])
        assert prices == {"rent": CohortPrice(3500.0, "headline")}

    def test_sale_only_property(self):
        prices = property_cohort_prices([_sale(500_000)])
        assert prices == {"sale": CohortPrice(500_000.0, "headline")}
        assert prices["sale"].price / AREA_M2 == 5000.0

    def test_dual_rent_and_sale(self):
        prices = property_cohort_prices([_rent(3800, 3000), _sale(500_000), _sale(520_000)])
        assert prices == {
            "rent": CohortPrice(3000.0, "rent_monthly"),
            "sale": CohortPrice(500_000.0, "headline"),
        }

    def test_no_listings(self):
        assert property_cohort_prices([]) == {}

    def test_accepts_any_mapping_and_ignores_extra_keys(self):
        row = {**_rent(3800, 3000), "platform": "quintoandar", "id": "x"}
        assert property_cohort_prices([row]) == {"rent": CohortPrice(3000.0, "rent_monthly")}


class TestRowPriceBasis:
    def test_stamp_is_the_rent_basis(self):
        assert row_price_basis("rent_monthly") == "rent_monthly"
        assert row_price_basis("headline") == "headline"

    def test_row_without_a_rent_price_is_headline(self):
        """Sale-only rows and legacy rows have no Listing-supplied rent basis."""
        assert row_price_basis(None) == "headline"

    def test_anything_outside_the_vocabulary_is_rejected(self):
        with pytest.raises(ValueError):
            row_price_basis("total_monthly_cost")


class TestMixedBasisCohort:
    """Both bases share one cohort's statistics; each row keeps its own stamp."""

    def test_mean_median_z_and_stamps(self):
        members = [
            property_cohort_prices([_rent(3800, 3000)])["rent"],
            property_cohort_prices([_rent(4000, 4000)])["rent"],
            property_cohort_prices([_rent(5000, None)])["rent"],
        ]
        ppm = [member.price / AREA_M2 for member in members]
        assert ppm == [30.0, 40.0, 50.0]
        assert [member.price_basis for member in members] == [
            "rent_monthly",
            "rent_monthly",
            "headline",
        ]

        mean, median, stddev = statistics.mean(ppm), statistics.median(ppm), statistics.stdev(ppm)
        assert (mean, median, stddev) == (40.0, 40.0, 10.0)

        weights = ScoringWeights(stat_weight=1.0, ai_weight=0.0, neighbourhood_weight=0.0)
        scored = [
            _compute_type_scores(
                ppm=value, mean=mean, stddev=stddev, pct_rank=None, ai_score=0.0, weights=weights
            )
            for value in ppm
        ]
        assert [z for _stat, z, _pct, _combined in scored] == [-1.0, 0.0, 1.0]
        stats = [stat for stat, _z, _pct, _combined in scored]
        assert stats[0] > stats[1] == 0.5 > stats[2]

    def test_fee_inclusive_and_fee_exclusive_peers_get_the_same_price(self):
        quintoandar = property_cohort_prices([_rent(3800, 3000)])["rent"]
        zapimoveis = property_cohort_prices([_rent(3000, 3000)])["rent"]
        assert quintoandar == zapimoveis == CohortPrice(3000.0, "rent_monthly")
