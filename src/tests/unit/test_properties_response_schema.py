"""Unit tests locking GET /properties response validation against AI score types.

BIN-56: ``condition_score`` / ``sentiment_score`` are floats in [0.0, 1.0].
Declaring them as ``int`` in ``PropertyModel`` caused ResponseValidationError → 500
whenever enriched properties were listed. These tests must fail if the schema
drifts away from the AI domain again — without needing a live database.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.main import app
from api.properties import (
    PropertyExportFilters,
    PropertyListFilters,
    _build_list_filters,
    _export_filters_as_list_filters,
)
from api.schemas import PaginatedPropertiesResponse, PropertyModel
from core.property_projection import map_property_list_item


def _ai_enriched_row(**overrides):
    """DB-shaped row matching LIST_SELECT_COLUMNS + float AI meta (production shape)."""
    base = {
        "id": uuid4(),
        "platform": "quintoandar",
        "platform_id": "qa-1",
        "title": "Apt Savassi",
        "price": 3500.0,
        "area_m2": 70.0,
        "bedrooms": 2,
        "bathrooms": 1,
        "address": "Rua A",
        "image_urls": [],
        "first_seen": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "lat": -19.9,
        "lon": -43.9,
        "stat_score": 0.5,
        "ai_score": 0.6,
        "combined_score": 0.7,
        "percentile_rank": 0.8,
        "z_score": -0.2,
        "price_per_m2": 50.0,
        "neighborhood_mean": 55.0,
        "neighborhood_id": uuid4(),
        "neighborhood_name": "Savassi",
        "parking": 1,
        "description": "Nice",
        "props_json": {"available_for_rent": True, "available_for_sale": False},
        "meta": {
            "visual": {
                "features_detected": ["balcony"],
                "issues_detected": [],
                "condition_score": 0.75,
                "category": "Average",
                "reasoning": "ok",
            },
            "sentiment": {
                "green_flags": ["light"],
                "red_flags": [],
                "sentiment_score": 0.78,
                "category": "Average",
                "reasoning": "fine",
            },
            "stat_analysis": {"category": "deal", "reasoning": "cheap"},
            "deal_verdict": {"verdict": "Worth a look"},
        },
        "listings": [
            {
                "platform": "quintoandar",
                "platform_listing_id": "1",
                "listing_type": "rent",
                "price": 3500.0,
                "currency": "BRL",
                "url": "https://example.com/1",
                "is_furnished": False,
                "accepts_pets": True,
                "condo_fee": 500.0,
                "iptu": 100.0,
            }
        ],
    }
    base.update(overrides)
    return base


@pytest.mark.unit
class TestPropertyModelAiScoreTypes:
    def test_property_model_accepts_fractional_ai_scores(self):
        mapped = map_property_list_item(_ai_enriched_row())
        model = PropertyModel.model_validate(mapped)
        assert model.condition_score == pytest.approx(0.75)
        assert model.sentiment_score == pytest.approx(0.78)

    def test_paginated_response_accepts_fractional_ai_scores(self):
        mapped = map_property_list_item(_ai_enriched_row())
        envelope = PaginatedPropertiesResponse.model_validate(
            {
                "total": 1,
                "page": 1,
                "page_size": 24,
                "pages": 1,
                "properties": [mapped],
            }
        )
        assert envelope.properties[0].condition_score == pytest.approx(0.75)

    def test_property_model_rejects_non_numeric_scores(self):
        mapped = map_property_list_item(_ai_enriched_row())
        mapped["condition_score"] = "good"
        with pytest.raises(ValidationError):
            PropertyModel.model_validate(mapped)

    @pytest.mark.parametrize("field_name,bad_value", [
        ("condition_score", 1.5),
        ("condition_score", -0.1),
        ("sentiment_score", 85.0),
        ("sentiment_score", -1.0),
        ("ai_score", 2.0),
    ])
    def test_property_model_rejects_out_of_range_scores(self, field_name, bad_value):
        """BIN-148: response-side safety net — an out-of-range AI score reaching
        the API layer (e.g. via a bug upstream of the client.py clamp) must fail
        loudly rather than serialize a corrupted deal-ranking value."""
        mapped = map_property_list_item(_ai_enriched_row())
        mapped[field_name] = bad_value
        with pytest.raises(ValidationError):
            PropertyModel.model_validate(mapped)


@pytest.mark.unit
class TestListPropertiesEndpointSchema:
    """Hit the real FastAPI route with mocked DB so response_model validation runs."""

    def test_list_properties_200_with_float_ai_scores(self):
        row = _ai_enriched_row()
        session = MagicMock()
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        session.execute.side_effect = [
            SimpleNamespace(scalar=lambda: 1),
            SimpleNamespace(mappings=lambda: SimpleNamespace(fetchall=lambda: [row])),
        ]

        def _bypass_rate_limit(self, request, endpoint, *args, **kwargs):
            request.state.view_rate_limit = []

        # Unit CI has no Redis; bypass slowapi storage while still running
        # FastAPI response_model validation on the real route.
        with (
            patch("api.properties.SessionLocal", return_value=session),
            patch(
                "slowapi.extension.Limiter._check_request_limit",
                _bypass_rate_limit,
            ),
        ):
            client = TestClient(app, raise_server_exceptions=True)
            response = client.get("/properties?page=1&page_size=1")

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["total"] == 1
        prop = data["properties"][0]
        assert prop["condition_score"] == pytest.approx(0.75)
        assert prop["sentiment_score"] == pytest.approx(0.78)
        assert "primary_listing" in prop
        assert "listings" in prop
        # v0.14-s1.2: cost fields survive response_model validation (a field
        # missing from the model would be silently dropped).
        assert prop["deciding_rule"] == "lowest-headline-price"
        assert prop["total_monthly_cost"] is None
        assert "deciding_listing_id" in prop
        assert prop["listings"][0]["cost"]["total_state"] == "incomplete"
        assert "id" in prop["listings"][0]

    def test_list_properties_emits_persisted_cost_through_the_route(self):
        listing = dict(_ai_enriched_row()["listings"][0])
        listing.update(
            id=str(uuid4()),
            rent_monthly=3500.0,
            condo_fee_monthly=500.0,
            iptu_monthly=100.0,
            iptu_periodicity_source="monthly",
            cost_fees_bundled=False,
            total_monthly_cost=4100.0,
            cost_complete=True,
        )
        row = _ai_enriched_row(listings=[listing])
        session = MagicMock()
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        session.execute.side_effect = [
            SimpleNamespace(scalar=lambda: 1),
            SimpleNamespace(mappings=lambda: SimpleNamespace(fetchall=lambda: [row])),
        ]

        def _bypass_rate_limit(self, request, endpoint, *args, **kwargs):
            request.state.view_rate_limit = []

        with (
            patch("api.properties.SessionLocal", return_value=session),
            patch(
                "slowapi.extension.Limiter._check_request_limit",
                _bypass_rate_limit,
            ),
        ):
            client = TestClient(app, raise_server_exceptions=True)
            response = client.get(
                "/properties?page=1&page_size=1&sort_by=total_monthly_cost"
                "&sort_dir=asc&max_total_monthly_cost=4500"
                "&include_incomplete_totals=true"
            )
            invalid_sort = client.get("/properties?sort_by=total")
            negative_cap = client.get("/properties?max_total_monthly_cost=-1")

        assert response.status_code == 200, response.text
        prop = response.json()["properties"][0]
        assert prop["deciding_listing_id"] == listing["id"]
        assert prop["deciding_rule"] == "lowest-complete-total"
        assert prop["total_monthly_cost"] == pytest.approx(4100.0)
        cost = prop["listings"][0]["cost"]
        assert cost == {
            "rent_monthly": 3500.0,
            "rent_state": "known",
            "condo_fee_monthly": 500.0,
            "condo_fee_state": "known",
            "iptu_monthly": 100.0,
            "iptu_state": "known",
            "iptu_periodicity_source": "monthly",
            "fees_bundled": False,
            "total_monthly_cost": 4100.0,
            "total_state": "complete",
            "cost_complete": True,
        }
        assert invalid_sort.status_code == 422
        assert negative_cap.status_code == 422


def _cost_columns_in(sql: str) -> set[str]:
    return {
        column
        for column in (
            "rent_monthly",
            "condo_fee_monthly",
            "iptu_monthly",
            "iptu_periodicity_source",
            "fees_bundled",
            "cost_complete",
            "total_monthly_cost",
            "condo_fee",
            "iptu",
            "base_price",
        )
        if re.search(r"\bpl\." + column + r"\b", sql)
    }


@pytest.mark.unit
class TestTotalMonthlyCostFilterBuilder:
    """v0.14-s1.2: the sort and the cap read ``total_monthly_cost`` only."""

    def test_sort_orders_by_lowest_active_rent_total_nulls_last(self):
        for direction in ("asc", "desc"):
            _where, params, order = _build_list_filters(
                PropertyListFilters(sort_by="total_monthly_cost", sort_dir=direction),
                None,
            )
            assert "MIN(pl.total_monthly_cost)" in order
            assert "pl.active = true" in order
            assert "pl.listing_type = 'rent'" in order
            assert "pl.total_monthly_cost IS NOT NULL" in order
            assert order.endswith(f"{direction.upper()} NULLS LAST, p.id")
            assert _cost_columns_in(order) == {"total_monthly_cost"}
            assert "sort_price_type" not in params

    def test_cap_keeps_properties_with_a_total_at_or_under_it(self):
        where, params, _order = _build_list_filters(
            PropertyListFilters(max_total_monthly_cost=4000), None
        )
        assert params["max_total_monthly_cost"] == 4000
        assert "pl.total_monthly_cost <= :max_total_monthly_cost" in where
        assert "4000" not in where  # bound, never spliced (BIN-135)
        assert "NOT EXISTS" not in where
        assert _cost_columns_in(where) == {"total_monthly_cost"}

    def test_cap_with_incomplete_requested_adds_the_no_total_branch(self):
        where, params, _order = _build_list_filters(
            PropertyListFilters(
                max_total_monthly_cost=4000, include_incomplete_totals=True
            ),
            None,
        )
        assert params["max_total_monthly_cost"] == 4000
        assert "pl.total_monthly_cost <= :max_total_monthly_cost" in where
        assert " OR " in where
        assert "NOT EXISTS" in where
        assert _cost_columns_in(where) == {"total_monthly_cost"}

    def test_flag_without_a_cap_has_no_filtering_effect(self):
        plain = _build_list_filters(PropertyListFilters(), None)
        flagged = _build_list_filters(
            PropertyListFilters(include_incomplete_totals=True), None
        )
        assert flagged == plain

    def test_cap_does_not_disturb_max_price(self):
        where, params, _order = _build_list_filters(
            PropertyListFilters(max_price=3000, max_total_monthly_cost=4000), None
        )
        assert params["max_price"] == 3000
        assert params["price_type"] == "rent"
        assert "pl.price <= :max_price" in where

    def test_invalid_sort_key_and_negative_cap_are_rejected(self):
        with pytest.raises(ValidationError):
            PropertyListFilters(sort_by="total")
        with pytest.raises(ValidationError):
            PropertyListFilters(max_total_monthly_cost=-1)
        with pytest.raises(ValidationError):
            PropertyExportFilters(sort_by="total")

    def test_export_filters_carry_the_same_params(self):
        list_filters = _export_filters_as_list_filters(
            PropertyExportFilters(
                sort_by="total_monthly_cost",
                sort_dir="asc",
                max_total_monthly_cost=4000,
                include_incomplete_totals=True,
            )
        )
        assert list_filters.max_total_monthly_cost == 4000
        assert list_filters.include_incomplete_totals is True
        where, params, order = _build_list_filters(list_filters, None)
        assert params["max_total_monthly_cost"] == 4000
        assert "NOT EXISTS" in where
        assert order.endswith("ASC NULLS LAST, p.id")


@pytest.mark.unit
class TestPricePercentileThroughTheRoute:
    """v0.14-s1.7: the stored percentiles survive response_model validation."""

    @staticmethod
    def _get(path: str, row: dict):
        session = MagicMock()
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        session.execute.side_effect = [
            SimpleNamespace(scalar=lambda: 1),
            SimpleNamespace(mappings=lambda: SimpleNamespace(fetchall=lambda: [row])),
        ]

        def _bypass_rate_limit(self, request, endpoint, *args, **kwargs):
            request.state.view_rate_limit = []

        with (
            patch("api.properties.SessionLocal", return_value=session),
            patch("slowapi.extension.Limiter._check_request_limit", _bypass_rate_limit),
        ):
            client = TestClient(app, raise_server_exceptions=True)
            return client.get(path), session

    def test_list_item_carries_the_unrounded_value_and_null(self):
        row = _ai_enriched_row(
            price_per_m2_percentile_rent=501 / 2000,
            price_per_m2_percentile_sale=None,
        )
        response, session = self._get(
            "/properties?page=1&page_size=1&listing_type=rent"
            "&max_price_per_m2_percentile=0.5",
            row,
        )
        assert response.status_code == 200, response.text
        prop = response.json()["properties"][0]
        assert prop["price_per_m2_percentile_rent"] == 501 / 2000
        assert prop["price_per_m2_percentile_sale"] is None
        # The legacy field is still served.
        assert prop["percentile_rank"] == pytest.approx(0.8)
        # The value reached the query as a bound parameter.
        count_sql, count_params = session.execute.call_args_list[0].args
        assert count_params["max_price_per_m2_percentile"] == 0.5
        assert "<= 0.5" not in str(count_sql)
        assert (
            "ms.price_per_m2_percentile_rent <= :max_price_per_m2_percentile"
            in str(count_sql)
        )

    def test_a_row_without_the_columns_reads_null(self):
        response, _session = self._get("/properties?page=1&page_size=1", _ai_enriched_row())
        assert response.status_code == 200, response.text
        prop = response.json()["properties"][0]
        assert prop["price_per_m2_percentile_rent"] is None
        assert prop["price_per_m2_percentile_sale"] is None

    @pytest.mark.parametrize("value", ["0", "1.5", "abc", "-0.25"])
    def test_out_of_range_is_a_422(self, value):
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get(f"/properties?max_price_per_m2_percentile={value}")
        assert response.status_code == 422
