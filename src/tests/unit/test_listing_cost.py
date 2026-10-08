"""Unit tests for the Total Monthly Cost rules (Story 1.1, FR-31, AD-3).

Written before ``core/listing_cost.py``: the I/O matrix of the story, the
periodicity thresholds, rounding, declared vs inferred periodicity and the
reconstruction of the same inputs from rows stored before the story.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from core.listing_cost import (
    COST_COLUMNS,
    build_cost_source,
    compute_listing_cost,
    listing_cost_columns,
)

pytestmark = pytest.mark.unit

MODULE_PATH = Path(__file__).resolve().parents[2] / "core" / "listing_cost.py"


def _rent(**kwargs) -> dict:
    return compute_listing_cost(listing_type="rent", **kwargs)


def _sale(**kwargs) -> dict:
    return compute_listing_cost(listing_type="sale", **kwargs)


class TestContract:
    def test_cost_columns_are_the_seven_typed_columns(self):
        assert COST_COLUMNS == (
            "rent_monthly",
            "condo_fee_monthly",
            "iptu_monthly",
            "iptu_periodicity_source",
            "fees_bundled",
            "total_monthly_cost",
            "cost_complete",
        )

    def test_result_carries_exactly_the_cost_columns(self):
        assert tuple(_rent(rent=1000, condo_fee=100, iptu=50)) == COST_COLUMNS

    def test_module_imports_no_adapters_api_or_infra(self):
        """AD-1: the rule module is pure — no outer-layer import, lazy or not."""
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
            offenders.extend(
                name for name in names if name.split(".")[0] in forbidden
            )
        assert offenders == []


class TestMatrix:
    def test_quintoandar_itemized(self):
        cost = _rent(rent=750, condo_fee=120, iptu=59, iptu_periodicity="monthly")
        assert cost == {
            "rent_monthly": 750.0,
            "condo_fee_monthly": 120.0,
            "iptu_monthly": 59.0,
            "iptu_periodicity_source": "monthly",
            "fees_bundled": False,
            "total_monthly_cost": 929.0,
            "cost_complete": True,
        }

    def test_quintoandar_bundled(self):
        cost = _rent(rent=800, fees_combined=57, iptu_periodicity="monthly")
        assert cost == {
            "rent_monthly": 800.0,
            "condo_fee_monthly": 57.0,
            "iptu_monthly": None,
            "iptu_periodicity_source": "unknown",
            "fees_bundled": True,
            "total_monthly_cost": 857.0,
            "cost_complete": True,
        }

    def test_quintoandar_remainder_only(self):
        """condoIptu 0 and no itemized fee: nothing is derived from totalCost."""
        cost = _rent(rent=780, condo_fee=None, iptu=None, fees_combined=0, iptu_periodicity="monthly")
        assert cost["rent_monthly"] == 780.0
        assert cost["condo_fee_monthly"] is None
        assert cost["iptu_monthly"] is None
        assert cost["fees_bundled"] is False
        assert cost["total_monthly_cost"] is None
        assert cost["cost_complete"] is False

    @pytest.mark.parametrize("iptu", [None, 0, 0.0, "0", -5])
    def test_olx_missing_fee_is_unknown_not_zero(self, iptu):
        cost = _rent(rent=3500, condo_fee=650, iptu=iptu)
        assert cost["rent_monthly"] == 3500.0
        assert cost["condo_fee_monthly"] == 650.0
        assert cost["iptu_monthly"] is None
        assert cost["iptu_periodicity_source"] == "unknown"
        assert cost["total_monthly_cost"] is None
        assert cost["cost_complete"] is False

    def test_zap_annual_iptu_is_divided(self):
        cost = _rent(rent=4700, condo_fee=480, iptu=4940)
        assert cost["iptu_periodicity_source"] == "annual"
        assert cost["iptu_monthly"] == 411.67
        assert cost["total_monthly_cost"] == 5591.67
        assert cost["cost_complete"] is True

    def test_zap_monthly_iptu(self):
        cost = _rent(rent=3500, condo_fee=400, iptu=273)
        assert cost["iptu_periodicity_source"] == "monthly"
        assert cost["iptu_monthly"] == 273.0
        assert cost["total_monthly_cost"] == 4173.0
        assert cost["cost_complete"] is True

    def test_ambiguous_iptu_is_unknown_and_never_divided(self):
        cost = _rent(rent=4000, condo_fee=500, iptu=1000)
        assert cost["iptu_periodicity_source"] == "unknown"
        assert cost["iptu_monthly"] is None
        assert cost["total_monthly_cost"] is None
        assert cost["cost_complete"] is False

    def test_sale_listing_has_components_but_no_total(self):
        cost = _sale(sale_price=450000, condo_fee=600, iptu=1857)
        assert cost == {
            "rent_monthly": None,
            "condo_fee_monthly": 600.0,
            "iptu_monthly": 154.75,
            "iptu_periodicity_source": "annual",
            "fees_bundled": False,
            "total_monthly_cost": None,
            "cost_complete": False,
        }

    @pytest.mark.parametrize("rent", [None, 0, -100, "", "abc"])
    def test_rent_unknown_leaves_inferred_periodicity_unknown(self, rent):
        cost = _rent(rent=rent, condo_fee=400, iptu=273)
        assert cost["rent_monthly"] is None
        assert cost["iptu_periodicity_source"] == "unknown"
        assert cost["iptu_monthly"] is None
        assert cost["total_monthly_cost"] is None
        assert cost["cost_complete"] is False

    def test_rent_unknown_keeps_a_declared_periodicity(self):
        cost = _rent(rent=0, condo_fee=120, iptu=59, iptu_periodicity="monthly")
        assert cost["rent_monthly"] is None
        assert cost["iptu_periodicity_source"] == "monthly"
        assert cost["iptu_monthly"] == 59.0
        assert cost["total_monthly_cost"] is None


class TestInvariants:
    CASES = [
        dict(listing_type="rent", rent=750, condo_fee=120, iptu=59, iptu_periodicity="monthly"),
        dict(listing_type="rent", rent=800, fees_combined=57),
        dict(listing_type="rent", rent=3500, condo_fee=650),
        dict(listing_type="rent", rent=3500, iptu=273),
        dict(listing_type="rent", rent=None, condo_fee=1, iptu=1),
        dict(listing_type="rent", rent=4000, condo_fee=1, iptu=1000),
        dict(listing_type="sale", sale_price=450000, condo_fee=600, iptu=1857),
        dict(listing_type="sale", sale_price=450000, fees_combined=700),
        dict(listing_type="other", rent=1000, condo_fee=10, iptu=10),
    ]

    @pytest.mark.parametrize("kwargs", CASES)
    def test_cost_complete_iff_total_is_not_null(self, kwargs):
        cost = compute_listing_cost(**kwargs)
        assert cost["cost_complete"] is (cost["total_monthly_cost"] is not None)

    @pytest.mark.parametrize("kwargs", CASES)
    def test_periodicity_is_one_of_the_three_values(self, kwargs):
        assert compute_listing_cost(**kwargs)["iptu_periodicity_source"] in (
            "monthly",
            "annual",
            "unknown",
        )

    def test_no_component_is_ever_zero(self):
        cost = _rent(rent=0, condo_fee=0, iptu=0, fees_combined=0)
        assert cost["rent_monthly"] is None
        assert cost["condo_fee_monthly"] is None
        assert cost["iptu_monthly"] is None

    def test_total_is_exactly_the_three_components(self):
        cost = _rent(rent=1234.5, condo_fee=321.25, iptu=45.1)
        assert cost["total_monthly_cost"] == pytest.approx(1234.5 + 321.25 + 45.1)

    def test_separate_fee_wins_over_a_combined_figure(self):
        """A combined figure only bundles when no fee is published separately."""
        cost = _rent(rent=750, condo_fee=120, iptu=None, fees_combined=179)
        assert cost["fees_bundled"] is False
        assert cost["condo_fee_monthly"] == 120.0
        assert cost["iptu_monthly"] is None
        assert cost["total_monthly_cost"] is None

    def test_sale_never_carries_rent_or_total_even_when_bundled(self):
        cost = _sale(sale_price=450000, rent=3000, fees_combined=700)
        assert cost["rent_monthly"] is None
        assert cost["fees_bundled"] is True
        assert cost["condo_fee_monthly"] == 700.0
        assert cost["total_monthly_cost"] is None
        assert cost["cost_complete"] is False

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), 10**400, True, [], {}])
    def test_unparseable_figures_are_unknown(self, value):
        cost = _rent(rent=value, condo_fee=value, iptu=value)
        assert cost["rent_monthly"] is None
        assert cost["condo_fee_monthly"] is None
        assert cost["iptu_monthly"] is None

    def test_numeric_strings_are_accepted(self):
        cost = _rent(rent="3500", condo_fee="400.50", iptu="273")
        assert cost["total_monthly_cost"] == 4173.5


class TestPeriodicityThresholds:
    @pytest.mark.parametrize(
        ("iptu", "expected"),
        [
            (600, "monthly"),      # exactly 15% of rent
            (600.01, "unknown"),   # just inside the ambiguity band
            (1599.99, "unknown"),  # just below 40%
            (1600, "annual"),      # exactly 40% of rent
        ],
    )
    def test_rent_boundaries(self, iptu, expected):
        assert _rent(rent=4000, condo_fee=1, iptu=iptu)["iptu_periodicity_source"] == expected

    @pytest.mark.parametrize(
        ("iptu", "expected"),
        [
            (500, "monthly"),      # exactly 0.10% of the sale price
            (500.01, "unknown"),
            (1249.99, "unknown"),
            (1250, "annual"),      # exactly 0.25% of the sale price
        ],
    )
    def test_sale_boundaries(self, iptu, expected):
        assert _sale(sale_price=500000, iptu=iptu)["iptu_periodicity_source"] == expected

    def test_sale_without_a_reference_price_is_unknown(self):
        cost = _sale(sale_price=None, condo_fee=600, iptu=1857)
        assert cost["iptu_periodicity_source"] == "unknown"
        assert cost["iptu_monthly"] is None
        assert cost["condo_fee_monthly"] == 600.0

    def test_declared_monthly_overrides_magnitude(self):
        cost = _rent(rent=1000, condo_fee=1, iptu=900, iptu_periodicity="monthly")
        assert cost["iptu_periodicity_source"] == "monthly"
        assert cost["iptu_monthly"] == 900.0

    def test_declared_annual_is_divided_whatever_the_magnitude(self):
        cost = _rent(rent=4000, condo_fee=1, iptu=120, iptu_periodicity="annual")
        assert cost["iptu_periodicity_source"] == "annual"
        assert cost["iptu_monthly"] == 10.0

    def test_unrecognized_declaration_falls_back_to_magnitude(self):
        cost = _rent(rent=3500, condo_fee=1, iptu=273, iptu_periodicity="yearly-ish")
        assert cost["iptu_periodicity_source"] == "monthly"

    def test_periodicity_is_unknown_when_there_is_no_iptu(self):
        cost = _rent(rent=750, condo_fee=120, iptu=None, iptu_periodicity="monthly")
        assert cost["iptu_periodicity_source"] == "unknown"


class TestRounding:
    @pytest.mark.parametrize(
        ("annual", "monthly"),
        [(4940, 411.67), (1857, 154.75), (1000, 83.33), (2000, 166.67), (1234.56, 102.88), (2400.06, 200.01)],
    )
    def test_annual_is_divided_by_twelve_and_rounded_to_cents(self, annual, monthly):
        cost = _rent(rent=1000, condo_fee=1, iptu=annual, iptu_periodicity="annual")
        assert cost["iptu_monthly"] == monthly

    def test_total_is_rounded_to_cents(self):
        cost = _rent(rent=0.1, condo_fee=0.2, iptu=0.3, iptu_periodicity="monthly")
        assert cost["total_monthly_cost"] == 0.6


class TestBuildCostSource:
    def test_shape_is_the_five_stamped_keys(self):
        stamp = build_cost_source(rent=750, condo_fee=120, iptu=59)
        assert stamp == {
            "rent": 750.0,
            "condo_fee": 120.0,
            "iptu": 59.0,
            "fees_combined": None,
            "iptu_periodicity": None,
        }

    def test_raw_zero_is_kept_as_published_and_garbage_is_none(self):
        stamp = build_cost_source(rent="3500", condo_fee=0, iptu="n/a", fees_combined=57, iptu_periodicity="monthly")
        assert stamp == {
            "rent": 3500.0,
            "condo_fee": 0.0,
            "iptu": None,
            "fees_combined": 57.0,
            "iptu_periodicity": "monthly",
        }

    def test_stamp_is_json_serializable(self):
        stamp = build_cost_source(rent=float("nan"), condo_fee=float("inf"), iptu=1)
        assert json.loads(json.dumps(stamp, allow_nan=False)) == stamp


def _listing(**overrides) -> dict:
    base = {
        "platform": "zapimoveis",
        "listing_type": "rent",
        "price": 1000.0,
        "base_price": None,
        "condo_fee": None,
        "iptu": None,
        "raw_json": {},
    }
    base.update(overrides)
    return base


class TestStampedListing:
    def test_stamp_is_the_only_input_for_a_rent_listing(self):
        """Headline columns are ignored once the scraper stamped the raw figures."""
        listing = _listing(
            platform="olx",
            price=4150.0,          # headline: rent + condo + 0
            base_price=9999.0,     # must not be read
            condo_fee=1.0,
            iptu=1.0,
            raw_json={
                "fees_bundled": False,
                "cost_source": build_cost_source(rent=3500, condo_fee=650, iptu=0),
            },
        )
        cost = listing_cost_columns(listing)
        assert cost["rent_monthly"] == 3500.0
        assert cost["condo_fee_monthly"] == 650.0
        assert cost["iptu_monthly"] is None
        assert cost["total_monthly_cost"] is None

    def test_sale_listing_classifies_against_its_own_price(self):
        listing = _listing(
            listing_type="sale",
            price=450000.0,
            raw_json={"cost_source": build_cost_source(rent=None, condo_fee=600, iptu=1857)},
        )
        cost = listing_cost_columns(listing)
        assert cost["iptu_periodicity_source"] == "annual"
        assert cost["iptu_monthly"] == 154.75
        assert cost["total_monthly_cost"] is None

    def test_raw_json_may_arrive_as_a_json_string(self):
        stamp = build_cost_source(rent=3500, condo_fee=400, iptu=273)
        listing = _listing(raw_json=json.dumps({"cost_source": stamp}))
        assert listing_cost_columns(listing)["total_monthly_cost"] == 4173.0

    def test_non_dict_stamp_falls_back_to_the_legacy_fields(self):
        listing = _listing(price=3500.0, condo_fee=400.0, iptu=273.0, raw_json={"cost_source": "oops"})
        assert listing_cost_columns(listing)["total_monthly_cost"] == 4173.0


class TestLegacyReconstruction:
    """Rows stored before the story carry no ``cost_source`` stamp."""

    @pytest.mark.parametrize("raw_json", [None, "", "{not json", "[1, 2]", 42, "null"])
    def test_malformed_raw_json_is_treated_as_empty(self, raw_json):
        listing = _listing(price=3500.0, condo_fee=400.0, iptu=273.0, raw_json=raw_json)
        assert listing_cost_columns(listing)["total_monthly_cost"] == 4173.0

    def test_zap_rent_uses_price(self):
        listing = _listing(price=4700.0, base_price=4700.0, condo_fee=480.0, iptu=4940.0,
                           raw_json={"fees_bundled": False})
        cost = listing_cost_columns(listing)
        assert cost["rent_monthly"] == 4700.0
        assert cost["iptu_periodicity_source"] == "annual"
        assert cost["total_monthly_cost"] == 5591.67

    def test_zap_sale_uses_price_as_reference(self):
        listing = _listing(listing_type="sale", price=450000.0, base_price=450000.0,
                           condo_fee=600.0, iptu=1857.0)
        cost = listing_cost_columns(listing)
        assert cost["rent_monthly"] is None
        assert cost["iptu_monthly"] == 154.75

    def test_olx_rent_uses_base_price_never_the_summed_headline(self):
        listing = _listing(platform="olx", price=4150.0, base_price=3500.0,
                           condo_fee=650.0, iptu=0.0, raw_json={"fees_bundled": False})
        cost = listing_cost_columns(listing)
        assert cost["rent_monthly"] == 3500.0
        assert cost["condo_fee_monthly"] == 650.0
        assert cost["iptu_monthly"] is None
        assert cost["cost_complete"] is False

    def test_olx_rent_without_base_price_is_unknown(self):
        listing = _listing(platform="olx", price=4150.0, base_price=None, condo_fee=650.0, iptu=100.0)
        cost = listing_cost_columns(listing)
        assert cost["rent_monthly"] is None
        assert cost["total_monthly_cost"] is None

    def test_quintoandar_itemized(self):
        listing = _listing(platform="quintoandar", price=929.0, base_price=750.0,
                           condo_fee=120.0, iptu=59.0,
                           raw_json={"partial_price": 750, "fees_bundled": False})
        cost = listing_cost_columns(listing)
        assert cost["rent_monthly"] == 750.0
        assert cost["iptu_periodicity_source"] == "monthly"
        assert cost["total_monthly_cost"] == 929.0

    def test_quintoandar_bundled_condo_iptu(self):
        listing = _listing(
            platform="quintoandar", price=857.0, base_price=800.0, condo_fee=57.0, iptu=None,
            raw_json={
                "partial_price": 800,
                "fees_bundled": True,
                "fees_note": "condoIptu is a bundled condo+IPTU field",
            },
        )
        cost = listing_cost_columns(listing)
        assert cost["fees_bundled"] is True
        assert cost["condo_fee_monthly"] == 57.0
        assert cost["iptu_monthly"] is None
        assert cost["total_monthly_cost"] == 857.0

    def test_quintoandar_derived_remainder_is_not_a_fee(self):
        listing = _listing(
            platform="quintoandar", price=815.0, base_price=780.0, condo_fee=35.0, iptu=None,
            raw_json={
                "partial_price": 780,
                "fees_bundled": True,
                "fees_note": "condo+IPTU derived from totalCost - rentPrice",
            },
        )
        cost = listing_cost_columns(listing)
        assert cost["rent_monthly"] == 780.0
        assert cost["condo_fee_monthly"] is None
        assert cost["fees_bundled"] is False
        assert cost["total_monthly_cost"] is None

    def test_quintoandar_bundled_without_a_note_is_not_trusted(self):
        listing = _listing(platform="quintoandar", price=815.0, base_price=780.0, condo_fee=35.0,
                           raw_json={"partial_price": 780, "fees_bundled": True})
        cost = listing_cost_columns(listing)
        assert cost["condo_fee_monthly"] is None
        assert cost["fees_bundled"] is False

    def test_quintoandar_rent_falls_back_to_base_price(self):
        listing = _listing(platform="quintoandar", price=929.0, base_price=750.0,
                           condo_fee=120.0, iptu=59.0, raw_json={})
        assert listing_cost_columns(listing)["rent_monthly"] == 750.0

    def test_quintoandar_sale_declares_monthly_iptu(self):
        listing = _listing(platform="quintoandar", listing_type="sale", price=450000.0,
                           condo_fee=600.0, iptu=1857.0,
                           raw_json={"partial_price": 450000, "fees_bundled": False})
        cost = listing_cost_columns(listing)
        assert cost["rent_monthly"] is None
        assert cost["iptu_periodicity_source"] == "monthly"
        assert cost["iptu_monthly"] == 1857.0
        assert cost["total_monthly_cost"] is None

    def test_unknown_platform_never_reads_the_headline_as_rent(self):
        listing = _listing(platform="vivareal", price=3000.0, base_price=None, condo_fee=300.0, iptu=100.0)
        cost = listing_cost_columns(listing)
        assert cost["rent_monthly"] is None
        assert cost["total_monthly_cost"] is None
