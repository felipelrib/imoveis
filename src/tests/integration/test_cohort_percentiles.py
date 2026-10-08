"""Cohort price/m² percentiles (Story 1.6, FR-30) on a real Postgres.

The scoring stage stores, per Property and listing type, the share of its
city x neighbourhood x listing-type cohort priced at or below it, on the
Story 1.3 price basis, with the cohort size and an evaluation timestamp.
Covers the I/O matrix through the bulk stage, the single-property path
against the bulk stage, the SQL counts against the Python reference,
clearing, the config-owned minimum, the CHECKs, the migration and the
single-writer rule.

Unless a test says otherwise the minimum cohort size is 3 and every member is
active with ``area_m2`` 100 in ``Savassi``, ``Belo Horizonte``.
"""

from __future__ import annotations

import ast
import inspect
import os
import random
import subprocess
import sys
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from adapters.db.models import MetricsScoring, Neighborhood, Property, PropertyListing
from adapters.metrics import scoring
from adapters.metrics.scoring import compute_neighborhood_stats, score_single_property
from core.cohort_percentile import cohort_percentiles
from infra.config import get_config
from tests.db_isolation import assert_wipe_safe_database_url
from tests.env_helpers import get_redis_url
from tests.redis_isolation import assert_wipe_safe_redis_url

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
REVISION = "e6f7a8b9c0d1"
DOWN_REVISION = "d5e6f7a8b9c0"

MIN_ENV = "IMOVEIS_SCORING__PERCENTILE_MIN_COHORT_SIZE"
CITY = "Belo Horizonte"
NEIGHBOURHOOD = "Savassi"

PERCENTILE_COLUMNS = (
    "price_per_m2_percentile_rent",
    "price_per_m2_percentile_sale",
    "percentile_cohort_size_rent",
    "percentile_cohort_size_sale",
    "percentile_evaluated_at",
)
CHECKS = (
    "ck_metrics_scoring_price_per_m2_percentile_rent",
    "ck_metrics_scoring_price_per_m2_percentile_sale",
    "ck_metrics_scoring_percentile_cohort_size_rent",
    "ck_metrics_scoring_percentile_cohort_size_sale",
)


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


def _set_minimum(monkeypatch, value: int) -> None:
    """Change ``scoring.percentile_min_cohort_size`` the way a host would."""
    monkeypatch.setenv(MIN_ENV, str(value))
    get_config.cache_clear()


@pytest.fixture(autouse=True)
def minimum_of_three(monkeypatch):
    _set_minimum(monkeypatch, 3)
    yield
    get_config.cache_clear()


def _make_property(
    session,
    *,
    neighbourhood: str | None = NEIGHBOURHOOD,
    city: str | None = CITY,
    area_m2: float | None = 100.0,
    active: bool = True,
    price: float = 9_999,
    neighborhood_id=None,
    props_json: dict | None | str = "build",
) -> Property:
    if props_json == "build":
        props_json = {}
        if neighbourhood is not None:
            props_json["neighborhood"] = neighbourhood
        if city is not None:
            props_json["city"] = city
    prop = Property(
        platform="test",
        platform_id=f"p-{uuid4().hex[:12]}",
        title="Cohort percentile fixture",
        price=price,
        area_m2=area_m2,
        neighborhood_id=neighborhood_id,
        props_json=props_json,
        active=active,
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
) -> PropertyListing:
    listing = PropertyListing(
        property_id=prop.id,
        platform="test",
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


def _rent(session, price_per_m2: float, **property_kwargs) -> Property:
    """A rent member at ``price_per_m2`` (area 100 unless overridden)."""
    prop = _make_property(session, **property_kwargs)
    _add_listing(session, prop, price=price_per_m2 * 100)
    return prop


def _sale(session, price_per_m2: float, **property_kwargs) -> Property:
    prop = _make_property(session, **property_kwargs)
    _add_listing(session, prop, listing_type="sale", price=price_per_m2 * 100)
    return prop


def _metrics(session, prop: Property) -> MetricsScoring:
    session.expire_all()
    return session.query(MetricsScoring).filter_by(property_id=prop.id).one()


def _stored(session, prop: Property) -> tuple:
    """``(percentile_rent, size_rent, percentile_sale, size_sale)``."""
    ms = _metrics(session, prop)
    return (
        ms.price_per_m2_percentile_rent,
        ms.percentile_cohort_size_rent,
        ms.price_per_m2_percentile_sale,
        ms.percentile_cohort_size_sale,
    )


def _bulk(session, key: str | None = None) -> int:
    count = compute_neighborhood_stats(session, key)
    session.commit()
    return count


def _rent_percentiles(session, props) -> list:
    return [_metrics(session, prop).price_per_m2_percentile_rent for prop in props]


@pytest.mark.integration
class TestMatrixThroughTheBulkStage:
    def test_distinct_prices(self, db_session):
        props = [_rent(db_session, ppm) for ppm in (30, 40, 50, 70)]
        db_session.commit()

        _bulk(db_session)

        assert _rent_percentiles(db_session, props) == [0.25, 0.5, 0.75, 1.0]
        for prop in props:
            ms = _metrics(db_session, prop)
            assert ms.percentile_cohort_size_rent == 4
            assert ms.price_per_m2_percentile_sale is None
            assert ms.percentile_cohort_size_sale is None
            assert ms.percentile_evaluated_at is not None

    def test_ties_share_the_inclusive_count(self, db_session):
        props = [_rent(db_session, ppm) for ppm in (30, 40, 40, 50)]
        db_session.commit()

        _bulk(db_session)

        assert _rent_percentiles(db_session, props) == [0.25, 0.75, 0.75, 1.0]

    def test_all_tied(self, db_session):
        props = [_rent(db_session, 40) for _ in range(3)]
        db_session.commit()

        _bulk(db_session)

        assert _rent_percentiles(db_session, props) == [1.0, 1.0, 1.0]

    def test_exactly_at_the_minimum_values_are_stored(self, db_session):
        props = [_rent(db_session, ppm) for ppm in (30, 40, 50)]
        db_session.commit()

        _bulk(db_session)

        assert _rent_percentiles(db_session, props) == pytest.approx([1 / 3, 2 / 3, 1.0])
        assert _metrics(db_session, props[0]).percentile_cohort_size_rent == 3

    def test_one_below_the_minimum_is_null_with_its_size(self, db_session):
        props = [_rent(db_session, ppm) for ppm in (30, 40)]
        db_session.commit()

        _bulk(db_session)

        for prop in props:
            ms = _metrics(db_session, prop)
            assert ms.price_per_m2_percentile_rent is None
            assert ms.percentile_cohort_size_rent == 2
            assert ms.percentile_evaluated_at is not None

    def test_single_listing_cohort(self, db_session, monkeypatch):
        _set_minimum(monkeypatch, 2)
        prop = _rent(db_session, 30)
        db_session.commit()

        _bulk(db_session)

        assert _stored(db_session, prop) == (None, 1, None, None)
        # The legacy rank of the same row is still PERCENT_RANK's 0.
        assert _metrics(db_session, prop).percentile_rank_rent == pytest.approx(0.0)

    def test_dual_property_has_one_percentile_per_type(self, db_session):
        dual = _make_property(db_session)
        _add_listing(db_session, dual, price=4_000)
        _add_listing(db_session, dual, listing_type="sale", price=500_000)
        _rent(db_session, 30)
        _rent(db_session, 50)
        sale_peer = _sale(db_session, 4_000)
        db_session.commit()

        _bulk(db_session)

        assert _stored(db_session, dual) == (pytest.approx(2 / 3), 3, None, 2)
        assert _stored(db_session, sale_peer) == (None, None, None, 2)

    @pytest.mark.parametrize("area_m2", [None, 0])
    def test_missing_area_clears_an_existing_row(self, db_session, area_m2):
        peers = [_rent(db_session, ppm) for ppm in (30, 40, 50)]
        subject = _rent(db_session, 60)
        db_session.commit()
        _bulk(db_session)
        assert _stored(db_session, subject) == (1.0, 4, None, None)
        # Age the first run's stamp: two runs can share one tick of a coarse clock.
        stamped = datetime(2000, 1, 1)
        db_session.execute(
            text("UPDATE metrics_scoring SET percentile_evaluated_at = :stamped"),
            {"stamped": stamped},
        )

        subject.area_m2 = area_m2
        db_session.commit()
        _bulk(db_session)

        assert _stored(db_session, subject) == (None, None, None, None)
        # The clearing statement stamps the row with its own run.
        assert _metrics(db_session, subject).percentile_evaluated_at > stamped
        # It no longer counts in the cohort it left.
        assert _rent_percentiles(db_session, peers) == pytest.approx([1 / 3, 2 / 3, 1.0])
        assert _metrics(db_session, peers[0]).percentile_cohort_size_rent == 3

    @pytest.mark.parametrize(
        "props_json",
        [None, {}, {"city": CITY}, {"neighborhood": "", "city": CITY}, {"neighborhood": "   "}],
        ids=["no-props", "empty-props", "no-label", "blank-label", "padding-only"],
    )
    def test_unassigned_neighbourhood_has_no_percentile(self, db_session, props_json):
        subjects = [_rent(db_session, ppm, props_json=props_json) for ppm in (30, 40, 50)]
        db_session.commit()

        _bulk(db_session)

        for prop in subjects:
            ms = _metrics(db_session, prop)
            assert _stored(db_session, prop) == (None, None, None, None)
            assert ms.percentile_evaluated_at is not None
            # The stat columns still come from the label cohort, as before.
            assert ms.neighborhood_mean_rent == pytest.approx(40.0)
            assert ms.stat_score_rent is not None
        assert _metrics(db_session, subjects[0]).percentile_rank_rent == pytest.approx(0.0)

    def test_same_label_in_two_cities_is_two_cohorts(self, db_session):
        bh = [_rent(db_session, ppm, neighbourhood="Centro") for ppm in (30, 50, 70)]
        contagem = [
            _rent(db_session, ppm, neighbourhood="Centro", city="Contagem")
            for ppm in (20, 40, 60, 80)
        ]
        db_session.commit()

        _bulk(db_session)

        assert _rent_percentiles(db_session, bh) == pytest.approx([1 / 3, 2 / 3, 1.0])
        assert _rent_percentiles(db_session, contagem) == [0.25, 0.5, 0.75, 1.0]
        assert _metrics(db_session, bh[0]).percentile_cohort_size_rent == 3
        assert _metrics(db_session, contagem[0]).percentile_cohort_size_rent == 4
        # The legacy rank still merges the two cities (7 rows, one label).
        assert _metrics(db_session, bh[0]).percentile_rank_rent == pytest.approx(1 / 6)

    def test_label_case_and_padding_are_one_cohort(self, db_session):
        props = [
            _rent(db_session, 30, neighbourhood="Savassi"),
            _rent(db_session, 40, neighbourhood=" savassi ", city="BELO HORIZONTE "),
            _rent(db_session, 50, neighbourhood="SAVASSI", city=" belo horizonte"),
        ]
        db_session.commit()

        _bulk(db_session)

        assert _rent_percentiles(db_session, props) == pytest.approx([1 / 3, 2 / 3, 1.0])

    def test_accent_and_whitespace_variants_are_one_cohort(self, db_session):
        props = [
            _rent(db_session, 30, neighbourhood="São Bento"),
            _rent(db_session, 40, neighbourhood="Sao Bento", city="Belo  Horizonte"),
            _rent(db_session, 50, neighbourhood="SÃO\tBENTO"),
            _rent(db_session, 60, neighbourhood="sa\u0303o   bento"),
        ]
        other = _rent(db_session, 10, neighbourhood="Santo Bento")
        db_session.commit()

        _bulk(db_session)

        assert _rent_percentiles(db_session, props) == [0.25, 0.5, 0.75, 1.0]
        assert _stored(db_session, other) == (None, 1, None, None)

    def test_missing_city_is_its_own_key(self, db_session):
        with_city = [_rent(db_session, ppm) for ppm in (30, 40, 50)]
        without_city = [_rent(db_session, ppm, city=None) for ppm in (35, 45)]
        db_session.commit()

        _bulk(db_session)

        assert _metrics(db_session, with_city[0]).percentile_cohort_size_rent == 3
        for prop in without_city:
            assert _stored(db_session, prop) == (None, 2, None, None)

    def test_rent_is_ranked_on_the_cohort_price_basis(self, db_session):
        """Headline 3800 with ``rent_monthly`` 3000 ranks at 30, not 38 R$/m²."""
        subject = _make_property(db_session)
        _add_listing(db_session, subject, price=3_800, rent_monthly=3_000)
        _rent(db_session, 35)
        _rent(db_session, 37)
        db_session.commit()

        _bulk(db_session)

        ms = _metrics(db_session, subject)
        assert ms.price_per_m2_rent == pytest.approx(30.0)
        assert ms.price_basis == "rent_monthly"
        assert ms.price_per_m2_percentile_rent == pytest.approx(1 / 3)

    def test_listing_less_legacy_property_is_not_a_member(self, db_session):
        members = [_rent(db_session, ppm) for ppm in (30, 40, 50)]
        legacy = _make_property(db_session, price=2_000)  # 20 R$/m², no Listing
        db_session.commit()

        _bulk(db_session)

        ms = _metrics(db_session, legacy)
        assert ms.price_per_m2_rent == pytest.approx(20.0)  # still scored on properties.price
        assert _stored(db_session, legacy) == (None, None, None, None)
        assert ms.percentile_evaluated_at is not None
        # Not counted: the cheapest member is still 1 of 3.
        assert _rent_percentiles(db_session, members) == pytest.approx([1 / 3, 2 / 3, 1.0])

    def test_inactive_property_or_listing_is_cleared_by_the_full_run(self, db_session):
        props = [_rent(db_session, ppm) for ppm in (30, 40, 50, 60, 70)]
        db_session.commit()
        _bulk(db_session)
        assert _rent_percentiles(db_session, props) == [0.2, 0.4, 0.6, 0.8, 1.0]

        props[0].active = False
        listing = db_session.query(PropertyListing).filter_by(property_id=props[1].id).one()
        listing.active = False
        db_session.commit()
        _bulk(db_session)

        assert _stored(db_session, props[0]) == (None, None, None, None)
        assert _stored(db_session, props[1]) == (None, None, None, None)
        assert _rent_percentiles(db_session, props[2:]) == pytest.approx([1 / 3, 2 / 3, 1.0])

    def test_row_never_evaluated_is_all_null(self, db_session):
        """The enrichment task inserts a bare row before the stage scores it."""
        prop = _rent(db_session, 30)
        db_session.add(MetricsScoring(property_id=prop.id, ai_score=0.4))
        db_session.commit()

        ms = _metrics(db_session, prop)
        for column in PERCENTILE_COLUMNS:
            assert getattr(ms, column) is None, column


@pytest.mark.integration
class TestCohortKeyWithSpatialAssignment:
    def test_fk_name_and_city_win_over_the_labels(self, db_session):
        nhood = Neighborhood(name="Savassi", city="Belo Horizonte", state="MG")
        db_session.add(nhood)
        db_session.flush()
        assigned = _rent(
            db_session, 30, neighbourhood="Some Other Label", city="Elsewhere",
            neighborhood_id=nhood.id,
        )
        assigned_no_props = _rent(db_session, 40, props_json=None, neighborhood_id=nhood.id)
        label_only = _rent(db_session, 50, neighbourhood="savassi", city="belo horizonte")
        other_label = _rent(db_session, 10, neighbourhood="Some Other Label", city="Elsewhere")
        db_session.commit()

        _bulk(db_session)

        assert _rent_percentiles(
            db_session, [assigned, assigned_no_props, label_only]
        ) == pytest.approx([1 / 3, 2 / 3, 1.0])
        assert _stored(db_session, other_label) == (None, 1, None, None)


@pytest.mark.integration
class TestRestrictedRun:
    def test_a_keyed_run_ranks_against_whole_cohorts_and_clears_nothing(self, db_session):
        centro_bh = [_rent(db_session, ppm, neighbourhood="Centro") for ppm in (30, 50, 70)]
        # Same cohort, another spelling: outside the label key of the run.
        variant = _rent(db_session, 10, neighbourhood=" centro ")
        savassi = [_rent(db_session, ppm) for ppm in (30, 40, 50)]
        db_session.commit()
        _bulk(db_session)
        savassi[0].active = False
        db_session.commit()
        db_session.query(MetricsScoring).filter(
            MetricsScoring.property_id.in_([p.id for p in centro_bh])
        ).update(
            {
                MetricsScoring.price_per_m2_percentile_rent: None,
                MetricsScoring.percentile_cohort_size_rent: None,
            },
            synchronize_session=False,
        )
        db_session.commit()

        count = _bulk(db_session, "Centro")

        assert count == 3
        # Ranked against the whole cohort of four, not the three keyed rows.
        assert _rent_percentiles(db_session, centro_bh) == [0.5, 0.75, 1.0]
        assert _metrics(db_session, centro_bh[0]).percentile_cohort_size_rent == 4
        assert _stored(db_session, variant) == (0.25, 4, None, None)
        # Outside the key: untouched, even the row that is no longer a member.
        assert _stored(db_session, savassi[0]) == (pytest.approx(1 / 3), 3, None, None)

        _bulk(db_session)
        assert _stored(db_session, savassi[0]) == (None, None, None, None)
        assert _stored(db_session, savassi[1]) == (None, 2, None, None)


@pytest.mark.integration
class TestMedianOncePerCohort:
    """The stat median comes from one GROUP BY joined back, not a subquery per row.

    Every older assertion on a bulk-written median runs a keyed call, where
    the statement holds a single cohort. The production caller runs unkeyed.
    """

    def test_unkeyed_run_gives_each_cohort_and_type_its_own_median(self, db_session):
        savassi = [_rent(db_session, ppm) for ppm in (30, 40, 50)]
        lourdes = [_rent(db_session, ppm, neighbourhood="Lourdes") for ppm in (60, 80, 100, 200)]
        savassi_sale = [_sale(db_session, ppm) for ppm in (5_000, 7_000)]
        lourdes_sale = [_sale(db_session, ppm, neighbourhood="Lourdes") for ppm in (9_000,)]
        dual = _rent(db_session, 300, neighbourhood="Centro")
        _add_listing(db_session, dual, listing_type="sale", price=1_000 * 100)
        unlabelled = [_rent(db_session, ppm, props_json=None) for ppm in (10, 20)]
        db_session.commit()

        assert _bulk(db_session) == 13

        def medians(prop):
            ms = _metrics(db_session, prop)
            return (ms.neighborhood_median, ms.neighborhood_median_rent, ms.neighborhood_median_sale)

        for prop in savassi:
            assert medians(prop) == (40.0, 40.0, None)
        # Even count: the mean of the two middle values.
        for prop in lourdes:
            assert medians(prop) == (90.0, 90.0, None)
        for prop in savassi_sale:
            assert medians(prop) == (6_000.0, None, 6_000.0)
        for prop in lourdes_sale:
            assert medians(prop) == (9_000.0, None, 9_000.0)
        # Rent is the primary type of a dual row; each type keeps its own median.
        assert medians(dual) == (300.0, 300.0, 1_000.0)
        # The Unknown stat cohort is a cohort like any other.
        for prop in unlabelled:
            assert medians(prop) == (15.0, 15.0, None)


def _seed_mixed_corpus(session) -> list[Property]:
    """Cohorts of several sizes, ties, both types, dual rows and non-members."""
    rng = random.Random(16)
    props: list[Property] = []
    for city in ("Belo Horizonte", "Contagem"):
        for label in ("Centro", "Savassi", "Lourdes"):
            for _ in range(rng.randint(1, 7)):
                prop = _make_property(
                    session,
                    neighbourhood=rng.choice([label, label.upper(), f" {label.lower()} "]),
                    city=city,
                    area_m2=rng.choice([50.0, 80.0, 100.0]),
                )
                kind = rng.choice(["rent", "sale", "dual"])
                if kind in ("rent", "dual"):
                    headline = rng.choice([2_000, 2_400, 3_000, 3_800])
                    _add_listing(
                        session,
                        prop,
                        price=headline,
                        rent_monthly=rng.choice([None, headline - 400]),
                    )
                if kind in ("sale", "dual"):
                    _add_listing(
                        session,
                        prop,
                        listing_type="sale",
                        price=rng.choice([300_000, 400_000, 500_000]),
                    )
                props.append(prop)
    # Non-members: no label, no area, no Listing, inactive Property.
    props.append(_rent(session, 30, props_json=None))
    props.append(_rent(session, 30, area_m2=None))
    props.append(_make_property(session, price=3_000))
    props.append(_rent(session, 30, active=False))
    session.commit()
    return props


@pytest.mark.integration
class TestSqlCountsAgainstThePythonReference:
    def test_stored_values_equal_the_whole_cohort_reference(self, db_session):
        props = _seed_mixed_corpus(db_session)
        _bulk(db_session)

        # Rebuild every cohort in Python from the same rows.
        from core.price_basis import property_cohort_prices

        cohorts: dict[tuple, list[tuple]] = defaultdict(list)
        for prop in props:
            labels = prop.props_json or {}
            label = (labels.get("neighborhood") or "").strip().lower()
            if not prop.active or not prop.area_m2 or not label:
                continue
            listings = [
                {
                    "listing_type": listing.listing_type,
                    "price": listing.price,
                    "rent_monthly": listing.rent_monthly,
                    "active": listing.active,
                }
                for listing in db_session.query(PropertyListing).filter_by(property_id=prop.id)
            ]
            for listing_type, cohort_price in property_cohort_prices(listings).items():
                key = (listing_type, (labels.get("city") or "").strip().lower(), label)
                cohorts[key].append((prop.id, cohort_price.price / prop.area_m2))

        expected: dict[tuple, tuple] = {}
        for (listing_type, _city, _label), members in cohorts.items():
            values = cohort_percentiles([ppm for _pid, ppm in members], 3)
            for (property_id, _ppm), value in zip(members, values):
                expected[(property_id, listing_type)] = (value, len(members))

        assert len(cohorts) >= 8
        assert any(size < 3 for _value, size in expected.values())
        assert any(value is not None for value, _size in expected.values())
        for prop in props:
            row = (
                db_session.query(MetricsScoring).filter_by(property_id=prop.id).one_or_none()
            )
            if row is None:
                assert (prop.id, "rent") not in expected and (prop.id, "sale") not in expected
                continue
            db_session.refresh(row)
            assert (
                row.price_per_m2_percentile_rent,
                row.percentile_cohort_size_rent,
            ) == expected.get((prop.id, "rent"), (None, None))
            assert (
                row.price_per_m2_percentile_sale,
                row.percentile_cohort_size_sale,
            ) == expected.get((prop.id, "sale"), (None, None))


@pytest.mark.integration
class TestSinglePropertyPathMatchesTheBulkStage:
    def test_same_percentile_and_size_on_the_same_rows(self, db_session, real_redis):
        props = _seed_mixed_corpus(db_session)
        _bulk(db_session)
        bulk = {
            prop.id: _stored(db_session, prop)
            for prop in props
            if db_session.query(MetricsScoring).filter_by(property_id=prop.id).count()
        }
        assert any(value[0] is not None for value in bulk.values())
        assert any(value[2] is not None for value in bulk.values())
        # Blank what the bulk stage wrote so the single path has to produce it.
        db_session.execute(
            text(
                "UPDATE metrics_scoring SET price_per_m2_percentile_rent = NULL, "
                "price_per_m2_percentile_sale = NULL, percentile_cohort_size_rent = NULL, "
                "percentile_cohort_size_sale = NULL, percentile_evaluated_at = NULL"
            )
        )
        db_session.commit()

        for prop in props:
            score_single_property(db_session, str(prop.id))
        db_session.commit()

        for prop in props:
            if prop.id not in bulk:
                continue
            assert _stored(db_session, prop) == bulk[prop.id], prop.id
            assert _metrics(db_session, prop).percentile_evaluated_at is not None

    def test_spelling_variants_and_a_spatial_assignment_agree_on_both_paths(
        self, db_session, real_redis
    ):
        nhood = Neighborhood(name="São Bento", city="Belo Horizonte", state="MG")
        db_session.add(nhood)
        db_session.flush()
        props = [
            _rent(db_session, 30, neighbourhood="Other", city="Elsewhere", neighborhood_id=nhood.id),
            _rent(db_session, 40, neighbourhood="Sao Bento", city="BELO  HORIZONTE"),
            _rent(db_session, 40, neighbourhood="SÃO	BENTO ", city="belo horizonte"),
            _rent(db_session, 60, neighbourhood=" são  bento", city=" Belo Horizonte "),
        ]
        db_session.commit()
        expected = [(share, 4, None, None) for share in (0.25, 0.75, 0.75, 1.0)]

        _bulk(db_session)
        assert [_stored(db_session, prop) for prop in props] == expected

        db_session.execute(
            text(
                "UPDATE metrics_scoring SET price_per_m2_percentile_rent = NULL, "
                "percentile_cohort_size_rent = NULL, percentile_evaluated_at = NULL"
            )
        )
        db_session.commit()
        for prop in props:
            score_single_property(db_session, str(prop.id))
        db_session.commit()
        assert [_stored(db_session, prop) for prop in props] == expected

    def test_insert_path_writes_the_percentile(self, db_session, real_redis):
        props = [_rent(db_session, ppm) for ppm in (30, 40, 40, 50)]
        db_session.commit()

        for prop in props:
            score_single_property(db_session, str(prop.id))
        db_session.commit()

        assert _rent_percentiles(db_session, props) == [0.25, 0.75, 0.75, 1.0]
        # The legacy per-type rank on this path is still the fabricated 0.5.
        assert _metrics(db_session, props[0]).percentile_rank_rent == pytest.approx(0.5)

    def test_below_the_minimum_is_null_with_its_size(self, db_session, real_redis):
        props = [_rent(db_session, ppm) for ppm in (30, 40)]
        db_session.commit()

        score_single_property(db_session, str(props[0].id))
        db_session.commit()

        ms = _metrics(db_session, props[0])
        assert _stored(db_session, props[0]) == (None, 2, None, None)
        assert ms.percentile_evaluated_at is not None

    def test_dual_property(self, db_session, real_redis):
        dual = _make_property(db_session)
        _add_listing(db_session, dual, price=4_000)
        _add_listing(db_session, dual, listing_type="sale", price=500_000)
        _rent(db_session, 30)
        _rent(db_session, 50)
        _sale(db_session, 4_000)
        db_session.commit()

        score_single_property(db_session, str(dual.id))
        db_session.commit()

        assert _stored(db_session, dual) == (pytest.approx(2 / 3), 3, None, 2)

    @pytest.mark.parametrize("area_m2", [None, 0])
    def test_no_usable_area_clears_an_existing_row_and_nothing_else(
        self, db_session, real_redis, area_m2
    ):
        _rent(db_session, 30)
        _rent(db_session, 40)
        subject = _rent(db_session, 50)
        db_session.commit()
        _bulk(db_session)
        before = _metrics(db_session, subject)
        assert before.price_per_m2_percentile_rent == 1.0
        kept = (before.price_per_m2_rent, before.stat_score_rent, before.percentile_rank_rent)

        subject.area_m2 = area_m2
        db_session.commit()
        score_single_property(db_session, str(subject.id))
        db_session.commit()

        after = _metrics(db_session, subject)
        assert _stored(db_session, subject) == (None, None, None, None)
        assert after.percentile_evaluated_at is not None
        assert (after.price_per_m2_rent, after.stat_score_rent, after.percentile_rank_rent) == kept

    def test_no_usable_price_and_no_row_writes_nothing(self, db_session, real_redis):
        prop = _make_property(db_session, price=0)
        db_session.commit()

        score_single_property(db_session, str(prop.id))
        db_session.commit()

        assert db_session.query(MetricsScoring).filter_by(property_id=prop.id).count() == 0

    def test_non_members_are_scored_without_a_percentile(self, db_session, real_redis):
        for ppm in (30, 40, 50):
            _rent(db_session, ppm)
        unassigned = _rent(db_session, 35, props_json=None)
        legacy = _make_property(db_session, price=3_500)
        inactive = _rent(db_session, 35, active=False)
        db_session.commit()

        for prop in (unassigned, legacy, inactive):
            score_single_property(db_session, str(prop.id))
        db_session.commit()

        for prop in (unassigned, legacy, inactive):
            ms = _metrics(db_session, prop)
            assert _stored(db_session, prop) == (None, None, None, None)
            assert ms.percentile_evaluated_at is not None
            assert ms.price_per_m2_rent == pytest.approx(35.0)


@pytest.mark.integration
class TestConfigOwnedMinimum:
    def test_suppression_follows_the_configured_value(self, db_session, monkeypatch):
        props = [_rent(db_session, ppm) for ppm in (30, 40, 50, 70)]
        db_session.commit()

        _bulk(db_session)
        assert _rent_percentiles(db_session, props) == [0.25, 0.5, 0.75, 1.0]

        _set_minimum(monkeypatch, 5)
        _bulk(db_session)
        assert _rent_percentiles(db_session, props) == [None] * 4
        assert _metrics(db_session, props[0]).percentile_cohort_size_rent == 4

        _set_minimum(monkeypatch, 4)
        _bulk(db_session)
        assert _rent_percentiles(db_session, props) == [0.25, 0.5, 0.75, 1.0]

    def test_committed_default_suppresses_a_cohort_of_nine(self, db_session, monkeypatch):
        monkeypatch.delenv(MIN_ENV)
        get_config.cache_clear()
        assert get_config().scoring.percentile_min_cohort_size == 10
        nine = [_rent(db_session, 30 + i) for i in range(9)]
        ten = [_rent(db_session, 30 + i, neighbourhood="Lourdes") for i in range(10)]
        db_session.commit()

        _bulk(db_session)

        assert _rent_percentiles(db_session, nine) == [None] * 9
        assert _metrics(db_session, nine[0]).percentile_cohort_size_rent == 9
        assert _rent_percentiles(db_session, ten) == pytest.approx(
            [(i + 1) / 10 for i in range(10)]
        )


@contextmanager
def _recorded_statements(engine):
    statements: list[str] = []

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append(" ".join(statement.split()).upper())

    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)


@pytest.mark.integration
class TestBulkStageStaysSetBased:
    def test_statement_count_does_not_depend_on_the_number_of_properties(self, db_session):
        engine = db_session.get_bind()

        def _run() -> tuple[int, int, int]:
            with _recorded_statements(engine) as statements:
                compute_neighborhood_stats(db_session)
            db_session.commit()
            reads = [s for s in statements if s.startswith(("SELECT", "WITH"))]
            counting = [s for s in statements if "PCT_MEMBERS" in s]
            clearing = [s for s in statements if s.startswith("UPDATE METRICS_SCORING AS MS")]
            return len(reads), len(counting), len(clearing)

        for ppm in (30, 40, 50):
            _rent(db_session, ppm)
        db_session.commit()
        small = _run()

        for ppm in range(20, 60):
            _rent(db_session, ppm)
        db_session.commit()
        large = _run()

        assert small == large
        reads, counting, clearing = large
        assert reads <= 4
        assert counting == 1  # the counts ride in the one existing statement
        assert clearing == 1


@pytest.mark.integration
class TestChecks:
    @pytest.mark.parametrize(
        "column, value",
        [
            ("price_per_m2_percentile_rent", 0.0),
            ("price_per_m2_percentile_rent", 1.01),
            ("price_per_m2_percentile_sale", -0.1),
            ("price_per_m2_percentile_sale", 0.0),
            ("percentile_cohort_size_rent", 0),
            ("percentile_cohort_size_sale", -1),
        ],
    )
    def test_out_of_range_values_are_rejected(self, db_session, column, value):
        prop = _make_property(db_session)
        db_session.add(MetricsScoring(property_id=prop.id))
        db_session.commit()

        with pytest.raises(IntegrityError):
            db_session.execute(
                text("UPDATE metrics_scoring SET " + column + " = :value WHERE property_id = :pid"),
                {"value": value, "pid": prop.id},
            )
        db_session.rollback()

    def test_bounds_are_accepted(self, db_session):
        prop = _make_property(db_session)
        db_session.add(MetricsScoring(property_id=prop.id))
        db_session.commit()

        db_session.execute(
            text(
                "UPDATE metrics_scoring SET price_per_m2_percentile_rent = 1.0, "
                "price_per_m2_percentile_sale = 0.001, percentile_cohort_size_rent = 1, "
                "percentile_cohort_size_sale = 1 WHERE property_id = :pid"
            ),
            {"pid": prop.id},
        )
        db_session.commit()


class TestMigration:
    """The migration applies and reverses on a real Postgres, to explicit revisions."""

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
    def _columns(engine) -> set[str]:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'metrics_scoring'"
                )
            ).fetchall()
        return {row[0] for row in rows} & set(PERCENTILE_COLUMNS)

    @staticmethod
    def _checks(engine) -> set[str]:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT conname FROM pg_constraint WHERE conname LIKE 'ck_metrics_scoring_%'")
            ).fetchall()
        return {row[0] for row in rows} & set(CHECKS)

    @staticmethod
    def _version(engine) -> str:
        with engine.connect() as conn:
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()

    def test_downgrade_then_upgrade_and_existing_rows_read_null(self):
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            pytest.skip("DATABASE_URL not set — run through scripts/agent/validate.py")
        assert_wipe_safe_database_url(database_url)
        engine = create_engine(database_url, poolclass=NullPool)
        row_id = None
        try:
            assert self._columns(engine) == set(PERCENTILE_COLUMNS)
            assert self._checks(engine) == set(CHECKS)
            try:
                down = self._alembic("downgrade", DOWN_REVISION)
                assert down.returncode == 0, down.stderr
                assert self._version(engine) == DOWN_REVISION
                assert self._columns(engine) == set()
                assert self._checks(engine) == set()
                # A row written before this story.
                with engine.begin() as conn:
                    row_id = conn.execute(
                        text(
                            "INSERT INTO metrics_scoring (stat_score, percentile_rank_rent) "
                            "VALUES (0.5, 0.5) RETURNING id"
                        )
                    ).scalar()
                up = self._alembic("upgrade", REVISION)
                assert up.returncode == 0, up.stderr
                assert self._version(engine) == REVISION
            finally:
                head = self._alembic("upgrade", "head")
            assert head.returncode == 0, head.stderr
            assert self._columns(engine) == set(PERCENTILE_COLUMNS)
            assert self._checks(engine) == set(CHECKS)
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT percentile_rank_rent, "
                        + ", ".join(PERCENTILE_COLUMNS)
                        + " FROM metrics_scoring WHERE id = :id"
                    ),
                    {"id": row_id},
                ).one()
            assert row[0] == pytest.approx(0.5)  # the legacy column is untouched
            assert list(row[1:]) == [None] * len(PERCENTILE_COLUMNS)
        finally:
            if row_id is not None:
                with engine.begin() as conn:
                    conn.execute(
                        text("DELETE FROM metrics_scoring WHERE id = :id"), {"id": row_id}
                    )
            engine.dispose()

    def test_model_matches_the_migrated_schema(self):
        """``compare_metadata`` reports no difference on ``metrics_scoring``."""
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
                model_checks = {
                    constraint.name
                    for constraint in Base.metadata.tables["metrics_scoring"].constraints
                }
        finally:
            engine.dispose()

        drift = [entry for entry in diff if "metrics_scoring" in repr(entry)]
        assert drift == [], drift
        # compare_metadata does not look at CHECKs: pin the names both sides use.
        assert set(CHECKS) <= model_checks

    def test_model_declares_the_columns_nullable_with_the_migrated_types(self):
        table = MetricsScoring.__table__
        for column in PERCENTILE_COLUMNS:
            assert table.c[column].nullable, column
            assert table.c[column].server_default is None, column
        assert str(table.c.price_per_m2_percentile_rent.type) == "FLOAT"
        assert str(table.c.percentile_cohort_size_sale.type) == "INTEGER"
        assert str(table.c.percentile_evaluated_at.type) == "DATETIME"


class TestSingleWriterAndPriceSource:
    """Static checks over ``src/`` (no database)."""

    WRITER = SRC_ROOT / "adapters" / "metrics" / "scoring.py"
    MODEL = SRC_ROOT / "adapters" / "db" / "models.py"

    @staticmethod
    def _production_files() -> list[Path]:
        return [
            path
            for path in SRC_ROOT.rglob("*.py")
            if "tests" not in path.relative_to(SRC_ROOT).parts
        ]

    @staticmethod
    def _references(path: Path) -> list[str]:
        """Every way a module could write one of the columns."""
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found: list[str] = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.ctx, ast.Store)
                and node.attr in PERCENTILE_COLUMNS
            ):
                found.append(f"{path.name}:{node.lineno} assigns .{node.attr}")
            elif isinstance(node, ast.keyword) and node.arg in PERCENTILE_COLUMNS:
                found.append(f"{path.name}:{node.lineno} passes {node.arg}=")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                # SQL text that writes: a SELECT naming the columns is a read.
                upper = node.value.upper()
                if "UPDATE " not in upper and "INSERT " not in upper:
                    continue
                for column in PERCENTILE_COLUMNS:
                    if column in node.value:
                        found.append(f"{path.name}:{node.lineno} names {column} in a string")
        return found

    def test_only_scoring_py_assigns_the_five_columns(self):
        offenders: list[str] = []
        for path in self._production_files():
            if path == self.WRITER:
                continue
            references = self._references(path)
            offenders.extend(references)
        assert offenders == []

    def test_a_write_in_sql_text_is_caught_and_a_read_is_not(self, tmp_path):
        writer = tmp_path / "writer.py"
        writer.write_text(
            'SQL = "UPDATE metrics_scoring SET price_per_m2_percentile_rent = NULL"\n',
            encoding="utf-8",
        )
        reader = tmp_path / "reader.py"
        reader.write_text(
            'SQL = "SELECT ms.price_per_m2_percentile_rent FROM metrics_scoring ms"\n',
            encoding="utf-8",
        )
        assert self._references(writer) != []
        assert self._references(reader) == []

    def test_the_writer_does_assign_all_five(self):
        assigned = {
            ref.split(" assigns .")[1]
            for ref in self._references(self.WRITER)
            if " assigns ." in ref
        }
        assert assigned == set(PERCENTILE_COLUMNS)

    def test_percentile_path_reads_no_price_of_its_own(self):
        """The price comes from ``COHORT_PRICE_SQL``; nothing else is read."""
        fragments = (
            scoring._PCT_PARTITION_SQL,
            scoring._PCT_PRICE_PER_M2_SQL,
            scoring._PCT_MEMBERS_JOIN_WHERE_SQL,
            scoring._PCT_MEMBERS_FROM_CTE_SQL,
        )
        sources = fragments + tuple(
            inspect.getsource(function)
            for function in (
                scoring._apply_percentile_fields,
                scoring._row_percentile_counts,
                scoring._clear_percentiles_of_non_members,
                scoring._single_property_percentile_counts,
            )
        )
        for source in sources:
            for forbidden in ("pl.price", "p.price", "properties.price", "total_monthly_cost"):
                assert forbidden not in source, forbidden
        assert scoring._PCT_PRICE_PER_M2_SQL.startswith("lm.price")
        core_module = (SRC_ROOT / "core" / "cohort_percentile.py").read_text(encoding="utf-8")
        assert "pl.price" not in core_module and "properties.price" not in core_module

    def test_percentile_sql_is_assembled_without_f_strings(self):
        tree = ast.parse(self.WRITER.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and "percentile" in node.name:
                assert not any(isinstance(child, ast.JoinedStr) for child in ast.walk(node)), (
                    node.name
                )
