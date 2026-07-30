"""Characterization + query-count lock for compute_neighborhood_stats (BIN-151).

Before this fix, compute_neighborhood_stats looped over every scored property
row and ran a MetricsScoring lookup, a Property.get, and (indirectly) a
Neighborhood lookup per row — a classic N+1. The fix batch-loads all three
once per call. These tests:

1. Characterize output: existing MetricsScoring (update path) and brand-new
   rows (insert path), with and without a linked Neighborhood, must resolve
   ai_score / neighbourhood quality / combined_score identically to calling
   the per-property helpers directly.
2. Lock the query shape: the number of SELECT statements issued by
   compute_neighborhood_stats must stay constant as the number of scored
   properties grows (O(1) round trips, not O(N)), verified via a real
   SQLAlchemy `before_cursor_execute` event listener (no session mocking).
"""

from __future__ import annotations

from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import event

from adapters.db.models import MetricsScoring, Neighborhood, Property
from adapters.metrics.scoring import (
    _scoring_weights,
    blend_combined_score,
    compute_neighborhood_stats,
)


@pytest.fixture(scope="function")
def db_session(wipe_safe_db_session):
    """DB session on the isolated test database (BIN-71)."""
    yield wipe_safe_db_session


@contextmanager
def _count_select_statements(engine):
    """Count real SELECT statements sent to the DB (event-based, no mocks)."""
    statements: list[str] = []

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        if statement.strip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)


def _neighborhood(session, **scores) -> Neighborhood:
    n = Neighborhood(
        name=f"N1Cohort-{uuid4().hex[:8]}",
        city="Belo Horizonte",
        state="MG",
        **scores,
    )
    session.add(n)
    session.flush()
    return n


def _property(
    session,
    *,
    price: float,
    area_m2: float = 100.0,
    n_key: str,
    neighborhood_id=None,
) -> Property:
    """Property in its own single-row price cohort (unique props_json label)

    so mean == price_per_m2 and stddev is NULL (falsy) -> z == 0.0,
    stat_score == sigmoid(0.0) == 0.5 for every fixture, no matter how many
    fixtures exist. That keeps the query-count test's row count free to grow
    without needing to hand-compute cohort statistics.
    """
    p = Property(
        platform="test",
        platform_id=f"p-{uuid4().hex[:12]}",
        title="N+1 fix fixture",
        price=price,
        area_m2=area_m2,
        neighborhood_id=neighborhood_id,
        props_json={"neighborhood": n_key},
        active=True,
    )
    session.add(p)
    session.flush()
    return p


def _metrics(session, property_id) -> MetricsScoring:
    return session.query(MetricsScoring).filter_by(property_id=property_id).one()


@pytest.mark.integration
class TestComputeNeighborhoodStatsCharacterization:
    """Locks per-row output through the batched loaders (BIN-151)."""

    def test_batched_lookups_match_update_and_insert_paths(self, db_session):
        # Each FK-linked property gets its OWN Neighborhood row (same quality
        # scores, distinct name) — compute_neighborhood_stats' cohort key is
        # COALESCE(n.name, props_json->>'neighborhood', 'Unknown'), so sharing
        # one Neighborhood row across properties would merge their price
        # cohorts regardless of the props_json label used below.
        nhood_p1 = _neighborhood(db_session, amenity_score=0.9, transit_score=0.7)
        nhood_p3 = _neighborhood(db_session, amenity_score=0.9, transit_score=0.7)

        # P1: existing MetricsScoring (update path) + linked Neighborhood.
        p1 = _property(db_session, price=10_000, n_key=f"solo-{uuid4().hex[:8]}", neighborhood_id=nhood_p1.id)
        existing_ms = MetricsScoring(property_id=p1.id, ai_score=0.3)
        db_session.add(existing_ms)

        # P2: brand-new MetricsScoring (insert path), no Neighborhood link.
        p2 = _property(db_session, price=20_000, n_key=f"solo-{uuid4().hex[:8]}")

        # P3: brand-new MetricsScoring (insert path) + linked Neighborhood.
        p3 = _property(db_session, price=30_000, n_key=f"solo-{uuid4().hex[:8]}", neighborhood_id=nhood_p3.id)

        db_session.commit()

        count = compute_neighborhood_stats(db_session)
        db_session.commit()

        assert count == 3

        weights = _scoring_weights()
        nhood_score = 0.8  # avg(0.9, 0.7)

        # Each fixture is alone in its price cohort -> stddev NULL -> z=0.0
        # -> stat_score = sigmoid(0.0) = 0.5 for all three, regardless of price.
        ms1 = _metrics(db_session, p1.id)
        assert ms1.stat_score == pytest.approx(0.5)
        assert ms1.combined_score == pytest.approx(
            blend_combined_score(0.5, 0.3, nhood_score, weights)
        )

        ms2 = _metrics(db_session, p2.id)
        assert ms2.stat_score == pytest.approx(0.5)
        assert ms2.combined_score == pytest.approx(
            blend_combined_score(0.5, 0.0, 0.5, weights)
        )

        ms3 = _metrics(db_session, p3.id)
        assert ms3.stat_score == pytest.approx(0.5)
        assert ms3.combined_score == pytest.approx(
            blend_combined_score(0.5, 0.0, nhood_score, weights)
        )


@pytest.mark.integration
class TestComputeNeighborhoodStatsQueryCount:
    """Locks O(1) SELECT round trips regardless of scored-property count (BIN-151)."""

    def test_select_count_does_not_grow_with_property_count(self, db_session):
        engine = db_session.get_bind()
        nhood = _neighborhood(db_session, amenity_score=0.5)

        # Round 1: 2 scored properties.
        for _ in range(2):
            _property(
                db_session,
                price=10_000,
                n_key=f"solo-{uuid4().hex[:8]}",
                neighborhood_id=nhood.id,
            )
        db_session.commit()

        with _count_select_statements(engine) as statements_small:
            count_small = compute_neighborhood_stats(db_session)
        db_session.commit()

        # Round 2: 6 more scored properties (8 total in the DB).
        for _ in range(6):
            _property(
                db_session,
                price=10_000,
                n_key=f"solo-{uuid4().hex[:8]}",
                neighborhood_id=nhood.id,
            )
        db_session.commit()

        with _count_select_statements(engine) as statements_large:
            count_large = compute_neighborhood_stats(db_session)
        db_session.commit()

        assert count_small == 2
        assert count_large == 8

        # The whole point of BIN-151: SELECT round trips per call are O(1)
        # (main window-function query + one batch load each for
        # MetricsScoring/Property/Neighborhood), not O(number of properties).
        assert len(statements_small) == len(statements_large)
        assert len(statements_small) <= 4
