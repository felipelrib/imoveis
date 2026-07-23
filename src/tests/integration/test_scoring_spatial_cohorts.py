"""Integration: scoring cohorts prefer spatial neighborhood_id over props_json."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from adapters.db.models import Base, MetricsScoring, Neighborhood, Property
from adapters.metrics.scoring import (
    _property_neighborhood_key,
    compute_neighborhood_stats,
)
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
STRING_COHORT = "StringOnlyCohort"


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


def _fixture_a(session) -> Neighborhood:
    return (
        session.query(Neighborhood)
        .filter_by(name="FixtureA", city="Belo Horizonte", state="MG")
        .one()
    )


def _make_property(
    session,
    *,
    price: float,
    area_m2: float,
    props_neighborhood: str | None = None,
    neighborhood_id=None,
    lon: float | None = None,
    lat: float | None = None,
) -> Property:
    location = None
    if lon is not None and lat is not None:
        location = from_shape(Point(lon, lat), srid=4326)
    props = {}
    if props_neighborhood is not None:
        props["neighborhood"] = props_neighborhood
    prop = Property(
        platform="test",
        platform_id=f"p-{uuid4().hex[:12]}",
        title="Scoring cohort fixture",
        price=price,
        area_m2=area_m2,
        location=location,
        neighborhood_id=neighborhood_id,
        props_json=props or None,
        active=True,
    )
    session.add(prop)
    session.flush()
    return prop


def _metrics(session, property_id) -> MetricsScoring:
    return session.query(MetricsScoring).filter_by(property_id=property_id).one()


@pytest.mark.integration
class TestScoringSpatialCohorts:
    def test_string_only_fallback_still_scores(self, db_session):
        """No FK: cohort is props_json string; stats still write metrics."""
        peer_a = _make_property(
            db_session,
            price=100_000,
            area_m2=100,
            props_neighborhood=STRING_COHORT,
        )
        peer_b = _make_property(
            db_session,
            price=200_000,
            area_m2=100,
            props_neighborhood=STRING_COHORT,
        )
        subject = _make_property(
            db_session,
            price=150_000,
            area_m2=100,
            props_neighborhood=STRING_COHORT,
        )
        db_session.commit()

        assert _property_neighborhood_key(db_session, subject) == STRING_COHORT
        count = compute_neighborhood_stats(db_session, STRING_COHORT)
        db_session.commit()

        assert count == 3
        ms = _metrics(db_session, subject.id)
        # mean of 1000, 2000, 1500 R$/m²
        assert ms.neighborhood_mean == pytest.approx(1500.0)
        assert ms.stat_score is not None

        # peers share the same cohort mean
        assert _metrics(db_session, peer_a.id).neighborhood_mean == pytest.approx(1500.0)
        assert _metrics(db_session, peer_b.id).neighborhood_mean == pytest.approx(1500.0)

    def test_spatial_fk_moves_cohort_membership(self, db_session):
        """Inside FixtureA polygon: after assignment, cohort mean leaves string peers."""
        load_neighbourhood_geojson(db_session, FIXTURE)
        db_session.commit()
        fixture_a = _fixture_a(db_session)

        # Expensive string-only cohort peers (no FK)
        _make_property(
            db_session,
            price=900_000,
            area_m2=100,
            props_neighborhood=STRING_COHORT,
        )
        _make_property(
            db_session,
            price=1_100_000,
            area_m2=100,
            props_neighborhood=STRING_COHORT,
        )

        # Cheaper FixtureA spatial peers (already linked)
        _make_property(
            db_session,
            price=100_000,
            area_m2=100,
            props_neighborhood=STRING_COHORT,
            neighborhood_id=fixture_a.id,
            lon=INSIDE[0],
            lat=INSIDE[1],
        )
        _make_property(
            db_session,
            price=200_000,
            area_m2=100,
            props_neighborhood=STRING_COHORT,
            neighborhood_id=fixture_a.id,
            lon=INSIDE[0],
            lat=INSIDE[1],
        )

        # Subject: same string label, point inside FixtureA, FK not yet set
        subject = _make_property(
            db_session,
            price=150_000,
            area_m2=100,
            props_neighborhood=STRING_COHORT,
            lon=INSIDE[0],
            lat=INSIDE[1],
        )
        db_session.commit()

        assert subject.neighborhood_id is None
        assert _property_neighborhood_key(db_session, subject) == STRING_COHORT

        compute_neighborhood_stats(db_session)
        db_session.commit()
        mean_before = _metrics(db_session, subject.id).neighborhood_mean
        # String cohort only (FK peers already in FixtureA): 9000, 11000, 1500 → 21500/3
        assert mean_before == pytest.approx(21500.0 / 3)

        assigned = assign_property_neighbourhood(db_session, subject.id)
        db_session.commit()
        assert assigned == fixture_a.id
        db_session.refresh(subject)
        assert subject.neighborhood_id == fixture_a.id
        assert _property_neighborhood_key(db_session, subject) == "FixtureA"

        compute_neighborhood_stats(db_session)
        db_session.commit()
        mean_after = _metrics(db_session, subject.id).neighborhood_mean
        # FixtureA cohort: 1000, 2000, 1500 → mean 1500
        assert mean_after == pytest.approx(1500.0)
        assert mean_after != pytest.approx(mean_before)
