"""Unit tests for AD-12 canonical property projection."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.property_projection import (
    LISTINGS_JSON_AGG,
    decisioning_price,
    map_property_detail,
    map_property_list_item,
    neighborhood_fields,
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
