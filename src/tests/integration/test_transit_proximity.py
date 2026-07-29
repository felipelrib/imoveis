"""Integration: transit proximity scores land on neighbourhoods API (BIN-89)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from geoalchemy2.shape import to_shape

from adapters.db.models import Neighborhood
from api.main import app
from core.gtfs_headways import TRANSIT_HEADWAY_DISCLAIMER, parse_gtfs_stop_headways
from core.neighbourhood_geojson import load_neighbourhood_geojson
from core.transit_proximity import (
    apply_transit_scores,
    merge_stops,
    parse_gtfs_stops,
    parse_osm_transit_geojson,
    score_neighbourhood_rows,
)

GEO_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "geo"
    / "bh_neighbourhoods_tiny.geojson"
)
GTFS_DIR = (
    Path(__file__).resolve().parents[1] / "fixtures" / "transit" / "gtfs_tiny"
)
OSM_GEOJSON = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "transit"
    / "osm_stops_tiny.geojson"
)


@pytest.fixture(scope="function")
def db_session(wipe_safe_db_session):
    yield wipe_safe_db_session


@pytest.mark.integration
class TestTransitProximityRefresh:
    def test_apply_scores_visible_on_neighbourhood_detail(self, db_session):
        load_neighbourhood_geojson(db_session, GEO_FIXTURE)
        db_session.commit()

        # Preserve unrelated meta keys when merging transit.
        fixture_a = (
            db_session.query(Neighborhood).filter_by(name="FixtureA").one()
        )
        fixture_a.amenity_score = 0.42
        fixture_a.quality_meta = {"provider": "curated-yaml", "note": "keep"}
        db_session.commit()

        stops = merge_stops(
            parse_gtfs_stops(GTFS_DIR),
            parse_osm_transit_geojson(OSM_GEOJSON),
        )
        headways = parse_gtfs_stop_headways(GTFS_DIR)
        rows = [
            (n.id, to_shape(n.geometry))
            for n in db_session.query(Neighborhood).all()
            if n.geometry is not None
        ]
        scores = score_neighbourhood_rows(
            rows, stops, provider="gtfs+osm", stop_headways=headways
        )
        updated = apply_transit_scores(db_session, scores)
        db_session.commit()
        assert updated == 3

        db_session.refresh(fixture_a)
        assert fixture_a.transit_score is not None
        assert fixture_a.transit_score > 0.0
        assert fixture_a.amenity_score == pytest.approx(0.42)
        assert fixture_a.quality_meta["provider"] == "curated-yaml"
        assert fixture_a.quality_meta["note"] == "keep"
        assert fixture_a.quality_meta["transit"]["provider"] == "gtfs+osm"
        assert fixture_a.quality_meta["transit"]["stop_count"] >= 1
        assert fixture_a.quality_meta["transit"]["headway"]["method"] == (
            "gtfs_frequencies"
        )
        assert fixture_a.quality_meta["transit"]["headway"]["median_headway_min"] == 10
        assert (
            fixture_a.quality_meta["transit"]["headway"]["disclaimer"]
            == TRANSIT_HEADWAY_DISCLAIMER
        )

        client = TestClient(app)
        response = client.get(f"/properties/neighborhoods/{fixture_a.id}")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["transit_score"] == pytest.approx(fixture_a.transit_score)
        assert data["amenity_score"] == pytest.approx(0.42)
        assert data["quality_meta"]["transit"]["nearest_mode"] in {
            "metro",
            "brt",
            "bus",
        }
        assert data["quality_meta"]["transit"]["headway"]["method"] == (
            "gtfs_frequencies"
        )
        assert data["quality_meta"]["provider"] == "curated-yaml"
