"""Integration: listing claim stats refresh writes nested meta only (BIN-93)."""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from adapters.geo.listing_claim_refresh import refresh_listing_claim_stats
from api.main import app
from infra.config import ListingClaimStatsConfig


@pytest.fixture(scope="function")
def db_session(wipe_safe_db_session):
    yield wipe_safe_db_session


def _insert_nhood(session, *, name: str, meta: str | None = None) -> str:
    row = session.execute(
        text(
            """
            INSERT INTO neighborhoods (
                name, city, state, geometry,
                amenity_score, safety_score, quality_meta
            )
            VALUES (
                :name,
                'Belo Horizonte',
                'MG',
                ST_GeomFromText(
                    'POLYGON((-43.94 -19.94, -43.93 -19.94, -43.93 -19.93, -43.94 -19.93, -43.94 -19.94))',
                    4326
                ),
                0.77,
                0.55,
                CAST(:meta AS jsonb)
            )
            RETURNING id::text
            """
        ),
        {
            "name": name,
            "meta": meta or '{"provider": "curated-yaml", "access": {"hub_id": "x"}}',
        },
    ).fetchone()
    return row[0]


def _insert_property_with_sentiment(
    session,
    *,
    neighborhood_id: str,
    green: list[str],
    red: list[str],
) -> str:
    prop_id = str(uuid.uuid4())
    meta = {
        "sentiment": {
            "sentiment_score": 0.6,
            "green_flags": green,
            "red_flags": red,
        }
    }
    session.execute(
        text(
            """
            INSERT INTO properties (
                id, platform, platform_id, title, price, active, neighborhood_id
            )
            VALUES (
                CAST(:id AS uuid), 'test', :pid, 'claim fixture', 2000, true,
                CAST(:nid AS uuid)
            )
            """
        ),
        {
            "id": prop_id,
            "pid": f"claim-{prop_id[:8]}",
            "nid": neighborhood_id,
        },
    )
    session.execute(
        text(
            """
            INSERT INTO metrics_scoring (property_id, ai_score, meta)
            VALUES (CAST(:id AS uuid), 0.5, CAST(:meta AS jsonb))
            """
        ),
        {"id": prop_id, "meta": json.dumps(meta)},
    )
    return prop_id


@pytest.mark.integration
class TestListingClaimStatsRefresh:
    def test_aggregates_flags_without_overwriting_scores(self, db_session):
        nid = _insert_nhood(db_session, name="ClaimFixtureA")
        _insert_property_with_sentiment(
            db_session,
            neighborhood_id=nid,
            green=["Near Metro", "Park"],
            red=["Noise"],
        )
        _insert_property_with_sentiment(
            db_session,
            neighborhood_id=nid,
            green=["near metro"],
            red=[],
        )
        db_session.commit()

        cfg = ListingClaimStatsConfig(enabled=True, top_n=5, min_sample_size=1)
        stats = refresh_listing_claim_stats(
            db_session,
            cfg,
            refreshed_at="2026-07-27T15:00:00+00:00",
        )
        assert stats["updated"] == 1
        assert stats["errors"] == 0

        row = db_session.execute(
            text(
                """
                SELECT amenity_score, safety_score, quality_meta
                FROM neighborhoods
                WHERE id = CAST(:id AS uuid)
                """
            ),
            {"id": nid},
        ).mappings().one()
        assert row["amenity_score"] == pytest.approx(0.77)
        assert row["safety_score"] == pytest.approx(0.55)
        meta = row["quality_meta"]
        assert meta["provider"] == "curated-yaml"
        assert meta["access"]["hub_id"] == "x"
        claims = meta["listing_claim_stats"]
        assert claims["source"] == "listing_llm_aggregate"
        assert claims["sample_size"] == 2
        assert claims["refreshed_at"] == "2026-07-27T15:00:00+00:00"
        assert "biased" in claims["disclaimer"].casefold() or "omit" in claims[
            "disclaimer"
        ].casefold()
        assert claims["top_green_flags"][0] == {"flag": "near metro", "count": 2}
        assert {"flag": "park", "count": 1} in claims["top_green_flags"]
        assert claims["top_red_flags"] == [{"flag": "noise", "count": 1}]

        client = TestClient(app)
        response = client.get(f"/properties/neighborhoods/{nid}")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["amenity_score"] == pytest.approx(0.77)
        assert data["quality_meta"]["listing_claim_stats"]["source"] == (
            "listing_llm_aggregate"
        )

    def test_skips_below_min_sample_size(self, db_session):
        nid = _insert_nhood(db_session, name="ClaimFixtureB")
        _insert_property_with_sentiment(
            db_session,
            neighborhood_id=nid,
            green=["metro"],
            red=[],
        )
        db_session.commit()

        cfg = ListingClaimStatsConfig(enabled=True, min_sample_size=5)
        stats = refresh_listing_claim_stats(db_session, cfg)
        assert stats["processed"] == 1
        assert stats["updated"] == 0
        assert stats["skipped"] == 1

        meta = db_session.execute(
            text(
                "SELECT quality_meta FROM neighborhoods WHERE id = CAST(:id AS uuid)"
            ),
            {"id": nid},
        ).scalar_one()
        assert "listing_claim_stats" not in (meta or {})
