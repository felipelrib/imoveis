"""Integration: load tiny neighbourhood GeoJSON into PostGIS (idempotent)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from geoalchemy2.shape import to_shape
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from adapters.db.models import Base, Neighborhood
from core.neighbourhood_geojson import load_neighbourhood_geojson, parse_feature_collection

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "geo"
    / "bh_neighbourhoods_tiny.geojson"
)


@pytest.fixture(scope="function")
def db_session():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set — integrate with validate.sh or set manually")

    engine = create_engine(database_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    with engine.connect() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
        conn.commit()
    engine.dispose()


@pytest.mark.integration
class TestLoadNeighbourhoodPolygons:
    def test_load_sets_valid_srid_4326_polygons(self, db_session):
        result = load_neighbourhood_geojson(db_session, FIXTURE)
        db_session.commit()

        assert result.inserted == 3
        assert result.updated == 0

        rows = db_session.query(Neighborhood).order_by(Neighborhood.name).all()
        assert len(rows) == 3

        for row in rows:
            assert row.geometry is not None
            checks = db_session.execute(
                text(
                    "SELECT ST_SRID(geometry) AS srid, ST_IsValid(geometry) AS ok, "
                    "GeometryType(geometry) AS gtype "
                    "FROM neighborhoods WHERE id = :id"
                ),
                {"id": row.id},
            ).mappings().one()
            assert checks["srid"] == 4326
            assert checks["ok"] is True
            assert checks["gtype"] == "POLYGON"
            shape = to_shape(row.geometry)
            assert shape.geom_type == "Polygon"

    def test_reload_identical_is_idempotent(self, db_session):
        first = load_neighbourhood_geojson(db_session, FIXTURE)
        db_session.commit()
        ids = {
            (r.name, r.city, r.state): r.id
            for r in db_session.query(Neighborhood).all()
        }

        second = load_neighbourhood_geojson(db_session, FIXTURE)
        db_session.commit()

        assert first.inserted == 3
        assert second.inserted == 0
        assert second.updated == 0
        assert second.skipped == 3
        assert db_session.query(Neighborhood).count() == 3
        for row in db_session.query(Neighborhood).all():
            assert ids[(row.name, row.city, row.state)] == row.id

    def test_reload_changed_geometry_updates(self, db_session):
        load_neighbourhood_geojson(db_session, FIXTURE)
        db_session.commit()
        original = (
            db_session.query(Neighborhood).filter_by(name="FixtureA").one()
        )
        original_id = original.id
        original_bounds = to_shape(original.geometry).bounds

        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        # Shift FixtureA east by 0.01 degrees
        for feat in data["features"]:
            if feat["properties"].get("name") == "FixtureA":
                ring = feat["geometry"]["coordinates"][0]
                feat["geometry"]["coordinates"][0] = [
                    [lon + 0.01, lat] for lon, lat in ring
                ]

        result = load_neighbourhood_geojson(db_session, data)
        db_session.commit()

        assert result.updated == 1
        assert result.inserted == 0
        updated = (
            db_session.query(Neighborhood).filter_by(name="FixtureA").one()
        )
        assert updated.id == original_id
        new_bounds = to_shape(updated.geometry).bounds
        assert new_bounds != original_bounds
        assert new_bounds[0] == pytest.approx(original_bounds[0] + 0.01)

    def test_unique_key_enforced(self, db_session):
        from core.neighbourhood_geojson import upsert_neighbourhoods

        rows = parse_feature_collection(FIXTURE)
        # Same natural key twice in one payload: one insert, then skip
        duplicate_a = [rows[0], rows[0]]
        result = upsert_neighbourhoods(db_session, duplicate_a)
        db_session.commit()

        assert db_session.query(Neighborhood).filter_by(name="FixtureA").count() == 1
        assert result.inserted == 1
        assert result.skipped == 1
