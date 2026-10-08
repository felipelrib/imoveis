"""Characterization lock for the scoring stage (Story 1.3, landed before any change).

One seeded cohort set, every ``metrics_scoring`` stat column asserted against
hand-computed values, through the three paths that read a Listing price:

* ``compute_neighborhood_stats``   (bulk recalculation)
* ``get_neighborhood_stats_cached`` (cohort stats for one type)
* ``score_single_property``        (post-enrichment single row)

No fixture Listing carries ``rent_monthly``, so every row here is scored from
the published headline ``price``. This file is not edited by later commits: a
change to the scoring SQL or to the price a path reads must keep it green.

Seed (all ``area_m2`` 100, cohort ``LockCohort``, no neighbourhood FK):

    R1  one rent Listing 3000                          rent 30
    R2  two rent Listings 5000 and 4000 (lowest wins)  rent 40
    D   rent Listing 5000 + sale Listing 500000        rent 50, sale 5000
    S   one sale Listing 400000                        sale 4000
    L   no Listing, properties.price 7000, no flags    rent 70 (legacy)
    LS  no Listing, properties.price 750000, sale flag sale 7500 (legacy)

Rent cohort 30 / 40 / 50 / 70: mean 47.5, median 45, sample stddev
sqrt(875 / 3) = 17.0782513. Sale cohort 4000 / 5000 / 7500: mean 5500,
median 5000, sample stddev sqrt(3 250 000) = 1802.7756377.
"""

from __future__ import annotations

import math
from uuid import uuid4

import pytest

from adapters.db.models import MetricsScoring, Property, PropertyListing
from adapters.metrics.scoring import (
    _scoring_weights,
    compute_neighborhood_stats,
    get_neighborhood_stats_cached,
    score_single_property,
)
from tests.env_helpers import get_redis_url
from tests.redis_isolation import assert_wipe_safe_redis_url

COHORT = "LockCohort"
OTHER_COHORT = "LockOtherCohort"
NHOOD_NEUTRAL = 0.5  # no neighbourhood FK -> neutral quality score
D_AI_SCORE = 0.4  # D starts with a MetricsScoring row (update path)

RENT_MEAN, RENT_MEDIAN, RENT_STDDEV = 47.5, 45.0, 17.078251276599330
SALE_MEAN, SALE_MEDIAN, SALE_STDDEV = 5500.0, 5000.0, 1802.7756377319947

# name -> (ppm, z, percent_rank, stat band) per listing type, hand-computed.
RENT = {
    "R1": (30.0, -1.0246950765959597, 0.0, "highly_undervalued"),
    "R2": (40.0, -0.4391550328268399, 1 / 3, "slightly_undervalued"),
    "D": (50.0, 0.14638501094227996, 2 / 3, "average"),
    "L": (70.0, 1.3174650984805196, 1.0, "highly_overvalued"),
}
SALE = {
    "S": (4000.0, -0.8320502943378437, 0.0, "slightly_undervalued"),
    "D": (5000.0, -0.2773500981126146, 0.5, "slightly_undervalued"),
    "LS": (7500.0, 1.1094003924504583, 1.0, "highly_overvalued"),
}
NAMES = ("R1", "R2", "D", "S", "L", "LS")
ABS = 1e-6


@pytest.fixture(scope="function")
def db_session(wipe_safe_db_session):
    """DB session on the isolated test database (BIN-71)."""
    yield wipe_safe_db_session


@pytest.fixture(scope="function")
def real_redis():
    """Real Redis on the isolated test DB (BIN-117); skip if unavailable."""
    redis_url = get_redis_url()
    if not redis_url:
        pytest.skip("REDIS_URL not set — run through scripts/agent/validate.py")
    import redis

    assert_wipe_safe_redis_url(redis_url)
    client = redis.Redis.from_url(redis_url)
    client.flushdb()
    yield client
    assert_wipe_safe_redis_url(redis_url)
    client.flushdb()
    client.close()


def _sigmoid(z: float) -> float:
    """Independent copy of the stat-score mapping: lower price, higher score."""
    return 1.0 / (1.0 + math.exp(z))


def _combined(stat: float, ai: float) -> float:
    weights = _scoring_weights()
    return (
        stat * weights.stat_weight
        + ai * weights.ai_weight
        + NHOOD_NEUTRAL * weights.neighbourhood_weight
    )


def _make_property(session, *, price: float, cohort: str = COHORT, **flags) -> Property:
    prop = Property(
        platform="test",
        platform_id=f"p-{uuid4().hex[:12]}",
        title="Scoring characterization fixture",
        price=price,
        area_m2=100.0,
        props_json={"neighborhood": cohort, **flags},
        active=True,
    )
    session.add(prop)
    session.flush()
    return prop


def _add_listing(session, prop: Property, *, listing_type: str, price: float) -> None:
    session.add(
        PropertyListing(
            property_id=prop.id,
            platform="test",
            platform_listing_id=f"l-{uuid4().hex[:12]}",
            listing_type=listing_type,
            price=price,
            currency="BRL",
            url=f"https://example.test/{uuid4().hex[:8]}",
            active=True,
        )
    )


def _seed(session) -> dict[str, Property]:
    """Seed the cohort set; ``properties.price`` never equals a Listing price."""
    props: dict[str, Property] = {}

    props["R1"] = _make_property(session, price=9_999)
    _add_listing(session, props["R1"], listing_type="rent", price=3_000)

    props["R2"] = _make_property(session, price=9_999)
    _add_listing(session, props["R2"], listing_type="rent", price=5_000)
    _add_listing(session, props["R2"], listing_type="rent", price=4_000)

    props["D"] = _make_property(session, price=9_999)
    _add_listing(session, props["D"], listing_type="rent", price=5_000)
    _add_listing(session, props["D"], listing_type="sale", price=500_000)
    session.add(MetricsScoring(property_id=props["D"].id, ai_score=D_AI_SCORE))

    props["S"] = _make_property(session, price=9_999)
    _add_listing(session, props["S"], listing_type="sale", price=400_000)

    props["L"] = _make_property(session, price=7_000)
    props["LS"] = _make_property(session, price=750_000, available_for_sale=True)

    # Another cohort: must not enter LockCohort's statistics.
    outsider = _make_property(session, price=9_999, cohort=OTHER_COHORT)
    _add_listing(session, outsider, listing_type="rent", price=9_000)
    props["outsider"] = outsider

    session.commit()
    return props


def _metrics(session, prop: Property) -> MetricsScoring:
    session.expire_all()
    return session.query(MetricsScoring).filter_by(property_id=prop.id).one()


def _assert_type_columns(ms: MetricsScoring, name: str, *, ai: float, pct_from_bulk: bool) -> None:
    """Assert the per-type columns of one row for both listing types."""
    for suffix, table, mean, median in (
        ("rent", RENT, RENT_MEAN, RENT_MEDIAN),
        ("sale", SALE, SALE_MEAN, SALE_MEDIAN),
    ):
        ppm = getattr(ms, f"price_per_m2_{suffix}")
        if name not in table:
            assert ppm is None, (name, suffix)
            for column in (
                "neighborhood_mean",
                "neighborhood_median",
                "stat_score",
                "z_score",
                "percentile_rank",
                "combined_score",
            ):
                assert getattr(ms, f"{column}_{suffix}") is None, (name, column, suffix)
            continue
        exp_ppm, exp_z, exp_pct, _band = table[name]
        assert ppm == pytest.approx(exp_ppm, abs=ABS), (name, suffix)
        assert getattr(ms, f"neighborhood_mean_{suffix}") == pytest.approx(mean, abs=ABS)
        assert getattr(ms, f"neighborhood_median_{suffix}") == pytest.approx(median, abs=ABS)
        assert getattr(ms, f"z_score_{suffix}") == pytest.approx(exp_z, abs=ABS), (name, suffix)
        assert getattr(ms, f"stat_score_{suffix}") == pytest.approx(_sigmoid(exp_z), abs=ABS)
        assert getattr(ms, f"percentile_rank_{suffix}") == pytest.approx(
            exp_pct if pct_from_bulk else 0.5, abs=ABS
        ), (name, suffix)
        assert getattr(ms, f"combined_score_{suffix}") == pytest.approx(
            _combined(_sigmoid(exp_z), ai), abs=ABS
        ), (name, suffix)


def _primary(name: str) -> tuple[tuple[float, float, float, str], float, float]:
    """Legacy columns follow the primary type: rent when the row has a rent price."""
    if name in RENT:
        return RENT[name], RENT_MEAN, RENT_MEDIAN
    return SALE[name], SALE_MEAN, SALE_MEDIAN


@pytest.mark.integration
class TestBulkRecalculationLock:
    def test_every_stat_column_matches_the_hand_computed_values(self, db_session):
        props = _seed(db_session)

        count = compute_neighborhood_stats(db_session, COHORT)
        db_session.commit()

        assert count == 6
        for name in NAMES:
            ms = _metrics(db_session, props[name])
            ai = D_AI_SCORE if name == "D" else 0.0
            (ppm, z, pct, band), mean, median = _primary(name)

            assert ms.ai_score == pytest.approx(ai), name
            assert ms.price_per_m2 == pytest.approx(ppm, abs=ABS), name
            assert ms.neighborhood_mean == pytest.approx(mean, abs=ABS), name
            assert ms.neighborhood_median == pytest.approx(median, abs=ABS), name
            assert ms.z_score == pytest.approx(z, abs=ABS), name
            assert ms.stat_score == pytest.approx(_sigmoid(z), abs=ABS), name
            assert ms.percentile_rank == pytest.approx(pct, abs=ABS), name
            assert ms.combined_score == pytest.approx(_combined(_sigmoid(z), ai), abs=ABS), name
            assert ms.meta == {"stat_analysis": {"category": band, "reasoning": ""}}, name
            _assert_type_columns(ms, name, ai=ai, pct_from_bulk=True)

        # The other cohort was filtered out by the neighbourhood key.
        assert (
            db_session.query(MetricsScoring)
            .filter_by(property_id=props["outsider"].id)
            .one_or_none()
            is None
        )

    def test_unfiltered_run_keeps_cohorts_apart(self, db_session):
        props = _seed(db_session)

        count = compute_neighborhood_stats(db_session)
        db_session.commit()

        assert count == 7
        outsider = _metrics(db_session, props["outsider"])
        # Alone in its cohort: mean is its own price/m², stddev NULL -> z 0.
        assert outsider.price_per_m2_rent == pytest.approx(90.0)
        assert outsider.neighborhood_mean_rent == pytest.approx(90.0)
        assert outsider.z_score_rent == pytest.approx(0.0)
        assert outsider.stat_score_rent == pytest.approx(0.5)
        # LockCohort is unaffected by the outsider's 90 R$/m².
        r1 = _metrics(db_session, props["R1"])
        assert r1.neighborhood_mean_rent == pytest.approx(RENT_MEAN, abs=ABS)
        assert r1.z_score_rent == pytest.approx(RENT["R1"][1], abs=ABS)


@pytest.mark.integration
class TestCachedCohortStatsLock:
    def test_rent_and_sale_cohort_stats(self, db_session, real_redis):
        _seed(db_session)

        rent = get_neighborhood_stats_cached(db_session, COHORT, listing_type="rent")
        sale = get_neighborhood_stats_cached(db_session, COHORT, listing_type="sale")

        assert rent["count"] == 4
        assert rent["mean"] == pytest.approx(RENT_MEAN, abs=ABS)
        assert rent["median"] == pytest.approx(RENT_MEDIAN, abs=ABS)
        assert rent["stddev"] == pytest.approx(RENT_STDDEV, abs=ABS)
        assert sale["count"] == 3
        assert sale["mean"] == pytest.approx(SALE_MEAN, abs=ABS)
        assert sale["median"] == pytest.approx(SALE_MEDIAN, abs=ABS)
        assert sale["stddev"] == pytest.approx(SALE_STDDEV, abs=ABS)


@pytest.mark.integration
class TestSinglePropertyLock:
    def test_every_row_scores_like_the_bulk_path_with_a_neutral_percentile(
        self, db_session, real_redis
    ):
        props = _seed(db_session)

        for name in NAMES:
            score_single_property(db_session, str(props[name].id))
        db_session.commit()

        for name in NAMES:
            ms = _metrics(db_session, props[name])
            ai = D_AI_SCORE if name == "D" else 0.0
            (ppm, z, _pct, band), mean, median = _primary(name)

            assert ms.ai_score == pytest.approx(ai), name
            assert ms.price_per_m2 == pytest.approx(ppm, abs=ABS), name
            assert ms.neighborhood_mean == pytest.approx(mean, abs=ABS), name
            assert ms.neighborhood_median == pytest.approx(median, abs=ABS), name
            assert ms.z_score == pytest.approx(z, abs=ABS), name
            assert ms.stat_score == pytest.approx(_sigmoid(z), abs=ABS), name
            assert ms.combined_score == pytest.approx(_combined(_sigmoid(z), ai), abs=ABS), name
            assert ms.meta == {"stat_analysis": {"category": band, "reasoning": ""}}, name
            if name == "D":
                # Update path: the legacy percentile is left as it was (unset).
                assert ms.percentile_rank is None
            else:
                # Insert path: neutral percentile until the next bulk run.
                assert ms.percentile_rank == pytest.approx(0.5), name
            _assert_type_columns(ms, name, ai=ai, pct_from_bulk=False)

    def test_property_without_a_usable_price_is_left_untouched(self, db_session, real_redis):
        prop = _make_property(db_session, price=0)
        db_session.commit()

        score_single_property(db_session, str(prop.id))
        db_session.commit()

        assert db_session.query(MetricsScoring).filter_by(property_id=prop.id).one_or_none() is None
