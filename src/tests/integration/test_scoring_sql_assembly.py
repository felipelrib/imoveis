"""Characterization lock for scoring.py SQL assembled via string concatenation (BIN-135).

recalculate_all_combined_scores() and get_neighborhood_stats_cached() had no
DB-level test coverage before BIN-135 rewrote their f-string-built text()
queries as plain concatenation (never an f-string) to close the "NEVER
f-string SQL" gap. These tests lock the pre-existing behavior against a real
PostGIS/Redis instance so a future edit to the query assembly cannot silently
change semantics.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from adapters.db.models import MetricsScoring, Neighborhood, Property
from adapters.metrics.scoring import (
    get_neighborhood_stats_cached,
    recalculate_all_combined_scores,
)
from core.entities import ScoringWeights
from tests.env_helpers import get_redis_url
from tests.redis_isolation import assert_wipe_safe_redis_url


@pytest.fixture(scope="function")
def db_session(wipe_safe_db_session):
    yield wipe_safe_db_session


@pytest.fixture(scope="function")
def real_redis():
    """Real Redis on the isolated test DB (BIN-117); skip if unavailable."""
    redis_url = get_redis_url()
    if not redis_url:
        pytest.skip("REDIS_URL not set — run via validate.sh backend/all")
    import redis

    assert_wipe_safe_redis_url(redis_url)
    client = redis.Redis.from_url(redis_url)
    client.flushdb()
    yield client
    assert_wipe_safe_redis_url(redis_url)
    client.flushdb()
    client.close()


def _neighborhood(session, **scores) -> Neighborhood:
    n = Neighborhood(
        name=f"Cohort-{uuid4().hex[:8]}",
        city="Belo Horizonte",
        state="MG",
        amenity_score=scores.get("amenity_score"),
        transit_score=scores.get("transit_score"),
        access_score=scores.get("access_score"),
        safety_score=scores.get("safety_score"),
    )
    session.add(n)
    session.flush()
    return n


def _property(session, *, neighborhood_id, price=1000.0, area_m2=50.0) -> Property:
    p = Property(
        platform="test",
        platform_id=f"p-{uuid4().hex[:12]}",
        title="Scoring SQL assembly fixture",
        price=price,
        area_m2=area_m2,
        neighborhood_id=neighborhood_id,
        active=True,
    )
    session.add(p)
    session.flush()
    return p


@pytest.mark.integration
class TestRecalculateAllCombinedScores:
    def test_blends_stat_ai_neighbourhood_with_configured_weights(self, db_session):
        # amenity=0.8, transit=0.6 -> nhood score = avg(0.8, 0.6) = 0.7
        nhood = _neighborhood(db_session, amenity_score=0.8, transit_score=0.6)
        prop = _property(db_session, neighborhood_id=nhood.id)
        ms = MetricsScoring(
            property_id=prop.id,
            stat_score=0.4,
            stat_score_rent=0.5,
            stat_score_sale=None,
            ai_score=0.2,
        )
        db_session.add(ms)
        db_session.commit()

        weights = ScoringWeights(stat_weight=0.5, ai_weight=0.3, neighbourhood_weight=0.2)
        count = recalculate_all_combined_scores(db_session, weights)
        db_session.commit()

        assert count == 1
        updated = db_session.query(MetricsScoring).filter_by(property_id=prop.id).one()
        # combined_score = stat_score*w_stat + ai_score*w_ai + nhood*w_nhood
        assert updated.combined_score == pytest.approx(0.4 * 0.5 + 0.2 * 0.3 + 0.7 * 0.2)
        # combined_score_rent uses stat_score_rent when present
        assert updated.combined_score_rent == pytest.approx(0.5 * 0.5 + 0.2 * 0.3 + 0.7 * 0.2)
        # combined_score_sale is NULL when stat_score_sale is NULL
        assert updated.combined_score_sale is None

    def test_neighbourhood_score_defaults_to_half_when_all_scores_missing(self, db_session):
        nhood = _neighborhood(db_session)  # no amenity/transit/access/safety
        prop = _property(db_session, neighborhood_id=nhood.id)
        ms = MetricsScoring(property_id=prop.id, stat_score=0.0, ai_score=0.0)
        db_session.add(ms)
        db_session.commit()

        weights = ScoringWeights(stat_weight=0.0, ai_weight=0.0, neighbourhood_weight=1.0)
        recalculate_all_combined_scores(db_session, weights)
        db_session.commit()

        updated = db_session.query(MetricsScoring).filter_by(property_id=prop.id).one()
        assert updated.combined_score == pytest.approx(0.5)


@pytest.mark.integration
class TestGetNeighborhoodStatsCached:
    def test_computes_mean_median_stddev_from_active_listings(self, db_session, real_redis):
        # get_neighborhood_stats_cached() resolves Redis via infra.redis_client.get_redis(),
        # which reads REDIS_URL from AppConfig — same isolated test DB (15) real_redis uses.
        n_key = f"cohort-{uuid4().hex[:8]}"
        for price in (1000.0, 2000.0, 3000.0):
            p = Property(
                platform="test",
                platform_id=f"p-{uuid4().hex[:12]}",
                title="Cached stats fixture",
                price=price,
                area_m2=100.0,
                active=True,
                props_json={"neighborhood": n_key, "available_for_rent": True},
            )
            db_session.add(p)
        db_session.commit()

        stats = get_neighborhood_stats_cached(db_session, n_key, listing_type="rent")

        # price_per_m2 = 10, 20, 30 -> mean 20
        assert stats["mean"] == pytest.approx(20.0)
        assert stats["median"] == pytest.approx(20.0)
        assert stats["count"] == 3

    def test_empty_cohort_returns_zeroed_stats(self, db_session, real_redis):
        n_key = f"empty-cohort-{uuid4().hex[:8]}"
        stats = get_neighborhood_stats_cached(db_session, n_key, listing_type="sale")

        assert stats == {"mean": 0.0, "median": 0.0, "stddev": 0.0, "count": 0}

    def test_result_is_cached_in_redis(self, db_session, real_redis):
        n_key = f"cache-check-{uuid4().hex[:8]}"
        get_neighborhood_stats_cached(db_session, n_key, listing_type="rent")
        cache_key = f"n_stats:{n_key}:rent"
        assert real_redis.get(cache_key) is not None
