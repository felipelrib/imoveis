"""SQL behind the DB-derived enrichment coverage endpoint (v0.13-s1.6, FR-29).

Every figure the coverage endpoint reports about *progress* is measured here,
against the domain database — never read back from the backfill runner's Redis
checkpoints. The runner's control state answers exactly one question for this
feature ("is a pass live, and since when?"); anything numeric comes from these
queries, so a crashed, restarted or hand-driven run can never make coverage read
wrong. The "since when" is a *window bound* on the throughput query and nothing
more — it chooses which measurements are read, never what they say.

Invariants worth knowing before editing:

* **The denominator is active properties.** Delisted rows are never enriched,
  so counting them would depress coverage permanently and hold the ETA above
  zero forever — the dead-completion-branch bug v0.13-fu3 fixed in the runner.
* **``remaining`` mirrors the runner's own queue**, photo gate included. The
  runner skips gallery-less rows outright, so counting them as outstanding work
  would make the ETA unreachable by construction. The candidate predicate below
  is a deliberate copy of ``_CANDIDATES_SUBQUERY`` in
  ``scripts/dev/backfill_gemma.py`` (that script is not importable from the API
  container; the duplication is the price of keeping the two agreeing, and
  ``src/tests/unit/test_coverage_sql_drift.py`` fails the build if they stop).

And two honest limits of the ETA, stated here because the number looks more
exact than it is (they are repeated on ``BackfillProgressModel`` in
``src/api/schemas.py``, which is what a reader of the wire shape sees):

* **The rate and the remainder are measured over different populations.**
  ``remaining`` counts *active*, photo-gated rows with no ``ai_score``, while
  the rate comes from ``pipeline_metric_snapshots.enriched_properties`` — which
  ``api.system._check_db_and_counts`` computes as ``COUNT(*) FROM
  metrics_scoring WHERE ai_score > 0`` over the whole corpus: no ``active``
  filter, no photo gate, and it moves for live-pipeline enrichment too, not
  only for the backfill. So ``eta_days`` is *remaining backfill work divided by
  total enrichment velocity* — an approximation that runs optimistic while the
  live pipeline is also scoring rows, and pessimistic if inactive rows are
  being enriched. It is an order-of-magnitude figure for an operator watching a
  multi-day pass, never a delivery date. Re-plumbing the snapshot writer to
  emit a backfill-scoped counter is the fix, and it is not this story's.
* **``remaining`` does not subtract quarantined candidates.** The runner's own
  census does (``_count_quarantined_candidates``), so a row that has burned its
  retry budget stops being outstanding work *for the runner* while staying
  outstanding here — and the ETA of a pass whose tail is permanently failing
  rows will not converge to zero. Answering it correctly means the Redis
  attempt-ledger scan story 1.5 deliberately kept off ``/backfill/status``
  (O(rows ever attempted) ``HGETALL`` + sort, on a route the UI polls), so this
  route accepts the overstatement instead of paying that cost on every poll.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

import sqlalchemy

from core.enrichment import EnrichmentTaskClass
from core.photo_gate import effective_min_photos
from infra.config import get_config

__all__ = [
    "THROUGHPUT_LOOKBACK_HOURS",
    "CoverageInputs",
    "fetch_coverage_inputs",
]

# Throughput window: the trailing 24 hours of ``pipeline_metric_snapshots``.
# A shorter window makes the rate swing with a single slow hour of a multi-day
# pass; a longer one keeps quoting a rate hours after a run has stopped. It is a
# module constant, not a config key, on purpose — this is an internal smoothing
# choice with no operator-facing meaning, and the story adds no new config.
THROUGHPUT_LOOKBACK_HOURS = 24

_SECONDS_PER_DAY = 86400.0

# Shortest span of history that may be extrapolated to a daily rate. The lease
# clamp above is what makes this necessary: with the window pinned to a run that
# started a minute ago, the first two snapshots are 30 seconds apart, and
# ``delta / (30/86400)`` turns a handful of rows into a four-digit
# imóveis/dia claim (and an ETA to match) that the next tick contradicts. A run
# has to have been measured for a quarter of an hour before its rate is quoted;
# until then the honest answer is the absent line, not a noisy one.
_MIN_WINDOW_SECONDS = 900.0

# The three model-written signals live under their task-class names inside
# ``metrics_scoring.meta``, a Postgres ``json`` column (not ``jsonb``). The
# ``->`` operator is defined for both types, so the predicates below need no
# cast -- and deliberately avoid one: casting ``json`` to ``jsonb`` rejects NUL
# unicode escapes, which the scraped free text inside the AI meta blobs can
# legitimately carry, and that would turn a healthy read into a 500.
_TOTAL_SQL = "SELECT count(*) FROM properties WHERE active"

# ``count(DISTINCT p.id)``, not ``count(*)``: ``metrics_scoring.property_id``
# carries no unique constraint, so a duplicated metrics row would otherwise let
# a signal count exceed the denominator and produce a fraction above 1.0.
#
# ``json_typeof(...) <> 'null'``, not a bare ``IS NOT NULL``: a key explicitly
# written as JSON ``null`` is a *present* key holding a null value, so ``->``
# returns a non-SQL-NULL json datum and ``IS NOT NULL`` is true. A degenerate or
# failed enrichment stage that stored ``{"visual": null}`` would count as
# covered — and SQLAlchemy's ``JSON`` column writes Python ``None`` values
# exactly that way (``none_as_null`` is off by default), so this is the normal
# shape of a failure, not a corner case. The ``CASE`` guard around it is not
# decoration either: ``json -> text`` is only defined for objects, and ``AND``
# is not guaranteed to short-circuit, so a row whose whole ``meta`` is a scalar
# has to be excluded *before* the extraction is attempted.
#
# The column aliases below are the ``EnrichmentTaskClass`` values themselves —
# ``_count_enriched_by_task_class`` looks each member up by name, so a member
# added to the enum without a column here is a ``KeyError`` at request time.
# ``test_admin_coverage_api.py`` asserts the two sets match, so the gap surfaces
# in the suite instead of on a polled route.
_SIGNAL_COUNTS_SQL = """
    SELECT
      count(DISTINCT p.id) FILTER (
        WHERE CASE WHEN json_typeof(m.meta) = 'object'
                   THEN json_typeof(m.meta -> 'visual') <> 'null'
                   ELSE false END)
        AS visual,
      count(DISTINCT p.id) FILTER (
        WHERE CASE WHEN json_typeof(m.meta) = 'object'
                   THEN json_typeof(m.meta -> 'sentiment') <> 'null'
                   ELSE false END)
        AS sentiment,
      count(DISTINCT p.id) FILTER (
        WHERE CASE WHEN json_typeof(m.meta) = 'object'
                   THEN json_typeof(m.meta -> 'deal_verdict') <> 'null'
                   ELSE false END)
        AS deal_verdict,
      count(DISTINCT p.id) FILTER (WHERE m.stat_score IS NOT NULL)
        AS valuation,
      count(DISTINCT p.id) FILTER (WHERE p.embedding IS NOT NULL)
        AS embedding
    FROM properties p
    LEFT JOIN metrics_scoring m ON m.property_id = p.id
    WHERE p.active
"""

# Mirrors ``scripts/dev/backfill_gemma.py::_CANDIDATES_SUBQUERY`` — active rows
# with no AI score, with the photo count computed exactly the way
# ``core.photo_gate.count_photos`` does (non-blank strings only), so the SQL
# census and the runner's in-process partition agree on which rows are blocked.
_CANDIDATES_SUBQUERY = """
    SELECT p.id AS id,
           CASE
             WHEN p.image_urls IS NULL THEN 0
             WHEN jsonb_typeof(p.image_urls::jsonb) <> 'array' THEN 0
             ELSE (
               SELECT count(*) FROM jsonb_array_elements_text(p.image_urls::jsonb) u
               WHERE btrim(u) <> ''
             )
           END AS photos
    FROM properties p
    LEFT JOIN metrics_scoring m ON m.property_id = p.id
    WHERE p.active
      AND (m.id IS NULL OR m.ai_score IS NULL OR m.ai_score = 0)
"""

_REMAINING_SQL = (
    "SELECT count(*) FROM (" + _CANDIDATES_SUBQUERY + ") q WHERE q.photos >= :min_photos"
)

# Oldest and newest usable point in the window, in one round trip. Rows with a
# null ``enriched_properties`` are excluded rather than coalesced to zero: a
# missing measurement is not a measurement of zero, and treating it as one
# would fabricate an enormous delta on the next real point.
#
# The window starts at the *later* of "24h ago" and ``:since`` — the current
# run's lease acquisition. Snapshots are written every 30s whether or not a
# backfill is running, so a fixed 24h window divides a run that started thirty
# minutes ago across 23.5 idle hours and quotes a rate (and therefore an ETA)
# the operator has no reason to distrust. ``GREATEST`` ignores NULLs, so a
# ``:since`` of ``None`` leaves the plain 24h window in place; the cast is what
# lets the driver send that ``None`` without an untyped-parameter error.
#
# A ``:since`` in the DB's *future* is discarded rather than honoured: a host
# whose clock jumped forward (a suspended WSL box resuming is the ordinary way
# this happens) writes a lease ``acquired_at`` ahead of the database, and using
# it would move the window start past every snapshot and leave the operator with
# no rate and no ETA for the rest of the run, with nothing on screen to explain
# it. Falling back to the plain lookback is the conservative direction — it can
# only understate a young run's rate, never invent one. Clamping to ``now()``
# instead would be worse than useless: it would make the window empty by
# construction (as the test for this asserts).
_THROUGHPUT_SQL = """
    WITH bounds AS (
        SELECT GREATEST(
                 now() - (:hours * interval '1 hour'),
                 CASE WHEN CAST(:since AS timestamptz) > now() THEN NULL
                      ELSE CAST(:since AS timestamptz) END
               ) AS start_ts
    ),
    w AS (
        SELECT s.ts, s.enriched_properties
        FROM pipeline_metric_snapshots s, bounds b
        WHERE s.enriched_properties IS NOT NULL
          AND s.ts >= b.start_ts
    )
    SELECT
      (SELECT count(*) FROM w) AS points,
      (SELECT ts FROM w ORDER BY ts ASC LIMIT 1) AS first_ts,
      (SELECT enriched_properties FROM w ORDER BY ts ASC LIMIT 1) AS first_enriched,
      (SELECT ts FROM w ORDER BY ts DESC LIMIT 1) AS last_ts,
      (SELECT enriched_properties FROM w ORDER BY ts DESC LIMIT 1) AS last_enriched
"""


@dataclass(frozen=True)
class CoverageInputs:
    """Everything the pure coverage math needs, measured from the database."""

    total_properties: int
    enriched_by_task_class: Dict[str, int] = field(default_factory=dict)
    remaining: int = 0
    throughput_per_day: Optional[float] = None


def _min_photos_required(cfg: Any) -> int:
    """Photos a row needs before the backfill can enrich it at all.

    Mirrors ``scripts/dev/backfill_gemma.py::_min_photos_required``: with the
    gate on this is its threshold; with the gate off it is still 1, because the
    visual stage has nothing to look at in a gallery-less row and the runner
    rejects it before the gate is even consulted.
    """
    gate = cfg.scraping.photo_gate
    if not getattr(gate, "enabled", True):
        return 1
    override = getattr(gate, "min_photos", None)
    if override is not None:
        return max(1, int(override))
    return effective_min_photos(
        floor_min=int(getattr(gate, "floor_min", 8)),
        max_images_per_property=int(cfg.ai.max_images_per_property),
        coverage_ratio=float(getattr(gate, "coverage_ratio", 1.0)),
    )


def _count_active_properties(session: Any) -> int:
    return int(session.execute(sqlalchemy.text(_TOTAL_SQL)).scalar() or 0)


def _count_enriched_by_task_class(session: Any) -> Dict[str, int]:
    row = session.execute(sqlalchemy.text(_SIGNAL_COUNTS_SQL)).one()
    mapping = row._mapping
    return {
        task_class.value: int(mapping[task_class.value] or 0)
        for task_class in EnrichmentTaskClass
    }


def _count_remaining_candidates(session: Any, min_photos: int) -> int:
    stmt = sqlalchemy.text(_REMAINING_SQL).bindparams(min_photos=int(min_photos))
    return int(session.execute(stmt).scalar() or 0)


def _throughput_per_day(
    session: Any, since: Optional[datetime] = None
) -> Optional[float]:
    """Enriched-properties-per-day across the lookback window, or ``None``.

    ``since`` clamps the window start (the current run's lease acquisition):
    measuring a young run against 24h of mostly-idle snapshots understates its
    rate by however much of the day it missed. Points older than ``since`` are
    dropped, which is also why a fresh run reports ``None`` for a while — one
    point is not a rate, and the clamped window has to fill up first.

    ``None`` for every case that cannot honestly support a rate: fewer than two
    points *in the clamped window*, a flat or negative delta (a re-scored corpus
    can shrink the count), two points sharing a timestamp, or a span shorter
    than ``_MIN_WINDOW_SECONDS`` — thirty seconds of history extrapolated to a
    day is noise wearing a number's clothes. The caller turns that into an
    omitted line rather than a zero.
    """
    row = session.execute(
        sqlalchemy.text(_THROUGHPUT_SQL).bindparams(
            hours=int(THROUGHPUT_LOOKBACK_HOURS), since=since
        )
    ).one()
    values = row._mapping
    if int(values["points"] or 0) < 2:
        return None
    delta = int(values["last_enriched"] or 0) - int(values["first_enriched"] or 0)
    if delta <= 0:
        return None
    first_ts, last_ts = values["first_ts"], values["last_ts"]
    if first_ts is None or last_ts is None:
        return None
    elapsed_seconds = (last_ts - first_ts).total_seconds()
    if elapsed_seconds < _MIN_WINDOW_SECONDS:
        return None
    return delta / (elapsed_seconds / _SECONDS_PER_DAY)


def fetch_coverage_inputs(
    session: Any, *, run_started_at: Optional[datetime] = None
) -> CoverageInputs:
    """Measure coverage, outstanding work and throughput in one pass.

    The session is supplied by the caller (the admin route opens and closes it);
    nothing here writes or commits.

    ``run_started_at`` is the live run's lease acquisition timestamp when one is
    held — the only thing Redis contributes to a number here, and it contributes
    a *window bound*, not a measurement: it decides which snapshots the rate is
    read from, never what the rate is.
    """
    min_photos = _min_photos_required(get_config())
    return CoverageInputs(
        total_properties=_count_active_properties(session),
        enriched_by_task_class=_count_enriched_by_task_class(session),
        remaining=_count_remaining_candidates(session, min_photos),
        throughput_per_day=_throughput_per_day(session, run_started_at),
    )
