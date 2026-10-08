"""Characterization lock for the legacy percentile output (Story 1.6, landed first).

``metrics_scoring.percentile_rank`` / ``_rent`` / ``_sale`` as the scoring
stage writes them today, and as the AD-12 list projection exposes them:

* bulk stage: SQL ``PERCENT_RANK`` — ``(rank - 1) / (n - 1)``, cheapest = 0,
  ties share the lowest rank, a cohort of one reads 0, no minimum cohort size;
* cohort key: the neighbourhood label alone — ``Unknown`` when the label is
  missing, and one cohort for a label shared by two cities;
* single-property path: a fabricated ``0.5`` per listing type (the legacy
  ``percentile_rank`` is ``0.5`` on insert and left alone on update);
* list projection: three percentile fields, rounded to 3 places, and a fixed
  key set.

Story 1.6 adds new percentile columns beside these. This file is not edited by
later commits: the legacy values, their meaning and the projection must stay
exactly as locked here.

All fixtures: ``area_m2`` 100, no neighbourhood FK, one Listing per type.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from adapters.db.models import MetricsScoring, Property, PropertyListing
from adapters.metrics.scoring import compute_neighborhood_stats, score_single_property
from core.property_projection import LIST_SELECT_COLUMNS, map_property_list_item
from tests.env_helpers import get_redis_url
from tests.redis_isolation import assert_wipe_safe_redis_url

ABS = 1e-9

TIES = "PctLockTies"
SOLO = "PctLockSolo"
SHARED_LABEL = "PctLockCentro"
DUAL = "PctLockDual"

# The exact key set of ``map_property_list_item`` (AD-12 list projection).
LIST_ITEM_KEYS = frozenset(
    {
        "id",
        "public_id",
        "platform",
        "platform_id",
        "title",
        "price",
        "area_m2",
        "bedrooms",
        "bathrooms",
        "address",
        "image_urls",
        "created_at",
        "lat",
        "lon",
        "stat_score",
        "ai_score",
        "combined_score",
        "percentile_rank",
        "z_score",
        "price_per_m2",
        "neighborhood_mean",
        "price_per_m2_rent",
        "price_per_m2_sale",
        "neighborhood_mean_rent",
        "neighborhood_mean_sale",
        "stat_score_rent",
        "stat_score_sale",
        "z_score_rent",
        "z_score_sale",
        "percentile_rank_rent",
        "percentile_rank_sale",
        "combined_score_rent",
        "combined_score_sale",
        "price_per_m2_percentile_rent",
        "price_per_m2_percentile_sale",
        "neighborhood_id",
        "neighborhood_name",
        "city",
        "parking",
        "description",
        "available_for_rent",
        "available_for_sale",
        "ai_features",
        "ai_issues",
        "ai_green_flags",
        "ai_red_flags",
        "condition_score",
        "sentiment_score",
        "stat_category",
        "stat_reasoning",
        "deal_summary",
        "visual_category",
        "visual_reasoning",
        "sentiment_category",
        "sentiment_reasoning",
        "listings",
        "primary_listing",
        "deciding_listing_id",
        "deciding_rule",
        "total_monthly_cost",
        "neighbourhood_quality",
    }
)
PERCENTILE_KEYS = frozenset(
    {
        "percentile_rank",
        "percentile_rank_rent",
        "percentile_rank_sale",
        "price_per_m2_percentile_rent",
        "price_per_m2_percentile_sale",
    }
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


def _make_property(session, *, props_json: dict | None) -> Property:
    prop = Property(
        platform="test",
        platform_id=f"p-{uuid4().hex[:12]}",
        title="Percentile characterization fixture",
        price=9_999,
        area_m2=100.0,
        props_json=props_json,
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


def _rent(session, price: float, props_json: dict | None) -> Property:
    prop = _make_property(session, props_json=props_json)
    _add_listing(session, prop, listing_type="rent", price=price)
    return prop


def _sale(session, price: float, props_json: dict | None) -> Property:
    prop = _make_property(session, props_json=props_json)
    _add_listing(session, prop, listing_type="sale", price=price)
    return prop


def _metrics(session, prop: Property) -> MetricsScoring:
    session.expire_all()
    return session.query(MetricsScoring).filter_by(property_id=prop.id).one()


def _seed_dual(session) -> dict[str, Property]:
    """Rent 30 / 35 / 40 (dual) / 50; sale 4000 / 5000 (dual) / 6000 / 7000."""
    label = {"neighborhood": DUAL}
    props = {
        "rent_30": _rent(session, 3_000, label),
        "rent_35": _rent(session, 3_500, label),
        "rent_50": _rent(session, 5_000, label),
        "sale_4000": _sale(session, 400_000, label),
        "sale_6000": _sale(session, 600_000, label),
        "sale_7000": _sale(session, 700_000, label),
    }
    dual = _make_property(session, props_json=label)
    _add_listing(session, dual, listing_type="rent", price=4_000)
    _add_listing(session, dual, listing_type="sale", price=500_000)
    props["dual"] = dual
    session.commit()
    return props


@pytest.mark.integration
class TestBulkStageLegacyPercentile:
    def test_ties_share_the_lowest_rank(self, db_session):
        """Rent 30 / 40 / 40 / 50: PERCENT_RANK 0, 1/3, 1/3, 1."""
        label = {"neighborhood": TIES}
        props = [_rent(db_session, price, label) for price in (3_000, 4_000, 4_000, 5_000)]
        db_session.commit()

        compute_neighborhood_stats(db_session)
        db_session.commit()

        rows = [_metrics(db_session, prop) for prop in props]
        expected = [0.0, 1 / 3, 1 / 3, 1.0]
        assert [ms.percentile_rank_rent for ms in rows] == pytest.approx(expected, abs=ABS)
        assert [ms.percentile_rank for ms in rows] == pytest.approx(expected, abs=ABS)
        assert [ms.percentile_rank_sale for ms in rows] == [None] * 4

    def test_single_member_cohort_reads_zero(self, db_session):
        """No minimum cohort size: a cohort of one is ranked, at 0."""
        prop = _rent(db_session, 6_000, {"neighborhood": SOLO})
        db_session.commit()

        compute_neighborhood_stats(db_session)
        db_session.commit()

        ms = _metrics(db_session, prop)
        assert ms.percentile_rank_rent == pytest.approx(0.0, abs=ABS)
        assert ms.percentile_rank == pytest.approx(0.0, abs=ABS)
        assert ms.percentile_rank_sale is None

    def test_missing_label_is_ranked_in_the_unknown_cohort(self, db_session):
        """No label (no props, or props without the key) -> one ``Unknown`` cohort.

        A blank label is its own cohort, not ``Unknown``: at 40 R$/m² it would
        sit between the two ``Unknown`` rows if it were one of them.
        """
        no_props = _rent(db_session, 3_000, None)
        no_key = _rent(db_session, 5_000, {"city": "Belo Horizonte"})
        blank = _rent(db_session, 4_000, {"neighborhood": ""})
        db_session.commit()

        compute_neighborhood_stats(db_session)
        db_session.commit()

        assert _metrics(db_session, no_props).percentile_rank_rent == pytest.approx(0.0, abs=ABS)
        assert _metrics(db_session, no_key).percentile_rank_rent == pytest.approx(1.0, abs=ABS)
        assert _metrics(db_session, blank).percentile_rank_rent == pytest.approx(0.0, abs=ABS)

    def test_unknown_cohort_is_addressable_by_its_key(self, db_session):
        no_props = _rent(db_session, 3_000, None)
        no_key = _rent(db_session, 5_000, {"city": "Belo Horizonte"})
        labelled = _rent(db_session, 4_000, {"neighborhood": SOLO})
        db_session.commit()

        count = compute_neighborhood_stats(db_session, "Unknown")
        db_session.commit()

        assert count == 2
        assert _metrics(db_session, no_props).percentile_rank == pytest.approx(0.0, abs=ABS)
        assert _metrics(db_session, no_key).percentile_rank == pytest.approx(1.0, abs=ABS)
        assert (
            db_session.query(MetricsScoring).filter_by(property_id=labelled.id).one_or_none()
            is None
        )

    def test_one_label_in_two_cities_is_one_cohort(self, db_session):
        """Belo Horizonte 30 and 50, Contagem 40: ranked together 0, 1, 0.5."""
        bh_cheap = _rent(
            db_session, 3_000, {"neighborhood": SHARED_LABEL, "city": "Belo Horizonte"}
        )
        bh_dear = _rent(
            db_session, 5_000, {"neighborhood": SHARED_LABEL, "city": "Belo Horizonte"}
        )
        contagem = _rent(db_session, 4_000, {"neighborhood": SHARED_LABEL, "city": "Contagem"})
        db_session.commit()

        compute_neighborhood_stats(db_session)
        db_session.commit()

        assert _metrics(db_session, bh_cheap).percentile_rank_rent == pytest.approx(0.0, abs=ABS)
        assert _metrics(db_session, bh_dear).percentile_rank_rent == pytest.approx(1.0, abs=ABS)
        assert _metrics(db_session, contagem).percentile_rank_rent == pytest.approx(0.5, abs=ABS)
        assert _metrics(db_session, contagem).neighborhood_mean_rent == pytest.approx(40.0)

    def test_dual_property_has_one_rank_per_type_and_rent_is_primary(self, db_session):
        props = _seed_dual(db_session)

        compute_neighborhood_stats(db_session)
        db_session.commit()

        dual = _metrics(db_session, props["dual"])
        assert dual.percentile_rank_rent == pytest.approx(2 / 3, abs=ABS)
        assert dual.percentile_rank_sale == pytest.approx(1 / 3, abs=ABS)
        assert dual.percentile_rank == pytest.approx(2 / 3, abs=ABS)

        sale_only = _metrics(db_session, props["sale_7000"])
        assert sale_only.percentile_rank_rent is None
        assert sale_only.percentile_rank_sale == pytest.approx(1.0, abs=ABS)
        assert sale_only.percentile_rank == pytest.approx(1.0, abs=ABS)

        rent_only = _metrics(db_session, props["rent_30"])
        assert rent_only.percentile_rank_rent == pytest.approx(0.0, abs=ABS)
        assert rent_only.percentile_rank_sale is None
        assert rent_only.percentile_rank == pytest.approx(0.0, abs=ABS)


@pytest.mark.integration
class TestSinglePropertyPathLegacyPercentile:
    def test_insert_path_writes_the_neutral_half(self, db_session, real_redis):
        props = _seed_dual(db_session)

        for name in ("rent_30", "sale_7000", "dual"):
            score_single_property(db_session, str(props[name].id))
        db_session.commit()

        rent_only = _metrics(db_session, props["rent_30"])
        assert rent_only.percentile_rank == pytest.approx(0.5)
        assert rent_only.percentile_rank_rent == pytest.approx(0.5)
        assert rent_only.percentile_rank_sale is None

        sale_only = _metrics(db_session, props["sale_7000"])
        assert sale_only.percentile_rank == pytest.approx(0.5)
        assert sale_only.percentile_rank_rent is None
        assert sale_only.percentile_rank_sale == pytest.approx(0.5)

        dual = _metrics(db_session, props["dual"])
        assert dual.percentile_rank == pytest.approx(0.5)
        assert dual.percentile_rank_rent == pytest.approx(0.5)
        assert dual.percentile_rank_sale == pytest.approx(0.5)

    def test_update_path_keeps_the_legacy_rank_and_overwrites_the_typed_ones(
        self, db_session, real_redis
    ):
        """After a bulk run, rescoring one row leaves ``percentile_rank`` as the
        bulk stage wrote it and resets the per-type ranks to 0.5."""
        props = _seed_dual(db_session)
        compute_neighborhood_stats(db_session)
        db_session.commit()

        score_single_property(db_session, str(props["dual"].id))
        db_session.commit()

        dual = _metrics(db_session, props["dual"])
        assert dual.percentile_rank == pytest.approx(2 / 3, abs=ABS)
        assert dual.percentile_rank_rent == pytest.approx(0.5)
        assert dual.percentile_rank_sale == pytest.approx(0.5)


@pytest.mark.integration
class TestListProjectionLegacyPercentile:
    """The AD-12 list projection over the stored legacy columns."""

    @staticmethod
    def _row(session, prop: Property):
        session.expire_all()
        return (
            session.execute(
                text(
                    "SELECT " + LIST_SELECT_COLUMNS + " "
                    "FROM properties p "
                    "LEFT JOIN metrics_scoring ms ON ms.property_id = p.id "
                    "LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id "
                    "WHERE p.id = :pid"
                ),
                {"pid": prop.id},
            )
            .mappings()
            .one()
        )

    def test_percentile_fields_and_exact_key_set(self, db_session):
        props = _seed_dual(db_session)
        compute_neighborhood_stats(db_session)
        db_session.commit()

        row = self._row(db_session, props["dual"])
        item = map_property_list_item(row)

        assert {key for key in row.keys() if "percentile" in key} == PERCENTILE_KEYS
        assert set(item) == LIST_ITEM_KEYS
        assert {key for key in item if "percentile" in key} == PERCENTILE_KEYS
        # Stored 2/3 and 1/3, rounded to three places on the way out.
        assert item["percentile_rank"] == 0.667
        assert item["percentile_rank_rent"] == 0.667
        assert item["percentile_rank_sale"] == 0.333

        sale_only = map_property_list_item(self._row(db_session, props["sale_7000"]))
        assert sale_only["percentile_rank"] == 1.0
        assert sale_only["percentile_rank_rent"] is None
        assert sale_only["percentile_rank_sale"] == 1.0

    def test_unscored_property_reads_null_percentiles(self, db_session):
        prop = _rent(db_session, 3_000, {"neighborhood": SOLO})
        db_session.commit()

        item = map_property_list_item(self._row(db_session, prop))

        assert set(item) == LIST_ITEM_KEYS
        assert item["percentile_rank"] is None
        assert item["percentile_rank_rent"] is None
        assert item["percentile_rank_sale"] is None
