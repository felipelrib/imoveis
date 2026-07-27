"""Integration: scoring cohorts prefer spatial neighborhood_id over props_json."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Point

from adapters.db.models import MetricsScoring, Neighborhood, Property
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
def db_session(wipe_safe_db_session):
    """DB session on the isolated test database (BIN-71)."""
    yield wipe_safe_db_session


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


@pytest.mark.integration
class TestRentSalePricePerM2Cohorts:
    """BIN-84: rent and sale $/m² must not share a neighbourhood average."""

    def test_rent_mean_ignores_sale_peers(self, db_session):
        from adapters.db.models import PropertyListing

        def _add_listing(prop, *, listing_type: str, price: float) -> None:
            db_session.add(
                PropertyListing(
                    property_id=prop.id,
                    platform="test",
                    platform_listing_id=f"{prop.platform_id}-{listing_type}",
                    listing_type=listing_type,
                    price=price,
                    currency="BRL",
                    url=f"https://example.test/{prop.platform_id}/{listing_type}",
                    active=True,
                )
            )

        rent_peer = _make_property(
            db_session,
            price=5_000,
            area_m2=100,
            props_neighborhood=STRING_COHORT,
        )
        _add_listing(rent_peer, listing_type="rent", price=5_000)

        sale_peer = _make_property(
            db_session,
            price=400_000,
            area_m2=100,
            props_neighborhood=STRING_COHORT,
        )
        _add_listing(sale_peer, listing_type="sale", price=400_000)

        subject = _make_property(
            db_session,
            price=4_700,
            area_m2=100,
            props_neighborhood=STRING_COHORT,
        )
        _add_listing(subject, listing_type="rent", price=4_700)
        db_session.commit()

        count = compute_neighborhood_stats(db_session, STRING_COHORT)
        db_session.commit()
        assert count == 3

        ms = _metrics(db_session, subject.id)
        # Rent cohort only: 50 + 47 → mean 48.5 (sale 4000 must not blend in)
        assert ms.price_per_m2_rent == pytest.approx(47.0)
        assert ms.price_per_m2_sale is None
        assert ms.neighborhood_mean_rent == pytest.approx(48.5)
        assert ms.neighborhood_mean_sale is None
        assert ms.price_per_m2 == pytest.approx(47.0)
        assert ms.neighborhood_mean == pytest.approx(48.5)
        # Must not look like the sale peer average
        assert ms.neighborhood_mean != pytest.approx(4000.0)
        assert abs(ms.neighborhood_mean - 48.5) < abs(ms.neighborhood_mean - 4000.0)

        sale_ms = _metrics(db_session, sale_peer.id)
        assert sale_ms.price_per_m2_sale == pytest.approx(4000.0)
        assert sale_ms.neighborhood_mean_sale == pytest.approx(4000.0)
        assert sale_ms.price_per_m2_rent is None
        assert sale_ms.neighborhood_mean == pytest.approx(4000.0)

    def test_dual_listed_stores_both_means(self, db_session):
        from adapters.db.models import PropertyListing

        def _add_listing(prop, *, listing_type: str, price: float) -> None:
            db_session.add(
                PropertyListing(
                    property_id=prop.id,
                    platform="test",
                    platform_listing_id=f"{prop.platform_id}-{listing_type}",
                    listing_type=listing_type,
                    price=price,
                    currency="BRL",
                    url=f"https://example.test/{prop.platform_id}/{listing_type}",
                    active=True,
                )
            )

        peer_rent = _make_property(
            db_session, price=5_000, area_m2=100, props_neighborhood=STRING_COHORT
        )
        _add_listing(peer_rent, listing_type="rent", price=5_000)

        peer_sale = _make_property(
            db_session, price=500_000, area_m2=100, props_neighborhood=STRING_COHORT
        )
        _add_listing(peer_sale, listing_type="sale", price=500_000)

        dual = _make_property(
            db_session, price=4_000, area_m2=100, props_neighborhood=STRING_COHORT
        )
        _add_listing(dual, listing_type="rent", price=4_000)
        _add_listing(dual, listing_type="sale", price=300_000)
        db_session.commit()

        compute_neighborhood_stats(db_session, STRING_COHORT)
        db_session.commit()

        ms = _metrics(db_session, dual.id)
        assert ms.price_per_m2_rent == pytest.approx(40.0)
        assert ms.price_per_m2_sale == pytest.approx(3000.0)
        # Rent mean: (50 + 40) / 2 = 45; sale mean: (5000 + 3000) / 2 = 4000
        assert ms.neighborhood_mean_rent == pytest.approx(45.0)
        assert ms.neighborhood_mean_sale == pytest.approx(4000.0)
        # Legacy primary = rent
        assert ms.price_per_m2 == pytest.approx(40.0)
        assert ms.neighborhood_mean == pytest.approx(45.0)
