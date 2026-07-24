"""Unit tests locking GET /properties response validation against AI score types.

BIN-56: ``condition_score`` / ``sentiment_score`` are floats in [0.0, 1.0].
Declaring them as ``int`` in ``PropertyModel`` caused ResponseValidationError → 500
whenever enriched properties were listed. These tests must fail if the schema
drifts away from the AI domain again — without needing a live database.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.main import app
from api.property_projection import map_property_list_item
from api.schemas import PaginatedPropertiesResponse, PropertyModel


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
