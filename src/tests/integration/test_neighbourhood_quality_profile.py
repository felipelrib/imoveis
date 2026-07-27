"""Integration: neighbourhood quality profile columns round-trip via API (BIN-86)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from api.main import app


@pytest.fixture(scope="function")
def db_session(wipe_safe_db_session):
    yield wipe_safe_db_session


@pytest.mark.integration
class TestNeighbourhoodQualityProfileApi:
    def test_detail_returns_stored_profile(self, db_session):
        row = db_session.execute(
            text(
                """
                INSERT INTO neighborhoods (
                    name, city, state,
                    amenity_score, transit_score, access_score, safety_score,
                    risk_flags, quality_meta, quality_notes
                )
                VALUES (
                    'QualityFixture', 'Belo Horizonte', 'MG',
                    0.8, 0.55, NULL, 0.7,
                    ARRAY['flood']::text[],
                    CAST(:meta AS jsonb),
                    'curated mvp'
                )
                RETURNING id::text
                """
            ),
            {"meta": '{"provider": "curated-yaml", "refreshed_at": "2026-07-27"}'},
        ).fetchone()
        db_session.commit()
        nid = row[0]

        client = TestClient(app)
        response = client.get(f"/properties/neighborhoods/{nid}")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["name"] == "QualityFixture"
        assert data["id"] == nid
        assert data["count"] == 0
        assert data["amenity_score"] == pytest.approx(0.8)
        assert data["transit_score"] == pytest.approx(0.55)
        assert data["access_score"] is None
        assert data["safety_score"] == pytest.approx(0.7)
        assert data["risk_flags"] == ["flood"]
        assert data["quality_meta"]["provider"] == "curated-yaml"
        assert data["quality_notes"] == "curated mvp"
