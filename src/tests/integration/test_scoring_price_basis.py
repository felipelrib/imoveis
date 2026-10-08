"""One cohort price basis for rent (Story 1.3, AD-3) on a real Postgres.

A rent Listing contributes its fee-exclusive ``rent_monthly`` when it has one
and its headline ``price`` otherwise; ``metrics_scoring.price_basis`` records
which one produced the row's rent price/m². Covers the bulk path, the cached
cohort stats, the single-property path, the SQL relation against its Python
mirror, and the migration.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from adapters.db.models import MetricsScoring, Property, PropertyListing
from adapters.metrics.scoring import (
    compute_neighborhood_stats,
    get_neighborhood_stats_cached,
    score_single_property,
)
from core.price_basis import (
    COHORT_PRICE_FOR_TYPE_SQL,
    COHORT_PRICE_SQL,
    property_cohort_prices,
)
from tests.db_isolation import assert_wipe_safe_database_url
from tests.env_helpers import get_redis_url
from tests.redis_isolation import assert_wipe_safe_redis_url

REPO_ROOT = Path(__file__).resolve().parents[3]
DOWN_REVISION = "c4d5e6f7a8b9"
PRICE_BASIS_CHECK = "ck_metrics_scoring_price_basis"

RENT_MONTHLY = "rent_monthly"
HEADLINE = "headline"

# The I/O matrix, one Property per scenario, each alone in its own cohort.
# Listings: (listing_type, price, rent_monthly, active).
# Expected: (price_per_m2_rent, price_per_m2_sale, price_basis).
SCENARIOS: dict[str, tuple[list[tuple], float | None, tuple]] = {
    # name: (listings, legacy properties.price or None, expected)
    "unbundled_rent": ([("rent", 3800, 3000, True)], None, (30.0, None, RENT_MONTHLY)),
    "no_rent_monthly": ([("rent", 3500, None, True)], None, (35.0, None, HEADLINE)),
    "zero_rent_monthly": ([("rent", 3500, 0, True)], None, (35.0, None, HEADLINE)),
    "negative_rent_monthly": ([("rent", 3500, -10, True)], None, (35.0, None, HEADLINE)),
    "two_listings_both_rent": (
        [("rent", 3900, 3000, True), ("rent", 4100, 3200, True)],
        None,
        (30.0, None, RENT_MONTHLY),
    ),
    "mixed_headline_lower": (
        [("rent", 3800, 3000, True), ("rent", 2500, None, True)],
        None,
        (25.0, None, HEADLINE),
    ),
    "mixed_tie": (
        [("rent", 3800, 3000, True), ("rent", 3000, None, True)],
        None,
        (30.0, None, RENT_MONTHLY),
    ),
    "mixed_rent_lower": (
        [("rent", 3800, 3000, True), ("rent", 3500, None, True)],
        None,
        (30.0, None, RENT_MONTHLY),
    ),
    "inactive_holds_the_rent": (
        [("rent", 1800, 1000, False), ("rent", 3500, None, True)],
        None,
        (35.0, None, HEADLINE),
    ),
    "sale_only": ([("sale", 500_000, None, True)], None, (None, 5000.0, HEADLINE)),
    "dual": (
        [("rent", 3800, 3000, True), ("sale", 500_000, None, True)],
        None,
        (30.0, 5000.0, RENT_MONTHLY),
    ),
    "legacy_no_listings": ([], 4000, (40.0, None, HEADLINE)),
}


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


def _make_property(session, *, cohort: str, price: float = 9_999) -> Property:
    prop = Property(
        platform="test",
        platform_id=f"p-{uuid4().hex[:12]}",
        title="Price basis fixture",
        price=price,
        area_m2=100.0,
        props_json={"neighborhood": cohort},
        active=True,
    )
    session.add(prop)
    session.flush()
    return prop


def _add_listing(
    session,
    prop: Property,
    *,
    listing_type: str = "rent",
    price: float,
    rent_monthly: float | None = None,
    active: bool = True,
    platform: str = "test",
) -> PropertyListing:
    listing = PropertyListing(
        property_id=prop.id,
        platform=platform,
        platform_listing_id=f"l-{uuid4().hex[:12]}",
        listing_type=listing_type,
        price=price,
        rent_monthly=rent_monthly,
        currency="BRL",
        url=f"https://example.test/{uuid4().hex[:8]}",
        active=active,
    )
    session.add(listing)
    return listing


def _seed_scenarios(session) -> dict[str, Property]:
    props: dict[str, Property] = {}
    for name, (listings, legacy_price, _expected) in SCENARIOS.items():
        prop = _make_property(
            session,
            cohort=f"solo-{name}",
            price=legacy_price if legacy_price is not None else 9_999,
        )
        for listing_type, price, rent_monthly, active in listings:
            _add_listing(
                session,
                prop,
                listing_type=listing_type,
                price=price,
                rent_monthly=rent_monthly,
                active=active,
            )
        props[name] = prop
    session.commit()
    return props


def _metrics(session, prop: Property) -> MetricsScoring:
    session.expire_all()
    return session.query(MetricsScoring).filter_by(property_id=prop.id).one()


def _assert_scenarios(session, props: dict[str, Property]) -> None:
    for name, (_listings, _legacy, (ppm_rent, ppm_sale, basis)) in SCENARIOS.items():
        ms = _metrics(session, props[name])
        assert ms.price_per_m2_rent == (pytest.approx(ppm_rent) if ppm_rent else None), name
        assert ms.price_per_m2_sale == (pytest.approx(ppm_sale) if ppm_sale else None), name
        assert ms.price_basis == basis, name
        # Legacy columns follow the primary type (rent preferred).
        assert ms.price_per_m2 == pytest.approx(ppm_rent if ppm_rent else ppm_sale), name


@pytest.mark.integration
class TestMatrixThroughBothPaths:
    def test_bulk_path(self, db_session):
        props = _seed_scenarios(db_session)

        count = compute_neighborhood_stats(db_session)
        db_session.commit()

        assert count == len(SCENARIOS)
        _assert_scenarios(db_session, props)

    def test_single_property_path_matches_the_bulk_path(self, db_session, real_redis):
        props = _seed_scenarios(db_session)

        for prop in props.values():
            score_single_property(db_session, str(prop.id))
        db_session.commit()

        _assert_scenarios(db_session, props)


@pytest.mark.integration
class TestStampFollowsRecalculation:
    """The stamp is rewritten on update, not only on insert."""

    def test_bulk_update_path_moves_the_stamp_both_ways(self, db_session):
        prop = _make_property(db_session, cohort="restamp-bulk")
        listing = _add_listing(db_session, prop, price=3800)
        db_session.commit()

        compute_neighborhood_stats(db_session)
        db_session.commit()
        assert _metrics(db_session, prop).price_basis == HEADLINE
        assert _metrics(db_session, prop).price_per_m2_rent == pytest.approx(38.0)

        listing.rent_monthly = 3000
        db_session.commit()
        compute_neighborhood_stats(db_session)
        db_session.commit()
        assert _metrics(db_session, prop).price_basis == RENT_MONTHLY
        assert _metrics(db_session, prop).price_per_m2_rent == pytest.approx(30.0)

        listing.rent_monthly = None
        db_session.commit()
        compute_neighborhood_stats(db_session)
        db_session.commit()
        assert _metrics(db_session, prop).price_basis == HEADLINE
        assert _metrics(db_session, prop).price_per_m2_rent == pytest.approx(38.0)

    def test_single_update_path_moves_the_stamp(self, db_session, real_redis):
        prop = _make_property(db_session, cohort="restamp-single")
        listing = _add_listing(db_session, prop, price=3800)
        db_session.commit()

        score_single_property(db_session, str(prop.id))
        db_session.commit()
        assert _metrics(db_session, prop).price_basis == HEADLINE

        listing.rent_monthly = 3000
        db_session.commit()
        real_redis.flushdb()
        score_single_property(db_session, str(prop.id))
        db_session.commit()
        ms = _metrics(db_session, prop)
        assert ms.price_basis == RENT_MONTHLY
        assert ms.price_per_m2_rent == pytest.approx(30.0)

    def test_losing_the_rent_listing_resets_the_stamp_on_both_paths(self, db_session, real_redis):
        prop = _make_property(db_session, cohort="restamp-lost-rent")
        rent = _add_listing(db_session, prop, price=3800, rent_monthly=3000)
        _add_listing(db_session, prop, listing_type="sale", price=500_000)
        db_session.commit()

        for rescore in (
            lambda: compute_neighborhood_stats(db_session),
            lambda: score_single_property(db_session, str(prop.id)),
        ):
            rent.active = True
            db_session.commit()
            compute_neighborhood_stats(db_session)
            db_session.commit()
            assert _metrics(db_session, prop).price_basis == RENT_MONTHLY

            rent.active = False
            db_session.commit()
            real_redis.flushdb()
            rescore()
            db_session.commit()
            ms = _metrics(db_session, prop)
            assert ms.price_basis == HEADLINE
            assert ms.price_per_m2_rent is None
            assert ms.price_per_m2_sale == pytest.approx(5000.0)

    def test_no_usable_price_leaves_the_row_and_its_stamp_alone(self, db_session, real_redis):
        prop = _make_property(db_session, cohort="no-price", price=0)
        db_session.add(
            MetricsScoring(
                property_id=prop.id,
                price_per_m2_rent=30.0,
                stat_score_rent=0.7,
                price_basis=RENT_MONTHLY,
            )
        )
        db_session.commit()

        count = compute_neighborhood_stats(db_session)
        score_single_property(db_session, str(prop.id))
        db_session.commit()

        assert count == 0
        ms = _metrics(db_session, prop)
        assert ms.price_basis == RENT_MONTHLY
        assert ms.price_per_m2_rent == pytest.approx(30.0)
        assert ms.stat_score_rent == pytest.approx(0.7)


@pytest.mark.integration
class TestMixedBasisCohort:
    """Both bases share one cohort's statistics; nothing is excluded or imputed."""

    COHORT = "MixedBasisCohort"

    def _seed(self, session) -> list[Property]:
        p1 = _make_property(session, cohort=self.COHORT)
        _add_listing(session, p1, price=3800, rent_monthly=3000)
        p2 = _make_property(session, cohort=self.COHORT)
        _add_listing(session, p2, price=4000, rent_monthly=4000)
        p3 = _make_property(session, cohort=self.COHORT)
        _add_listing(session, p3, price=5000)
        session.commit()
        return [p1, p2, p3]

    def test_bulk_statistics_and_stamps(self, db_session):
        props = self._seed(db_session)

        count = compute_neighborhood_stats(db_session, self.COHORT)
        db_session.commit()

        assert count == 3
        rows = [_metrics(db_session, prop) for prop in props]
        assert [ms.price_per_m2_rent for ms in rows] == pytest.approx([30.0, 40.0, 50.0])
        assert [ms.price_basis for ms in rows] == [RENT_MONTHLY, RENT_MONTHLY, HEADLINE]
        for ms in rows:
            assert ms.neighborhood_mean_rent == pytest.approx(40.0)
            assert ms.neighborhood_median_rent == pytest.approx(40.0)
        # Sample stddev of 30 / 40 / 50 is 10.
        assert [ms.z_score_rent for ms in rows] == pytest.approx([-1.0, 0.0, 1.0])
        assert [ms.percentile_rank_rent for ms in rows] == pytest.approx([0.0, 0.5, 1.0])
        assert rows[0].stat_score_rent > rows[1].stat_score_rent > rows[2].stat_score_rent
        assert rows[1].stat_score_rent == pytest.approx(0.5)

    def test_cached_cohort_stats_use_the_same_prices(self, db_session, real_redis):
        self._seed(db_session)

        stats = get_neighborhood_stats_cached(db_session, self.COHORT, listing_type="rent")

        assert stats["count"] == 3
        assert stats["mean"] == pytest.approx(40.0)
        assert stats["median"] == pytest.approx(40.0)
        assert stats["stddev"] == pytest.approx(10.0)

    def test_single_property_path_agrees_with_the_bulk_path(self, db_session, real_redis):
        props = self._seed(db_session)

        compute_neighborhood_stats(db_session, self.COHORT)
        db_session.commit()
        bulk = [
            (ms.price_per_m2_rent, ms.z_score_rent, ms.stat_score_rent, ms.price_basis)
            for ms in (_metrics(db_session, prop) for prop in props)
        ]

        for prop in props:
            score_single_property(db_session, str(prop.id))
        db_session.commit()
        single = [
            (ms.price_per_m2_rent, ms.z_score_rent, ms.stat_score_rent, ms.price_basis)
            for ms in (_metrics(db_session, prop) for prop in props)
        ]

        for (b_ppm, b_z, b_stat, b_basis), (s_ppm, s_z, s_stat, s_basis) in zip(bulk, single):
            assert s_ppm == pytest.approx(b_ppm)
            assert s_z == pytest.approx(b_z)
            assert s_stat == pytest.approx(b_stat)
            assert s_basis == b_basis


@pytest.mark.integration
class TestFeeInclusiveVsFeeExclusivePeers:
    """AC 3: the same unbundled rent on two platforms scores the same.

    QuintoAndar's headline folds the fees in (3800), ZapImóveis' does not
    (3000). Scored on the headline they were 38 vs 30 R$/m².
    """

    def test_same_rent_same_price_z_and_stat_score(self, db_session):
        cohort = "PeerCohort"
        quintoandar = _make_property(db_session, cohort=cohort)
        _add_listing(
            db_session, quintoandar, price=3800, rent_monthly=3000, platform="quintoandar"
        )
        zapimoveis = _make_property(db_session, cohort=cohort)
        _add_listing(db_session, zapimoveis, price=3000, rent_monthly=3000, platform="zapimoveis")
        dearer = _make_property(db_session, cohort=cohort)
        _add_listing(db_session, dearer, price=4500, rent_monthly=4500, platform="zapimoveis")
        db_session.commit()

        compute_neighborhood_stats(db_session, cohort)
        db_session.commit()

        qa, zap = _metrics(db_session, quintoandar), _metrics(db_session, zapimoveis)
        assert qa.price_per_m2_rent == pytest.approx(30.0)
        assert zap.price_per_m2_rent == pytest.approx(30.0)
        assert qa.z_score_rent == pytest.approx(zap.z_score_rent)
        assert qa.z_score_rent < 0  # a real spread, not the stddev-0 shortcut
        assert qa.stat_score_rent == pytest.approx(zap.stat_score_rent)
        assert qa.percentile_rank_rent == pytest.approx(zap.percentile_rank_rent)
        assert qa.price_basis == zap.price_basis == RENT_MONTHLY


@pytest.mark.integration
class TestSaleCohortUnchanged:
    def test_sale_values_ignore_the_rent_basis(self, db_session):
        """Sale 4000 / 5000 / 7500: mean 5500, median 5000, stddev 1802.7756."""
        cohort = "SaleCohort"
        cheap = _make_property(db_session, cohort=cohort)
        _add_listing(db_session, cheap, listing_type="sale", price=400_000)
        dual = _make_property(db_session, cohort=cohort)
        _add_listing(db_session, dual, listing_type="sale", price=500_000)
        _add_listing(db_session, dual, price=3800, rent_monthly=3000)
        dear = _make_property(db_session, cohort=cohort)
        # A stray rent figure on a sale row must never reach a sale cohort.
        _add_listing(db_session, dear, listing_type="sale", price=750_000, rent_monthly=3000)
        db_session.commit()

        compute_neighborhood_stats(db_session, cohort)
        db_session.commit()

        rows = [_metrics(db_session, prop) for prop in (cheap, dual, dear)]
        assert [ms.price_per_m2_sale for ms in rows] == pytest.approx([4000.0, 5000.0, 7500.0])
        for ms in rows:
            assert ms.neighborhood_mean_sale == pytest.approx(5500.0)
            assert ms.neighborhood_median_sale == pytest.approx(5000.0)
        assert [ms.z_score_sale for ms in rows] == pytest.approx(
            [-0.8320502943, -0.2773500981, 1.1094003925]
        )
        assert [ms.percentile_rank_sale for ms in rows] == pytest.approx([0.0, 0.5, 1.0])
        assert [ms.price_basis for ms in rows] == [HEADLINE, RENT_MONTHLY, HEADLINE]


@pytest.mark.integration
class TestSqlRelationMatchesPythonMirror:
    """The two expressions of the rule in core/price_basis.py agree on the same rows."""

    def _seed(self, session) -> None:
        _seed_scenarios(session)
        # Rows the matrix does not hold: an unpriced Listing, a rent figure
        # above the headline, a stray rent on a sale row, an inactive Property.
        extra = _make_property(session, cohort="mirror-extra")
        _add_listing(session, extra, price=0, rent_monthly=2000)
        _add_listing(session, extra, price=3000, rent_monthly=3200)
        _add_listing(session, extra, listing_type="sale", price=450_000, rent_monthly=2500)
        _add_listing(session, extra, listing_type="sale", price=440_000, active=False)
        only_inactive = _make_property(session, cohort="mirror-extra")
        _add_listing(session, only_inactive, price=2000, rent_monthly=1500, active=False)
        session.commit()

    @staticmethod
    def _python(session) -> dict[tuple, tuple]:
        by_property: dict = defaultdict(list)
        for listing in session.query(PropertyListing).all():
            by_property[listing.property_id].append(
                {
                    "listing_type": listing.listing_type,
                    "price": listing.price,
                    "rent_monthly": listing.rent_monthly,
                    "active": listing.active,
                }
            )
        return {
            (property_id, listing_type): (cohort.price, cohort.price_basis)
            for property_id, listings in by_property.items()
            for listing_type, cohort in property_cohort_prices(listings).items()
        }

    def test_relation_equals_mirror(self, db_session):
        self._seed(db_session)

        rows = db_session.execute(
            text(
                "SELECT property_id, listing_type, price, price_basis FROM ("
                + COHORT_PRICE_SQL
                + ") AS cohort_price"
            )
        ).fetchall()
        sql = {(row[0], row[1]): (float(row[2]), row[3]) for row in rows}

        assert len(sql) == len(rows)  # one row per Property x listing type
        assert sql == self._python(db_session)
        assert len(sql) >= len(SCENARIOS)

    @pytest.mark.parametrize("listing_type", ["rent", "sale"])
    def test_per_type_relation_is_the_same_rows_for_that_type(self, db_session, listing_type):
        self._seed(db_session)

        rows = db_session.execute(
            text(
                "SELECT property_id, listing_type, price, price_basis FROM ("
                + COHORT_PRICE_FOR_TYPE_SQL
                + ") AS cohort_price"
            ),
            {"lt": listing_type},
        ).fetchall()
        sql = {(row[0], row[1]): (float(row[2]), row[3]) for row in rows}

        expected = {
            key: value for key, value in self._python(db_session).items() if key[1] == listing_type
        }
        assert sql == expected
        assert sql


@pytest.mark.integration
class TestPriceBasisColumn:
    def test_default_is_headline(self, db_session):
        """A row written without the stamp (tasks.py enrichment insert) is headline."""
        prop = _make_property(db_session, cohort="column-default")
        db_session.add(MetricsScoring(property_id=prop.id, ai_score=0.3))
        db_session.commit()

        assert _metrics(db_session, prop).price_basis == HEADLINE

    def test_check_rejects_a_value_outside_the_vocabulary(self, db_session):
        prop = _make_property(db_session, cohort="column-check")
        db_session.add(MetricsScoring(property_id=prop.id, price_basis="total_monthly_cost"))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_null_is_rejected(self, db_session):
        prop = _make_property(db_session, cohort="column-null")
        db_session.add(MetricsScoring(property_id=prop.id))
        db_session.commit()
        with pytest.raises(IntegrityError):
            db_session.execute(
                text("UPDATE metrics_scoring SET price_basis = NULL WHERE property_id = :pid"),
                {"pid": prop.id},
            )
        db_session.rollback()


class TestPriceBasisMigration:
    """AC 2: the migration applies and reverses on a real Postgres."""

    @staticmethod
    def _alembic(*args: str) -> subprocess.CompletedProcess:
        # A subprocess keeps alembic's logging reconfiguration out of the test run.
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )

    @staticmethod
    def _has_column(engine) -> bool:
        with engine.connect() as conn:
            return bool(
                conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'metrics_scoring' AND column_name = 'price_basis'"
                    )
                ).scalar()
            )

    @staticmethod
    def _has_check(engine) -> bool:
        with engine.connect() as conn:
            return bool(
                conn.execute(
                    text("SELECT 1 FROM pg_constraint WHERE conname = :name"),
                    {"name": PRICE_BASIS_CHECK},
                ).scalar()
            )

    def test_downgrade_then_upgrade_round_trips_and_existing_rows_read_headline(self):
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            pytest.skip("DATABASE_URL not set — run through scripts/agent/validate.py")
        assert_wipe_safe_database_url(database_url)
        engine = create_engine(database_url, poolclass=NullPool)
        row_id = None
        try:
            assert self._has_column(engine)
            try:
                # Explicit target: stays a real round trip after later migrations land.
                down = self._alembic("downgrade", DOWN_REVISION)
                assert down.returncode == 0, down.stderr
                with engine.connect() as conn:
                    assert (
                        conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
                        == DOWN_REVISION
                    )
                assert not self._has_column(engine)
                assert not self._has_check(engine)
                # A row written before this story.
                with engine.begin() as conn:
                    row_id = conn.execute(
                        text("INSERT INTO metrics_scoring (stat_score) VALUES (0.5) RETURNING id")
                    ).scalar()
            finally:
                up = self._alembic("upgrade", "head")
            assert up.returncode == 0, up.stderr
            assert self._has_column(engine)
            assert self._has_check(engine)
            with engine.connect() as conn:
                stamped = conn.execute(
                    text("SELECT price_basis FROM metrics_scoring WHERE id = :id"),
                    {"id": row_id},
                ).scalar()
            assert stamped == HEADLINE
        finally:
            if row_id is not None:
                with engine.begin() as conn:
                    conn.execute(
                        text("DELETE FROM metrics_scoring WHERE id = :id"), {"id": row_id}
                    )
            engine.dispose()

    def test_model_matches_the_migrated_schema(self):
        """No model/migration drift on ``metrics_scoring`` (column, default, nullability)."""
        from adapters.db.models import Base
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext

        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            pytest.skip("DATABASE_URL not set — run through scripts/agent/validate.py")

        def only_metrics(name, type_, *_):
            return type_ != "table" or name == "metrics_scoring"

        engine = create_engine(database_url, poolclass=NullPool)
        try:
            with engine.connect() as conn:
                context = MigrationContext.configure(
                    conn,
                    opts={
                        "include_name": lambda name, type_, _parents: only_metrics(name, type_),
                        "include_object": lambda _obj, name, type_, *_: only_metrics(name, type_),
                        "compare_server_default": True,
                    },
                )
                diff = compare_metadata(context, Base.metadata)
        finally:
            engine.dispose()

        drift = [entry for entry in diff if "metrics_scoring" in repr(entry)]
        assert drift == [], drift
