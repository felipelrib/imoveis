"""Integration: the coverage SQL, run against a real Postgres (v0.13-s1.6).

The unit tier around this feature mocks ``fetch_coverage_inputs`` or hands the
adapter a fake row, so every statement in
``adapters.db.enrichment_coverage_queries`` was previously only ever executed
against an empty database — where all five signal predicates, the
``count(DISTINCT …) FILTER``, the photo-gated ``remaining`` and the throughput
CTE agree on zero no matter what they say. This seeds a small corpus that
distinguishes them:

* a fully enriched row (every signal present),
* a row whose ``visual`` key is JSON ``null`` — a failed stage, which is what
  ``m.meta -> 'visual' IS NOT NULL`` used to count as covered,
* a row whose whole ``meta`` is the JSON scalar ``null``,
* a row with no ``metrics_scoring`` row at all,
* a photo-blocked row and a row whose ``image_urls`` is not an array,
* a duplicated ``metrics_scoring`` row for one property (the table has no unique
  constraint on ``property_id``),
* and an inactive row carrying every signal, which must count for nothing.

Everything is asserted as an exact count, so a predicate that silently widens or
narrows changes a number here.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("DATABASE_URL"),
        reason="DATABASE_URL not set",
    ),
]

_VISUAL = {"condition_score": 0.7, "category": "Average"}
_SENTIMENT = {"sentiment_score": 0.6, "category": "Average"}
_VERDICT = {"verdict": "Worth a look"}


@pytest.fixture
def session(wipe_safe_db_session):
    """Wipe-safe session, emptied up front so the counts below are exact.

    The shared fixture wipes *after* a test; the coverage queries aggregate over
    the whole table, so anything a previous test left behind would land in these
    numbers. Deleting ``properties`` cascades to ``metrics_scoring``.
    """
    db = wipe_safe_db_session
    db.execute(text("DELETE FROM properties"))
    db.execute(text("DELETE FROM pipeline_metric_snapshots"))
    db.commit()
    return db


def _insert_property(
    session,
    *,
    active: bool = True,
    photos: int = 0,
    image_urls_json: str | None = None,
    embedding: bool = False,
) -> str:
    prop_id = str(uuid.uuid4())
    if image_urls_json is None:
        image_urls_json = json.dumps([f"https://example.test/{i}.jpg" for i in range(photos)])
    embedding_literal = "[" + ",".join(["0.0"] * 1024) + "]" if embedding else None
    session.execute(
        text(
            """
            INSERT INTO properties (
                id, platform, platform_id, title, price, active, image_urls, embedding
            )
            VALUES (
                CAST(:id AS uuid), 'test', :pid, 'coverage fixture', 1000, :active,
                CAST(:image_urls AS json), CAST(:embedding AS vector)
            )
            """
        ),
        {
            "id": prop_id,
            "pid": f"cov-{prop_id[:8]}",
            "active": active,
            "image_urls": image_urls_json,
            "embedding": embedding_literal,
        },
    )
    return prop_id


def _insert_metrics(
    session,
    property_id: str,
    *,
    meta_json: str | None = None,
    stat_score: float | None = None,
    ai_score: float | None = None,
) -> None:
    session.execute(
        text(
            """
            INSERT INTO metrics_scoring (property_id, stat_score, ai_score, meta)
            VALUES (CAST(:id AS uuid), :stat_score, :ai_score, CAST(:meta AS json))
            """
        ),
        {
            "id": property_id,
            "stat_score": stat_score,
            "ai_score": ai_score,
            "meta": meta_json,
        },
    )


@pytest.fixture
def seeded_corpus(session):
    """Seven active rows plus one inactive, each isolating one predicate."""
    from adapters.db.enrichment_coverage_queries import _min_photos_required
    from infra.config import get_config

    min_photos = _min_photos_required(get_config())

    # A: every signal present, already scored (so not outstanding work).
    full = _insert_property(session, photos=min_photos, embedding=True)
    _insert_metrics(
        session,
        full,
        meta_json=json.dumps(
            {"visual": _VISUAL, "sentiment": _SENTIMENT, "deal_verdict": _VERDICT}
        ),
        stat_score=0.5,
        ai_score=0.8,
    )

    # B: the failed-stage shape — ``visual`` written as JSON null. Covered by
    # ``IS NOT NULL``, not covered in fact. Unscored, so it is outstanding work.
    partial = _insert_property(session, photos=min_photos)
    _insert_metrics(
        session,
        partial,
        meta_json=json.dumps({"visual": None, "sentiment": _SENTIMENT}),
    )

    # C: no metrics row at all — outstanding work.
    _insert_property(session, photos=min_photos)

    # D: photo-blocked. The runner would never pick it up, so counting it as
    # outstanding would put the ETA permanently out of reach (v0.13-fu3).
    _insert_property(session, photos=0)

    # E: two metrics rows for one property (no unique constraint exists), both
    # carrying ``visual``. ``count(DISTINCT p.id)`` is what keeps this at one.
    duplicated = _insert_property(session, photos=min_photos)
    for _ in range(2):
        _insert_metrics(
            session,
            duplicated,
            meta_json=json.dumps({"visual": _VISUAL}),
            ai_score=0.7,
        )

    # F: ``meta`` is the JSON scalar null — ``json -> text`` is undefined for a
    # non-object, so the predicate has to exclude it before extracting.
    scalar_meta = _insert_property(session, photos=min_photos)
    _insert_metrics(session, scalar_meta, meta_json="null", ai_score=0.9)

    # G: ``image_urls`` is an object rather than an array: zero photos, blocked.
    _insert_property(session, image_urls_json=json.dumps({"a": 1}))

    # H: inactive, fully enriched, unscored and photo-rich. Must count for
    # nothing at all — neither denominator, numerator nor remaining.
    inactive = _insert_property(session, active=False, photos=min_photos, embedding=True)
    _insert_metrics(
        session,
        inactive,
        meta_json=json.dumps(
            {"visual": _VISUAL, "sentiment": _SENTIMENT, "deal_verdict": _VERDICT}
        ),
        stat_score=0.9,
    )

    session.commit()
    return {"min_photos": min_photos}


def test_signal_counts_reflect_what_the_database_actually_holds(session, seeded_corpus):
    from adapters.db.enrichment_coverage_queries import fetch_coverage_inputs

    inputs = fetch_coverage_inputs(session)

    # Seven active rows; the inactive one is not in the denominator.
    assert inputs.total_properties == 7
    assert inputs.enriched_by_task_class == {
        # A + E. B's JSON-null ``visual`` is a *failed* stage, F's scalar meta
        # holds nothing, and the inactive row is out of scope entirely.
        "visual": 2,
        # A + B.
        "sentiment": 2,
        # A only.
        "deal_verdict": 1,
        # ``stat_score IS NOT NULL`` — A only (the inactive row has one too).
        "valuation": 1,
        # ``properties.embedding IS NOT NULL`` — A only.
        "embedding": 1,
    }


def test_a_json_null_signal_is_not_coverage(session, seeded_corpus):
    """The regression this file exists for.

    ``m.meta -> 'visual' IS NOT NULL`` is true for ``{"visual": null}``: the key
    is present, holding a JSON null, so a stage that failed and stored nothing
    reads as covered. SQLAlchemy's ``JSON`` column writes Python ``None`` that
    way by default, so this is the ordinary shape of a failure.
    """
    from adapters.db.enrichment_coverage_queries import _SIGNAL_COUNTS_SQL

    naive = session.execute(
        text(
            """
            SELECT count(DISTINCT p.id) FILTER (WHERE m.meta -> 'visual' IS NOT NULL)
            FROM properties p
            LEFT JOIN metrics_scoring m ON m.property_id = p.id
            WHERE p.active AND json_typeof(m.meta) = 'object'
            """
        )
    ).scalar()
    honest = session.execute(text(_SIGNAL_COUNTS_SQL)).one()._mapping["visual"]

    assert naive == 3  # the JSON-null row counted as enriched
    assert honest == 2  # …and does not here


def test_remaining_counts_the_runners_queue_and_nothing_else(session, seeded_corpus):
    from adapters.db.enrichment_coverage_queries import fetch_coverage_inputs

    inputs = fetch_coverage_inputs(session)

    # B (unscored, photo-rich) and C (no metrics row, photo-rich). Excluded:
    # scored rows, the photo-blocked row, the non-array gallery, the inactive row.
    assert inputs.remaining == 2


def test_the_photo_gate_threshold_moves_the_remaining_count(session, seeded_corpus):
    """The gate is a threshold, not a boolean: raising it blocks more rows."""
    from adapters.db.enrichment_coverage_queries import _count_remaining_candidates

    min_photos = seeded_corpus["min_photos"]

    assert _count_remaining_candidates(session, 1) == 2
    assert _count_remaining_candidates(session, min_photos) == 2
    # Nothing has that many photos, so the whole queue is blocked.
    assert _count_remaining_candidates(session, min_photos + 1) == 0


def test_an_empty_corpus_measures_zero_rather_than_failing(session):
    from adapters.db.enrichment_coverage_queries import fetch_coverage_inputs

    inputs = fetch_coverage_inputs(session)

    assert inputs.total_properties == 0
    assert set(inputs.enriched_by_task_class.values()) == {0}
    assert inputs.remaining == 0
    assert inputs.throughput_per_day is None


# ---------------------------------------------------------------------------
# Throughput window
# ---------------------------------------------------------------------------


def _snapshot(session, *, hours_ago: float, enriched: int | None) -> None:
    session.execute(
        text(
            """
            INSERT INTO pipeline_metric_snapshots (ts, enriched_properties)
            VALUES (now() - (:hours * interval '1 hour'), :enriched)
            """
        ),
        {"hours": hours_ago, "enriched": enriched},
    )


@pytest.fixture
def seeded_snapshots(session):
    """A slow 24h of history with a fast last two hours inside it."""
    _snapshot(session, hours_ago=20, enriched=1000)
    _snapshot(session, hours_ago=2, enriched=4000)
    _snapshot(session, hours_ago=1, enriched=4100)
    # A measurement that failed to read the DB: excluded, never read as zero.
    _snapshot(session, hours_ago=0.5, enriched=None)
    # Older than the 24h lookback.
    _snapshot(session, hours_ago=40, enriched=10)
    session.commit()


def test_the_default_window_is_the_trailing_lookback(session, seeded_snapshots):
    from adapters.db.enrichment_coverage_queries import _throughput_per_day

    # 1000 -> 4100 over 19h, and the 40h-old point is outside the window.
    assert _throughput_per_day(session) == pytest.approx(3100 / (19 / 24), rel=0.01)


def test_a_live_run_clamps_the_window_to_its_lease_acquisition(
    session, seeded_snapshots
):
    """A young run must not be averaged across the idle hours before it.

    Snapshots are written every 30s regardless of the backfill, so the
    unclamped window charges this run for 19 hours it did not exist.
    """
    from adapters.db.enrichment_coverage_queries import _throughput_per_day

    since = datetime.now(timezone.utc) - timedelta(hours=3)

    # 4000 -> 4100 over the last hour: 2400/day, not ~3900.
    assert _throughput_per_day(session, since) == pytest.approx(2400.0, rel=0.02)


def test_a_clamped_window_with_one_usable_point_reports_nothing(
    session, seeded_snapshots
):
    """One point is not a rate — the clamp narrows the window, never the bar."""
    from adapters.db.enrichment_coverage_queries import _throughput_per_day

    since = datetime.now(timezone.utc) - timedelta(minutes=90)

    # Only the 1h-old point is usable inside the clamp (the 30-minute-old row
    # carries a null measurement), so no rate may be stated.
    assert _throughput_per_day(session, since) is None


def test_a_lease_older_than_the_lookback_does_not_widen_the_window(
    session, seeded_snapshots
):
    """A multi-day run keeps the 24h smoothing window, not its whole lifetime."""
    from adapters.db.enrichment_coverage_queries import _throughput_per_day

    since = datetime.now(timezone.utc) - timedelta(days=5)

    assert _throughput_per_day(session, since) == pytest.approx(3100 / (19 / 24), rel=0.01)


def test_a_minutes_old_run_is_not_extrapolated_into_a_daily_rate(session):
    """The lease clamp must not turn 30 seconds of history into a day's rate.

    Two snapshots a minute apart inside a just-acquired lease satisfy every
    other guard (two points, positive delta, positive elapsed), and the naive
    division states ~14k imóveis/dia off ten rows. The absent line is the honest
    answer until the window has actually filled.
    """
    from adapters.db.enrichment_coverage_queries import _throughput_per_day

    _snapshot(session, hours_ago=1 / 60, enriched=1000)  # 60s ago
    _snapshot(session, hours_ago=0.5 / 60, enriched=1010)  # 30s ago
    session.commit()

    since = datetime.now(timezone.utc) - timedelta(minutes=2)

    assert _throughput_per_day(session, since) is None


def test_a_window_at_the_minimum_span_does_report_a_rate(session):
    """The floor is a floor, not a mute: just over it, the rate is quoted."""
    from adapters.db.enrichment_coverage_queries import _throughput_per_day

    _snapshot(session, hours_ago=0.5, enriched=1000)  # 30 min ago
    _snapshot(session, hours_ago=0.0, enriched=1100)
    session.commit()

    since = datetime.now(timezone.utc) - timedelta(hours=1)

    # 100 rows in half an hour = 4800/day.
    assert _throughput_per_day(session, since) == pytest.approx(4800.0, rel=0.02)


def test_a_lease_stamped_in_the_future_falls_back_to_the_lookback(
    session, seeded_snapshots
):
    """A forward clock jump must not silently delete the operator's ETA.

    An ``acquired_at`` ahead of the DB clock (a resumed WSL host) would push the
    window start past every snapshot, and the card would show no rate and no
    reason for the rest of the run.
    """
    from adapters.db.enrichment_coverage_queries import _throughput_per_day

    since = datetime.now(timezone.utc) + timedelta(hours=6)

    assert _throughput_per_day(session, since) == pytest.approx(3100 / (19 / 24), rel=0.01)
