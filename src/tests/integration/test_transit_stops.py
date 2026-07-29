"""Integration: persist transit_stops idempotently and score from DB (BIN-118)."""

from __future__ import annotations

from pathlib import Path

import pytest
from geoalchemy2.shape import to_shape

from adapters.db.models import Neighborhood, TransitStopRecord
from adapters.geo.transit_refresh import refresh_transit_proximity
from core.neighbourhood_geojson import load_neighbourhood_geojson
from core.transit_proximity import merge_stops, parse_gtfs_stops, parse_osm_transit_geojson
from core.transit_stops import external_id_for, stops_from_db, upsert_transit_stops

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
class TestTransitStopsPersistence:
    def test_upsert_idempotent_then_score_from_db(self, db_session):
        load_neighbourhood_geojson(db_session, GEO_FIXTURE)
        db_session.commit()

        stops = merge_stops(
            parse_gtfs_stops(GTFS_DIR),
            parse_osm_transit_geojson(OSM_GEOJSON),
        )
        assert len(stops) >= 2

        first = upsert_transit_stops(db_session, stops)
        db_session.commit()
        assert first.inserted == len(stops)
        assert first.updated == 0
        assert first.skipped == 0
        assert db_session.query(TransitStopRecord).count() == len(stops)

        second = upsert_transit_stops(db_session, stops)
        db_session.commit()
        assert second.inserted == 0
        assert second.updated == 0
        assert second.skipped == len(stops)
        assert db_session.query(TransitStopRecord).count() == len(stops)

        loaded = stops_from_db(db_session)
        assert len(loaded) == len(stops)
        assert {s.stop_id for s in loaded} == {external_id_for(s) for s in stops}

        result = refresh_transit_proximity(
            db_session,
            from_db=True,
            persist=False,
            dry_run=False,
        )
        assert result.status == "ok"
        assert result.mode == "from_db"
        assert result.neighbourhoods_updated >= 1

        scored = (
            db_session.query(Neighborhood)
            .filter(Neighborhood.transit_score.isnot(None))
            .count()
        )
        assert scored >= 1
        fixture_a = (
            db_session.query(Neighborhood).filter_by(name="FixtureA").one()
        )
        assert fixture_a.transit_score is not None
        assert fixture_a.quality_meta["transit"]["provider"] == "db"
        # Geometry round-trip sanity
        row = db_session.query(TransitStopRecord).first()
        pt = to_shape(row.location)
        assert pt.geom_type == "Point"
