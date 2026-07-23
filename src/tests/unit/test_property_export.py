"""Unit tests for AD-12 property export serializers (BIN-50)."""

from __future__ import annotations

import csv
import io
import json

import pytest

from api.property_export import (
    CSV_COLUMNS,
    properties_to_csv,
    properties_to_export_json,
)


def _sample_item(**overrides):
    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "platform": "zap",
        "platform_id": "abc",
        "title": "Apt Savassi",
        "price": 3500.0,
        "area_m2": 80.0,
        "bedrooms": 2,
        "bathrooms": 1,
        "parking": 1,
        "address": "Rua X",
        "image_urls": ["https://example.com/a.jpg"],
        "created_at": "2026-01-01T00:00:00",
        "lat": -19.9,
        "lon": -43.9,
        "stat_score": 0.8,
        "ai_score": 0.7,
        "combined_score": 0.75,
        "percentile_rank": 0.9,
        "z_score": -1.2,
        "price_per_m2": 43.75,
        "neighborhood_mean": 50.0,
        "neighborhood_id": "22222222-2222-2222-2222-222222222222",
        "neighborhood_name": "Savassi",
        "description": "Nice place",
        "available_for_rent": True,
        "available_for_sale": False,
        "ai_features": ["balcony"],
        "ai_issues": [],
        "ai_green_flags": ["light"],
        "ai_red_flags": [],
        "condition_score": 8,
        "sentiment_score": 7,
        "stat_category": "good_deal",
        "stat_reasoning": "below mean",
        "deal_summary": "Worth a look",
        "visual_category": "good",
        "visual_reasoning": "clean",
        "sentiment_category": "positive",
        "sentiment_reasoning": "ok",
        "listings": [
            {
                "platform": "zap",
                "platform_listing_id": "abc",
                "listing_type": "rent",
                "price": 3500.0,
                "currency": "BRL",
                "url": "https://example.com/l",
                "is_furnished": False,
                "accepts_pets": True,
                "condo_fee": 500.0,
                "iptu": 100.0,
            }
        ],
        "primary_listing": {
            "platform": "zap",
            "platform_listing_id": "abc",
            "listing_type": "rent",
            "price": 3500.0,
            "currency": "BRL",
            "url": "https://example.com/l",
            "is_furnished": False,
            "accepts_pets": True,
            "condo_fee": 500.0,
            "iptu": 100.0,
        },
    }
    base.update(overrides)
    return base


@pytest.mark.unit
def test_export_json_envelope_and_truncation():
    items = [_sample_item()]
    payload = properties_to_export_json(items, total=1)
    assert payload["total"] == 1
    assert payload["truncated"] is False
    assert len(payload["properties"]) == 1
    assert payload["properties"][0]["id"] == items[0]["id"]
    assert "primary_listing" in payload["properties"][0]

    truncated = properties_to_export_json(items, total=10)
    assert truncated["truncated"] is True
    assert truncated["total"] == 10


@pytest.mark.unit
def test_export_json_empty():
    payload = properties_to_export_json([], total=0)
    assert payload == {"properties": [], "total": 0, "truncated": False}


@pytest.mark.unit
def test_export_csv_empty_is_header_only():
    text = properties_to_csv([])
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    assert len(rows) == 1
    assert rows[0] == list(CSV_COLUMNS)


@pytest.mark.unit
def test_export_csv_flattens_primary_listing_and_json_lists():
    text = properties_to_csv([_sample_item()])
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "11111111-1111-1111-1111-111111111111"
    assert row["price"] == "3500.0"
    assert row["neighborhood_name"] == "Savassi"
    assert row["available_for_rent"] == "true"
    assert row["primary_listing_platform"] == "zap"
    assert row["primary_listing_listing_type"] == "rent"
    assert row["primary_listing_price"] == "3500.0"
    assert json.loads(row["listings"])[0]["platform"] == "zap"
    assert json.loads(row["image_urls"]) == ["https://example.com/a.jpg"]
    assert json.loads(row["ai_features"]) == ["balcony"]


@pytest.mark.unit
def test_export_csv_null_primary_listing_leaves_prefixed_empty():
    text = properties_to_csv([_sample_item(primary_listing=None, listings=[])])
    row = next(csv.DictReader(io.StringIO(text)))
    assert row["primary_listing_platform"] == ""
    assert row["primary_listing_price"] == ""
    assert json.loads(row["listings"]) == []
