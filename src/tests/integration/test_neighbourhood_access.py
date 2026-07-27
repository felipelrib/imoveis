"""Integration: neighbourhood access_score refresh writes meta (BIN-90)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from adapters.geo.access_refresh import refresh_neighbourhood_access
from adapters.geo.osrm_client import OsrmClient
from api.main import app
from infra.config import AccessHubConfig, NeighbourhoodAccessConfig


@pytest.fixture(scope="function")
def db_session(wipe_safe_db_session):
    yield wipe_safe_db_session


@pytest.mark.integration
class TestNeighbourhoodAccessRefresh:
    def test_haversine_refresh_updates_score_and_nested_meta(self, db_session):
        # Small square around Savassi-ish coords; PointOnSurface ≈ centroid.
        row = db_session.execute(
            text(
                """
                INSERT INTO neighborhoods (
                    name, city, state, geometry, quality_meta
                )
                VALUES (
                    'AccessFixture',
                    'Belo Horizonte',
                    'MG',
                    ST_GeomFromText(
                        'POLYGON((-43.94 -19.94, -43.93 -19.94, -43.93 -19.93, -43.94 -19.93, -43.94 -19.94))',
                        4326
                    ),
                    CAST(:meta AS jsonb)
                )
                RETURNING id::text
                """
            ),
            {"meta": '{"provider": "curated-yaml", "refreshed_at": "2026-07-01"}'},
        ).fetchone()
        db_session.commit()
        nid = row[0]

        cfg = NeighbourhoodAccessConfig(
            enabled=True,
            base_url="",
            mode="driving",
            max_minutes=45.0,
            avg_speed_kmh=30.0,
            hubs={
                "Belo Horizonte": [
                    AccessHubConfig(
                        id="savassi",
                        lat=-19.9386,
                        lon=-43.9378,
                        label="Savassi",
                    ),
                ],
            },
        )
        stats = refresh_neighbourhood_access(db_session, cfg)
        assert stats["updated"] == 1
        assert stats["errors"] == 0

        client = TestClient(app)
        response = client.get(f"/properties/neighborhoods/{nid}")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["access_score"] is not None
        assert 0.0 <= data["access_score"] <= 1.0
        assert data["quality_meta"]["provider"] == "curated-yaml"
        access = data["quality_meta"]["access"]
        assert access["hub_id"] == "savassi"
        assert access["mode"] == "driving"
        assert access["provider"] == "haversine"
        assert access["minutes"] >= 0

    def test_osrm_client_preferred_when_base_url_set(self, db_session):
        db_session.execute(
            text(
                """
                INSERT INTO neighborhoods (name, city, state, geometry)
                VALUES (
                    'OsrmFixture',
                    'Belo Horizonte',
                    'MG',
                    ST_GeomFromText(
                        'POLYGON((-43.94 -19.94, -43.93 -19.94, -43.93 -19.93, -43.94 -19.93, -43.94 -19.94))',
                        4326
                    )
                )
                """
            )
        )
        db_session.commit()

        http = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "code": "Ok",
            "routes": [{"duration": 720.0, "distance": 5000.0}],
        }
        http.get.return_value = response
        osrm = OsrmClient("http://osrm.test:5000", mode="driving", client=http)

        cfg = NeighbourhoodAccessConfig(
            enabled=True,
            base_url="http://osrm.test:5000",
            mode="driving",
            max_minutes=45.0,
            avg_speed_kmh=30.0,
            hubs={
                "Belo Horizonte": [
                    AccessHubConfig(id="praca-sete", lat=-19.9191, lon=-43.9386),
                ],
            },
        )
        stats = refresh_neighbourhood_access(db_session, cfg, osrm_client=osrm)
        assert stats["updated"] == 1

        stored = db_session.execute(
            text(
                "SELECT access_score, quality_meta "
                "FROM neighborhoods WHERE name = 'OsrmFixture'"
            )
        ).mappings().one()
        assert stored["access_score"] == pytest.approx(1.0 - (12.0 / 45.0))
        assert stored["quality_meta"]["access"]["provider"] == "osrm"
        assert stored["quality_meta"]["access"]["minutes"] == pytest.approx(12.0)
        assert stored["quality_meta"]["access"]["hub_id"] == "praca-sete"

    def test_skips_city_without_hubs(self, db_session):
        db_session.execute(
            text(
                """
                INSERT INTO neighborhoods (name, city, state, geometry)
                VALUES (
                    'NoHubCity',
                    'Curitiba',
                    'PR',
                    ST_GeomFromText(
                        'POLYGON((-49.28 -25.44, -49.27 -25.44, -49.27 -25.43, -49.28 -25.43, -49.28 -25.44))',
                        4326
                    )
                )
                """
            )
        )
        db_session.commit()
        cfg = NeighbourhoodAccessConfig(
            hubs={"Belo Horizonte": [AccessHubConfig(id="x", lat=-19.9, lon=-43.9)]}
        )
        stats = refresh_neighbourhood_access(db_session, cfg)
        assert stats["skipped"] >= 1
        assert stats["updated"] == 0
