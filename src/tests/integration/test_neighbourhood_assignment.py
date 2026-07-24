"""Integration: assign properties to neighbourhoods via ST_Covers."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Point

from adapters.db.models import Neighborhood, Property
from core.neighbourhood_assignment import assign_property_neighbourhood
from core.neighbourhood_geojson import load_neighbourhood_geojson

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "geo"
    / "bh_neighbourhoods_tiny.geojson"
)

# FixtureA: lon [-43.94, -43.935], lat [-19.92, -19.915]
INSIDE = (-43.9375, -19.9175)
BOUNDARY = (-43.9400, -19.9175)  # west edge
OUTSIDE = (-43.9300, -19.9100)


@pytest.fixture(scope="function")
def db_session(wipe_safe_db_session):
    """DB session on the isolated test database (BIN-71)."""
    yield wipe_safe_db_session


def _fixture_a_id(session) -> object:
    row = (
        session.query(Neighborhood)
        .filter_by(name="FixtureA", city="Belo Horizonte", state="MG")
        .one()
    )
    return row.id


def _make_property(session, *, lon: float | None, lat: float | None, neighborhood_id=None):
    location = None
    if lon is not None and lat is not None:
        location = from_shape(Point(lon, lat), srid=4326)
    prop = Property(
        platform="test",
        platform_id=f"p-{uuid4().hex[:12]}",
        title="Spatial fixture",
        price=100000.0,
        location=location,
        neighborhood_id=neighborhood_id,
    )
    session.add(prop)
    session.flush()
    return prop


@pytest.mark.integration
class TestAssignPropertyNeighbourhood:
    def test_inside_assigns_fixture_a(self, db_session):
        load_neighbourhood_geojson(db_session, FIXTURE)
        db_session.commit()
        expected = _fixture_a_id(db_session)

        prop = _make_property(db_session, lon=INSIDE[0], lat=INSIDE[1])
        assigned = assign_property_neighbourhood(db_session, prop.id)
        db_session.commit()

        assert assigned == expected
        db_session.refresh(prop)
        assert prop.neighborhood_id == expected

    def test_boundary_assigns_fixture_a(self, db_session):
        load_neighbourhood_geojson(db_session, FIXTURE)
        db_session.commit()
        expected = _fixture_a_id(db_session)

        prop = _make_property(db_session, lon=BOUNDARY[0], lat=BOUNDARY[1])
        assigned = assign_property_neighbourhood(db_session, prop.id)
        db_session.commit()

        assert assigned == expected
        db_session.refresh(prop)
        assert prop.neighborhood_id == expected

    def test_outside_clears_to_null(self, db_session):
        load_neighbourhood_geojson(db_session, FIXTURE)
        db_session.commit()

        prop = _make_property(db_session, lon=OUTSIDE[0], lat=OUTSIDE[1])
        assigned = assign_property_neighbourhood(db_session, prop.id)
        db_session.commit()

        assert assigned is None
        db_session.refresh(prop)
        assert prop.neighborhood_id is None

    def test_null_location_leaves_existing_fk(self, db_session):
        load_neighbourhood_geojson(db_session, FIXTURE)
        db_session.commit()
        existing = _fixture_a_id(db_session)

        prop = _make_property(
            db_session, lon=None, lat=None, neighborhood_id=existing
        )
        assigned = assign_property_neighbourhood(db_session, prop.id)
        db_session.commit()

        assert assigned == existing
        db_session.refresh(prop)
        assert prop.neighborhood_id == existing

    def test_reassign_clears_stale_fk_when_outside(self, db_session):
        load_neighbourhood_geojson(db_session, FIXTURE)
        db_session.commit()
        stale = _fixture_a_id(db_session)

        prop = _make_property(
            db_session,
            lon=OUTSIDE[0],
            lat=OUTSIDE[1],
            neighborhood_id=stale,
        )
        assigned = assign_property_neighbourhood(db_session, prop.id)
        db_session.commit()

        assert assigned is None
        db_session.refresh(prop)
        assert prop.neighborhood_id is None
