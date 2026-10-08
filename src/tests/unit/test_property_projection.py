"""Unit tests for AD-12 canonical property projection."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.property_projection import (
    LISTINGS_JSON_AGG,
    decisioning_price,
    listing_cost_view,
    map_property_detail,
    map_property_list_item,
    neighborhood_fields,
    project_listing,
    select_deciding_listing,
    select_primary_listing,
)


def test_listings_subquery_filters_inactive():
    """BIN-80: API must not emit soft-deactivated listings."""
    assert "pl.active = true" in LISTINGS_JSON_AGG


def _listing(**overrides):
    base = {
        "platform": "quintoandar",
        "platform_listing_id": "1",
        "listing_type": "rent",
        "price": 3000.0,
        "currency": "BRL",
        "url": "https://example.com/1",
        "is_furnished": False,
        "accepts_pets": True,
        "condo_fee": 500.0,
        "iptu": 100.0,
    }
    base.update(overrides)
    return base


class TestSelectPrimaryListing:
    def test_empty_returns_none(self):
        assert select_primary_listing(None) is None
        assert select_primary_listing([]) is None

    def test_single_listing(self):
        listing = _listing(price=2500.0)
        assert select_primary_listing([listing])["price"] == 2500.0

    def test_lowest_price_wins(self):
        listings = [
            _listing(platform="a", price=4000.0),
            _listing(platform="b", price=2800.0),
            _listing(platform="c", price=3500.0),
        ]
        primary = select_primary_listing(listings)
        assert primary["platform"] == "b"
        assert primary["price"] == 2800.0

    def test_tie_prefers_rent_over_sale(self):
        listings = [
            _listing(platform="zap", listing_type="sale", price=2000.0),
            _listing(platform="qa", listing_type="rent", price=2000.0),
        ]
        primary = select_primary_listing(listings)
        assert primary["listing_type"] == "rent"
        assert primary["platform"] == "qa"

    def test_tie_same_type_prefers_platform_asc(self):
        listings = [
            _listing(platform="zap", listing_type="rent", price=2000.0),
            _listing(platform="olx", listing_type="rent", price=2000.0),
        ]
        primary = select_primary_listing(listings)
        assert primary["platform"] == "olx"

    def test_unpriced_listings_ignored(self):
        listings = [
            _listing(platform="a", price=None),
            _listing(platform="b", price=3100.0),
        ]
        primary = select_primary_listing(listings)
        assert primary["platform"] == "b"

    def test_all_unpriced_returns_none(self):
        assert select_primary_listing([_listing(price=None)]) is None


class TestDecisioningPrice:
    def test_uses_primary_when_present(self):
        assert decisioning_price(9999.0, {"price": 2500.0}) == 2500.0

    def test_falls_back_to_row_price(self):
        assert decisioning_price(9999.0, None) == 9999.0


class TestNeighborhoodFields:
    def test_id_and_label_from_row(self):
        row = {
            "neighborhood_id": "nbr-1",
            "neighborhood_name": "Savassi",
            "props_json": {},
        }
        assert neighborhood_fields(row) == {
            "neighborhood_id": "nbr-1",
            "neighborhood_name": "Savassi",
            "city": None,
        }

    def test_name_falls_back_to_props_json(self):
        row = {
            "neighborhood_id": None,
            "neighborhood_name": None,
            "props_json": {"neighborhood": "Lourdes"},
        }
        fields = neighborhood_fields(row)
        assert fields["neighborhood_id"] is None
        assert fields["neighborhood_name"] == "Lourdes"

    def test_humanizes_slug_and_projects_city(self):
        from core.property_projection import format_location_label

        row = {
            "neighborhood_id": None,
            "neighborhood_name": None,
            "city": "Belo Horizonte",
            "props_json": {"neighborhood": "sion", "city": "Belo Horizonte"},
        }
        fields = neighborhood_fields(row)
        assert fields["neighborhood_name"] == "Sion"
        assert fields["city"] == "Belo Horizonte"
        assert format_location_label(fields["neighborhood_name"], fields["city"]) == (
            "Sion, Belo Horizonte"
        )

    def test_drops_city_as_neighborhood(self):
        row = {
            "neighborhood_id": None,
            "neighborhood_name": "São Paulo",
            "city": "São Paulo",
            "props_json": {},
        }
        fields = neighborhood_fields(row)
        assert fields["neighborhood_name"] is None
        assert fields["city"] == "São Paulo"


class TestMapPropertyProjection:
    def _row(self, **overrides):
        base = {
            "id": "prop-1",
            "public_id": 14,
            "platform": "quintoandar",
            "platform_id": "qa-1",
            "title": "Apt",
            "price": 5000.0,
            "area_m2": 80.0,
            "bedrooms": 2,
            "bathrooms": 1,
            "address": "Rua A",
            "image_urls": [],
            "first_seen": SimpleNamespace(isoformat=lambda: "2026-01-01T00:00:00"),
            "lat": -19.9,
            "lon": -43.9,
            "stat_score": 0.5,
            "ai_score": 0.6,
            "combined_score": 0.7,
            "percentile_rank": 0.8,
            "z_score": -0.2,
            "price_per_m2": 50.0,
            "neighborhood_mean": 55.0,
            "neighborhood_median": 54.0,
            "price_per_m2_rent": 50.0,
            "price_per_m2_sale": None,
            "neighborhood_mean_rent": 55.0,
            "neighborhood_mean_sale": None,
            "stat_score_rent": 0.82,
            "stat_score_sale": 0.41,
            "z_score_rent": -0.5,
            "z_score_sale": 0.8,
            "percentile_rank_rent": 0.2,
            "percentile_rank_sale": 0.9,
            "combined_score_rent": 0.79,
            "combined_score_sale": 0.52,
            "neighborhood_id": "nbr-9",
            "neighborhood_name": "Savassi",
            "parking": 1,
            "description": "Nice",
            "props_json": {"available_for_rent": True, "available_for_sale": False},
            "meta": {
                "visual": {
                    "features_detected": ["balcony"],
                    "issues_detected": [],
                    "condition_score": 0.75,
                    "category": "good",
                    "reasoning": "ok",
                },
                "sentiment": {
                    "green_flags": ["light"],
                    "red_flags": [],
                    "sentiment_score": 0.78,
                    "category": "positive",
                    "reasoning": "fine",
                },
                "stat_analysis": {"category": "deal", "reasoning": "cheap"},
                "deal_verdict": {"verdict": "Buy"},
            },
            "listings": [
                _listing(platform="zap", listing_type="sale", price=4500.0),
                _listing(platform="qa", listing_type="rent", price=2800.0),
            ],
        }
        base.update(overrides)
        return base

    def test_list_item_includes_primary_and_neighborhood_id(self):
        mapped = map_property_list_item(self._row())
        assert mapped["public_id"] == 14
        assert mapped["neighborhood_id"] == "nbr-9"
        assert mapped["neighborhood_name"] == "Savassi"
        assert mapped["primary_listing"]["price"] == 2800.0
        assert mapped["price"] == 2800.0
        assert mapped["price_per_m2"] == 50.0
        assert mapped["price_per_m2_rent"] == 50.0
        assert mapped["neighborhood_mean_rent"] == 55.0
        assert mapped["combined_score"] == 0.7
        assert mapped["combined_score_rent"] == 0.79
        assert mapped["stat_score_rent"] == 0.82
        assert mapped["ai_features"] == ["balcony"]
        assert mapped["condition_score"] == 0.75
        assert mapped["sentiment_score"] == 0.78
        assert len(mapped["listings"]) == 2

    def test_list_item_projects_neighbourhood_quality(self):
        mapped = map_property_list_item(
            self._row(
                amenity_score=0.8,
                transit_score=0.4,
                access_score=None,
                safety_score=None,
                risk_flags=["flood"],
                quality_meta={"source": "curated"},
                quality_notes="note",
            )
        )
        nq = mapped["neighbourhood_quality"]
        assert nq is not None
        assert nq["amenity_score"] == pytest.approx(0.8)
        assert nq["transit_score"] == pytest.approx(0.4)
        assert nq["neighbourhood_score"] == pytest.approx(0.6)
        assert nq["risk_flags"] == ["flood"]
        assert nq["quality_meta"]["source"] == "curated"

    def test_list_item_omits_quality_without_neighborhood_id(self):
        mapped = map_property_list_item(self._row(neighborhood_id=None))
        assert mapped["neighbourhood_quality"] is None

    def test_list_item_validates_against_property_model_with_float_scores(self):
        """Regression: AI scores are floats — PropertyModel must accept them (BIN-56)."""
        from api.schemas import PropertyModel

        mapped = map_property_list_item(
            self._row(amenity_score=0.9, transit_score=0.7, access_score=0.5, safety_score=0.3)
        )
        model = PropertyModel.model_validate(mapped)
        assert model.condition_score == 0.75
        assert model.sentiment_score == 0.78
        assert model.neighbourhood_quality is not None
        assert model.neighbourhood_quality.neighbourhood_score == pytest.approx(0.6)

    def test_detail_includes_primary_and_neighborhood_id(self):
        mapped = map_property_detail(self._row(amenity_score=0.5, safety_score=0.5))
        assert mapped["neighborhood_id"] == "nbr-9"
        assert mapped["primary_listing"]["listing_type"] == "rent"
        assert mapped["price"] == 2800.0
        assert "stat_analysis" in mapped
        assert "ai_analysis" in mapped
        assert mapped["neighbourhood_quality"]["neighbourhood_score"] == pytest.approx(0.5)

    def test_no_listings_keeps_row_price(self):
        mapped = map_property_list_item(self._row(listings=[]))
        assert mapped["primary_listing"] is None
        assert mapped["price"] == 5000.0


# ---------------------------------------------------------------------------
# Story 1.2 (v0.14) — cost in the canonical projection (FR-31, AD-12, AD-19)
# ---------------------------------------------------------------------------

_COST_KEYS = {
    "rent_monthly",
    "rent_state",
    "condo_fee_monthly",
    "condo_fee_state",
    "iptu_monthly",
    "iptu_state",
    "iptu_periodicity_source",
    "fees_bundled",
    "total_monthly_cost",
    "total_state",
    "cost_complete",
}


def _cost_listing(listing_id="l-1", **overrides):
    """A listing row as ``LISTINGS_JSON_AGG`` emits it (flat persisted columns)."""
    base = _listing(
        id=listing_id,
        rent_monthly=None,
        condo_fee_monthly=None,
        iptu_monthly=None,
        iptu_periodicity_source="unknown",
        cost_fees_bundled=False,
        total_monthly_cost=None,
        cost_complete=False,
    )
    base.update(overrides)
    return base


class TestListingsSubqueryCostColumns:
    def test_reads_the_persisted_cost_columns_and_the_listing_id(self):
        for fragment in (
            "'id', pl.id",
            "'rent_monthly', pl.rent_monthly",
            "'condo_fee_monthly', pl.condo_fee_monthly",
            "'iptu_monthly', pl.iptu_monthly",
            "'iptu_periodicity_source', pl.iptu_periodicity_source",
            "'cost_fees_bundled', pl.fees_bundled",
            "'total_monthly_cost', pl.total_monthly_cost",
            "'cost_complete', pl.cost_complete",
        ):
            assert fragment in LISTINGS_JSON_AGG, fragment

    def test_legacy_fees_bundled_key_still_reads_raw_json(self):
        assert (
            "'fees_bundled', (pl.raw_json->>'fees_bundled')::boolean"
            in LISTINGS_JSON_AGG
        )


class TestListingCostView:
    def test_itemized_rent_listing(self):
        cost = listing_cost_view(
            _cost_listing(
                rent_monthly=750.0,
                condo_fee_monthly=120.0,
                iptu_monthly=59.0,
                iptu_periodicity_source="monthly",
                total_monthly_cost=929.0,
                cost_complete=True,
            )
        )
        assert cost == {
            "rent_monthly": 750.0,
            "rent_state": "known",
            "condo_fee_monthly": 120.0,
            "condo_fee_state": "known",
            "iptu_monthly": 59.0,
            "iptu_state": "known",
            "iptu_periodicity_source": "monthly",
            "fees_bundled": False,
            "total_monthly_cost": 929.0,
            "total_state": "complete",
            "cost_complete": True,
        }

    def test_bundled_rent_listing(self):
        cost = listing_cost_view(
            _cost_listing(
                rent_monthly=800.0,
                condo_fee_monthly=57.0,
                cost_fees_bundled=True,
                total_monthly_cost=857.0,
                cost_complete=True,
            )
        )
        assert cost["condo_fee_state"] == "bundled"
        assert cost["iptu_state"] == "bundled"
        assert cost["condo_fee_monthly"] == 57.0
        assert cost["iptu_monthly"] is None
        assert cost["fees_bundled"] is True
        assert cost["total_monthly_cost"] == 857.0
        assert cost["total_state"] == "bundled"

    def test_incomplete_rent_listing(self):
        cost = listing_cost_view(
            _cost_listing(rent_monthly=3500.0, condo_fee_monthly=650.0)
        )
        assert cost["rent_state"] == "known"
        assert cost["condo_fee_state"] == "known"
        assert cost["iptu_state"] == "unknown"
        assert cost["iptu_monthly"] is None
        assert cost["total_monthly_cost"] is None
        assert cost["total_state"] == "incomplete"
        assert cost["cost_complete"] is False

    def test_bundled_but_rent_unknown(self):
        cost = listing_cost_view(
            _cost_listing(condo_fee_monthly=57.0, cost_fees_bundled=True)
        )
        assert cost["rent_state"] == "unknown"
        assert cost["condo_fee_state"] == "bundled"
        assert cost["iptu_state"] == "bundled"
        assert cost["total_state"] == "incomplete"

    def test_sale_listing(self):
        cost = listing_cost_view(
            _cost_listing(
                listing_type="sale",
                price=450000.0,
                condo_fee_monthly=600.0,
                iptu_monthly=154.75,
                iptu_periodicity_source="annual",
            )
        )
        assert cost["rent_state"] == "not-applicable"
        assert cost["total_state"] == "not-applicable"
        assert cost["condo_fee_state"] == "known"
        assert cost["iptu_state"] == "known"
        assert cost["iptu_monthly"] == 154.75
        assert cost["iptu_periodicity_source"] == "annual"
        assert cost["total_monthly_cost"] is None

    def test_row_without_cost_keys_reads_as_unknown(self):
        rent = listing_cost_view(_listing())
        assert set(rent) == _COST_KEYS
        assert rent["rent_state"] == "unknown"
        assert rent["condo_fee_state"] == "unknown"
        assert rent["iptu_state"] == "unknown"
        assert rent["total_state"] == "incomplete"
        assert rent["fees_bundled"] is False
        assert rent["cost_complete"] is False
        assert rent["iptu_periodicity_source"] == "unknown"

        sale = listing_cost_view(_listing(listing_type="sale"))
        assert sale["rent_state"] == "not-applicable"
        assert sale["total_state"] == "not-applicable"

    def test_a_null_component_is_never_zero_and_legacy_fields_are_not_read(self):
        """No fallback to ``price`` / ``condo_fee`` / ``iptu`` / ``base_price``."""
        cost = listing_cost_view(
            _listing(price=4150.0, condo_fee=650.0, iptu=0.0, base_price=3500.0)
        )
        assert cost["rent_monthly"] is None
        assert cost["condo_fee_monthly"] is None
        assert cost["iptu_monthly"] is None
        assert cost["total_monthly_cost"] is None

    def test_figures_are_copied_as_stored_without_arithmetic(self):
        """A stored total that disagrees with its components is emitted as is."""
        cost = listing_cost_view(
            _cost_listing(
                rent_monthly=1000.0,
                condo_fee_monthly=100.0,
                iptu_monthly=10.0,
                total_monthly_cost=5591.67,
                cost_complete=True,
            )
        )
        assert cost["total_monthly_cost"] == 5591.67


class TestProjectListing:
    def test_nests_cost_and_keeps_the_legacy_keys(self):
        projected = project_listing(
            _cost_listing(
                listing_id="abc",
                rent_monthly=750.0,
                cost_fees_bundled=True,
                fees_bundled=False,
                base_price=700.0,
            )
        )
        assert projected["id"] == "abc"
        assert projected["cost"]["fees_bundled"] is True
        # Legacy key keeps its raw_json meaning; the column lives under ``cost``.
        assert projected["fees_bundled"] is False
        assert projected["condo_fee"] == 500.0
        assert projected["iptu"] == 100.0
        assert projected["base_price"] == 700.0
        assert projected["price"] == 3000.0
        for flat in (
            "rent_monthly",
            "cost_fees_bundled",
            "total_monthly_cost",
            "cost_complete",
        ):
            assert flat not in projected

    def test_id_is_stringified_and_null_when_absent(self):
        import uuid

        lid = uuid.uuid4()
        assert project_listing(_cost_listing(listing_id=lid))["id"] == str(lid)
        assert project_listing(_listing())["id"] is None

    def test_does_not_mutate_the_input_row(self):
        raw = _cost_listing(rent_monthly=750.0)
        before = dict(raw)
        project_listing(raw)
        assert raw == before


def _projected(*listings):
    return [project_listing(listing) for listing in listings]


class TestSelectDecidingListing:
    def _decide(self, listings):
        return select_deciding_listing(listings, select_primary_listing(listings))

    def test_two_complete_totals_lowest_total_wins(self):
        listings = _projected(
            _cost_listing("A", platform="qa", price=3000.0, total_monthly_cost=4200.0),
            _cost_listing("B", platform="zap", price=3400.0, total_monthly_cost=3900.0),
        )
        assert self._decide(listings) == ("B", "lowest-complete-total", 3900.0)
        assert select_primary_listing(listings)["id"] == "A"

    def test_complete_beats_cheaper_incomplete(self):
        listings = _projected(
            _cost_listing("A", platform="olx", price=2500.0),
            _cost_listing("B", platform="zap", price=3000.0, total_monthly_cost=3900.0),
        )
        assert self._decide(listings) == ("B", "lowest-complete-total", 3900.0)

    def test_no_complete_total_falls_back_to_the_primary_listing(self):
        listings = _projected(
            _cost_listing("A", platform="olx", price=2500.0),
            _cost_listing("B", platform="zap", price=3000.0),
        )
        assert self._decide(listings) == ("A", "lowest-headline-price", None)

    def test_sale_only_property(self):
        listings = _projected(
            _cost_listing("S", listing_type="sale", price=450000.0),
        )
        assert self._decide(listings) == ("S", "lowest-headline-price", None)

    def test_a_sale_listing_never_decides_by_total(self):
        """A total on a sale row would be corrupt data; it must not win."""
        listings = _projected(
            _cost_listing("S", listing_type="sale", price=100.0, total_monthly_cost=1.0),
            _cost_listing("R", price=3000.0, total_monthly_cost=3900.0),
        )
        assert self._decide(listings) == ("R", "lowest-complete-total", 3900.0)

    def test_no_priced_listing(self):
        assert self._decide([]) == (None, None, None)
        assert select_deciding_listing(None, None) == (None, None, None)

    def test_tie_breaks_on_platform_then_id(self):
        listings = _projected(
            _cost_listing("2", platform="zap", total_monthly_cost=3900.0),
            _cost_listing("9", platform="olx", total_monthly_cost=3900.0),
            _cost_listing("1", platform="olx", total_monthly_cost=3900.0),
        )
        assert self._decide(listings)[0] == "1"

    def test_choice_is_independent_of_listing_order(self):
        import itertools

        rows = [
            _cost_listing("1", platform="olx", price=2500.0),
            _cost_listing("2", platform="zap", price=3400.0, total_monthly_cost=3900.0),
            _cost_listing("3", platform="olx", price=3000.0, total_monthly_cost=3900.0),
            _cost_listing("4", platform="qa", price=3100.0, total_monthly_cost=4200.0),
            _cost_listing("5", listing_type="sale", price=1.0),
        ]
        results = {
            self._decide(_projected(*perm)) for perm in itertools.permutations(rows)
        }
        assert results == {("3", "lowest-complete-total", 3900.0)}


class TestMapPropertyCostProjection:
    def _row(self, **overrides):
        base = TestMapPropertyProjection()._row(
            listings=[
                _cost_listing(
                    "A",
                    platform="qa",
                    price=3000.0,
                    rent_monthly=3000.0,
                    condo_fee_monthly=900.0,
                    iptu_monthly=300.0,
                    iptu_periodicity_source="monthly",
                    total_monthly_cost=4200.0,
                    cost_complete=True,
                ),
                _cost_listing(
                    "B",
                    platform="zap",
                    price=3400.0,
                    rent_monthly=3400.0,
                    condo_fee_monthly=500.0,
                    cost_fees_bundled=True,
                    total_monthly_cost=3900.0,
                    cost_complete=True,
                ),
                _cost_listing("S", platform="zap", listing_type="sale", price=450000.0),
            ]
        )
        base.update(overrides)
        return base

    @pytest.mark.parametrize("mapper", [map_property_list_item, map_property_detail])
    def test_both_mappers_carry_the_property_cost_fields(self, mapper):
        mapped = mapper(self._row())
        assert mapped["deciding_listing_id"] == "B"
        assert mapped["deciding_rule"] == "lowest-complete-total"
        assert mapped["total_monthly_cost"] == 3900.0
        # Legacy fields keep their meaning: headline-lowest primary, its price.
        assert mapped["primary_listing"]["id"] == "A"
        assert mapped["price"] == 3000.0
        assert mapped["deciding_listing_id"] in {x["id"] for x in mapped["listings"]}
        for listing in mapped["listings"]:
            assert set(listing["cost"]) == _COST_KEYS
        assert mapped["primary_listing"]["cost"]["total_state"] == "complete"

    @pytest.mark.parametrize("mapper", [map_property_list_item, map_property_detail])
    def test_no_total_falls_back_to_the_primary_listing(self, mapper):
        mapped = mapper(
            self._row(
                listings=[
                    _cost_listing("A", platform="olx", price=2500.0),
                    _cost_listing("S", listing_type="sale", price=450000.0),
                ]
            )
        )
        assert mapped["deciding_listing_id"] == "A" == mapped["primary_listing"]["id"]
        assert mapped["deciding_rule"] == "lowest-headline-price"
        assert mapped["total_monthly_cost"] is None

    @pytest.mark.parametrize("mapper", [map_property_list_item, map_property_detail])
    def test_no_listings_leaves_all_three_null(self, mapper):
        mapped = mapper(self._row(listings=[]))
        assert mapped["primary_listing"] is None
        assert mapped["deciding_listing_id"] is None
        assert mapped["deciding_rule"] is None
        assert mapped["total_monthly_cost"] is None

    def test_rows_without_cost_keys_still_project(self):
        """Older fake rows / digest fixtures: no exception, everything unknown."""
        mapped = map_property_list_item(TestMapPropertyProjection()._row())
        assert mapped["deciding_rule"] == "lowest-headline-price"
        assert mapped["total_monthly_cost"] is None
        assert {x["cost"]["total_state"] for x in mapped["listings"]} == {
            "incomplete",
            "not-applicable",
        }

    def test_no_cost_figure_differs_from_the_stored_column(self):
        row = self._row()
        stored = {x["id"]: x for x in row["listings"]}
        mapped = map_property_list_item(row)
        for listing in mapped["listings"]:
            source = stored[listing["id"]]
            for column in (
                "rent_monthly",
                "condo_fee_monthly",
                "iptu_monthly",
                "total_monthly_cost",
            ):
                assert listing["cost"][column] == source[column]
            assert listing["cost"]["fees_bundled"] == source["cost_fees_bundled"]
            assert listing["cost"]["cost_complete"] == source["cost_complete"]

    def test_list_item_validates_against_property_model(self):
        from api.schemas import PropertyModel

        model = PropertyModel.model_validate(map_property_list_item(self._row()))
        assert model.deciding_listing_id == "B"
        assert model.deciding_rule == "lowest-complete-total"
        assert model.total_monthly_cost == 3900.0
        by_id = {x.id: x for x in model.listings}
        assert by_id["B"].cost.total_state == "bundled"
        assert by_id["B"].cost.iptu_state == "bundled"
        assert by_id["A"].cost.total_state == "complete"
        assert by_id["S"].cost.rent_state == "not-applicable"
        dumped = model.model_dump()
        assert dumped["listings"][0]["cost"]["rent_monthly"] == 3000.0

    def test_detail_validates_against_property_detail_model(self):
        from api.schemas import PropertyDetailModel

        model = PropertyDetailModel.model_validate(map_property_detail(self._row()))
        assert model.deciding_listing_id == "B"
        assert model.deciding_rule == "lowest-complete-total"
        assert model.total_monthly_cost == 3900.0
        assert model.primary_listing.id == "A"
        assert model.primary_listing.cost.total_monthly_cost == 4200.0

    def test_models_reject_a_state_outside_the_vocabulary(self):
        from pydantic import ValidationError

        from api.schemas import PropertyModel

        mapped = map_property_list_item(self._row())
        mapped["listings"][0]["cost"]["total_state"] = "estimated"
        with pytest.raises(ValidationError):
            PropertyModel.model_validate(mapped)

        mapped = map_property_list_item(self._row())
        mapped["deciding_rule"] = "cheapest"
        with pytest.raises(ValidationError):
            PropertyModel.model_validate(mapped)
