"""Integration: GET /properties must serialize AI float scores without 500 (BIN-56)."""

from __future__ import annotations

import json
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("DATABASE_URL"),
        reason="DATABASE_URL not set",
    ),
]


def _db_ready() -> bool:
    try:
        from infra.db import SessionLocal

        with SessionLocal() as session:
            session.execute(text("SELECT 1 FROM properties LIMIT 0"))
            return True
    except Exception:
        return False


@pytest.fixture
def client():
    if not _db_ready():
        pytest.skip("Postgres properties table not available")
    from api.main import app

    # Raise so ResponseValidationError fails the test instead of becoming a soft 500.
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def seeded_ai_enriched_property():
    """Property + metrics_scoring with fractional condition/sentiment scores."""
    if not _db_ready():
        pytest.skip("Postgres properties table not available")

    from infra.db import SessionLocal

    prop_id = str(uuid.uuid4())
    meta = {
        "visual": {
            "condition_score": 0.75,
            "category": "Average",
            "reasoning": "ok",
            "features_detected": ["balcony"],
            "issues_detected": [],
        },
        "sentiment": {
            "sentiment_score": 0.78,
            "category": "Average",
            "reasoning": "fine",
            "green_flags": ["light"],
            "red_flags": [],
        },
        "stat_analysis": {"category": "deal", "reasoning": "cheap"},
        "deal_verdict": {"verdict": "Worth a look"},
    }

    with SessionLocal() as session:
        session.execute(
            text(
                """
                INSERT INTO properties (
                    id, platform, platform_id, title, description, price, active
                )
                VALUES (
                    CAST(:id AS uuid), 'test', :pid, 'BIN-56 float scores',
                    'apartamento teste', 2500, true
                )
                """
            ),
            {"id": prop_id, "pid": f"bin56-{prop_id[:8]}"},
        )
        session.execute(
            text(
                """
                INSERT INTO metrics_scoring (
                    property_id, stat_score, ai_score, combined_score, meta
                )
                VALUES (
                    CAST(:id AS uuid), 0.5, 0.6, 0.55, CAST(:meta AS jsonb)
                )
                """
            ),
            {"id": prop_id, "meta": json.dumps(meta)},
        )
        session.commit()

    yield prop_id

    with SessionLocal() as session:
        session.execute(
            text("DELETE FROM metrics_scoring WHERE property_id = CAST(:id AS uuid)"),
            {"id": prop_id},
        )
        session.execute(
            text("DELETE FROM properties WHERE id = CAST(:id AS uuid)"),
            {"id": prop_id},
        )
        session.commit()


def test_list_properties_accepts_float_ai_scores(client, seeded_ai_enriched_property):
    """Enriched rows must not trigger ResponseValidationError on the list endpoint."""
    prop_id = seeded_ai_enriched_property
    response = client.get("/properties?page=1&page_size=100&platform=test")
    assert response.status_code == 200, response.text
    data = response.json()
    match = next((p for p in data["properties"] if p["id"] == prop_id), None)
    assert match is not None, "seeded property missing from list"
    assert match["condition_score"] == pytest.approx(0.75)
    assert match["sentiment_score"] == pytest.approx(0.78)


def test_export_json_accepts_float_ai_scores(client, seeded_ai_enriched_property):
    prop_id = seeded_ai_enriched_property
    api_key = os.environ.get("API_KEY", "")
    headers = {"X-API-Key": api_key} if api_key else {}
    response = client.get(
        "/properties/export?format=json&platform=test",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    match = next((p for p in data["properties"] if p["id"] == prop_id), None)
    assert match is not None
    assert match["condition_score"] == pytest.approx(0.75)
    assert match["sentiment_score"] == pytest.approx(0.78)
