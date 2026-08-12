"""Pure coverage/ETA math behind ``GET /admin/enrichment/coverage`` (FR-29).

Framework-free by design: this module knows nothing about SQLAlchemy, FastAPI or
Redis. The adapter (``adapters.db.enrichment_coverage_queries``) measures the
database, the route asks the runner's lease whether a pass is live, and
everything that turns those numbers into the wire shape happens here — which is
why this is the layer the "never fabricate a figure" rules are enforced in and
the layer they are unit-tested at.

Two rules carry the whole feature:

* **Absence over zero.** ``fraction`` is ``None`` when the denominator is zero.
  An empty (or fully delisted) database has *undefined* coverage; reporting
  ``0.0`` would tell the operator their enrichment had failed. Same for
  ``minimum_fraction`` when nothing is measurable.
* **No projection without a live run and usable history.** ``throughput_per_day``,
  ``eta_days`` and ``projected_completion_date`` are all ``None`` unless a run
  actually holds the lease *and* the snapshot history yields a positive rate.
  ``estimate_eta_days`` returns ``inf`` for a non-positive rate, and ``inf`` is
  not representable in JSON — so it is converted to ``None`` here rather than
  being allowed anywhere near a response model.

The denominator is *active* properties only (see the adapter): delisted rows are
never enriched, so counting them would depress coverage forever and stall the
ETA — the dead-completion-branch failure v0.13-fu3 fixed in the runner itself.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Mapping, Optional, Tuple

from core.backfill_runner import estimate_eta_days
from core.enrichment import EnrichmentTaskClass

__all__ = [
    "SignalCoverage",
    "BackfillProgress",
    "CoverageReport",
    "coverage_fraction",
    "build_backfill_progress",
    "build_coverage_report",
]

# Rounding is a wire concern, not a math one: it keeps repeated calls over an
# unchanged database byte-identical (an acceptance criterion) and stops
# floating-point noise ("0.6170000000000001") from reaching the UI.
_FRACTION_DECIMALS = 6
_RATE_DECIMALS = 2
_ETA_DECIMALS = 2


@dataclass(frozen=True)
class SignalCoverage:
    """How much of the active corpus carries one enrichment signal.

    ``task_class`` is the ``EnrichmentTaskClass`` *value* (English on the wire —
    pt-BR exists only as a rendered label, per the story's boundary rules).
    """

    task_class: str
    enriched: int
    total: int
    fraction: Optional[float]


@dataclass(frozen=True)
class BackfillProgress:
    """What the cloud backfill is doing, as far as the DB and the lease can say.

    ``active`` is the runner's Redis lease and nothing else; every other field is
    derived from the database. That split is FR-29: the runner's control state
    must never become a second progress metric.
    """

    active: bool
    remaining: int
    throughput_per_day: Optional[float]
    eta_days: Optional[float]
    projected_completion_date: Optional[str]


@dataclass(frozen=True)
class CoverageReport:
    """The whole ``/admin/enrichment/coverage`` payload, pre-serialisation."""

    signals: Tuple[SignalCoverage, ...]
    minimum_fraction: Optional[float]
    total_properties: int
    backfill: BackfillProgress


def coverage_fraction(enriched: int, total: int) -> Optional[float]:
    """Enriched share of ``total``, or ``None`` when there is nothing to cover.

    ``None`` — never ``0.0``: an empty denominator makes the fraction undefined,
    and rendering that as 0% would report a total enrichment failure on a
    database that simply holds no active properties.

    The result is clamped into ``[0.0, 1.0]``: ``metrics_scoring`` has no unique
    constraint on ``property_id``, so a duplicated row must not be able to push
    the value past the response model's ``le=1.0`` and turn a healthy read into
    a 500.
    """
    if total <= 0:
        return None
    fraction = float(enriched) / float(total)
    return round(min(1.0, max(0.0, fraction)), _FRACTION_DECIMALS)


def _projected_completion(eta_days: float, today: date) -> Optional[str]:
    """ISO date the run is expected to have finished on, rounded up to a day.

    Rounding *up* keeps the promise honest (a 0.17-day ETA finishes tomorrow,
    not today) while ``remaining == 0`` still lands on ``today``. An ETA far
    enough out to overflow ``datetime.date`` yields ``None`` rather than a
    clamped year-9999 date, which would read as a real prediction.
    """
    try:
        whole_days = math.ceil(eta_days)
        return (today + timedelta(days=whole_days)).isoformat()
    except (OverflowError, ValueError):
        return None


def build_backfill_progress(
    *,
    active: bool,
    remaining: int,
    throughput_per_day: Optional[float],
    today: date,
) -> BackfillProgress:
    """Combine lease liveness with DB-measured work and rate into a projection.

    ``remaining`` is always reported (it is a plain measurement of the queue,
    true whether or not anything is working on it). The three forward-looking
    fields are reported only when a run is live *and* the rate is usable.
    """
    remaining = max(0, int(remaining))
    blank = BackfillProgress(
        active=bool(active),
        remaining=remaining,
        throughput_per_day=None,
        eta_days=None,
        projected_completion_date=None,
    )
    if not active:
        # A historical rate with nothing running would promise progress that
        # nobody is making — the UI must show absence instead (UX-DR3).
        return blank
    rate = throughput_per_day
    if rate is None or not math.isfinite(float(rate)) or float(rate) <= 0.0:
        # Fewer than two usable snapshots, or a flat/negative delta: one point
        # cannot make a rate, and inventing one is exactly what FR-29 forbids.
        return blank

    rate = float(rate)
    eta = estimate_eta_days(remaining, rate)
    if not math.isfinite(eta) or eta < 0.0:
        return BackfillProgress(
            active=True,
            remaining=remaining,
            throughput_per_day=round(rate, _RATE_DECIMALS),
            eta_days=None,
            projected_completion_date=None,
        )
    return BackfillProgress(
        active=True,
        remaining=remaining,
        throughput_per_day=round(rate, _RATE_DECIMALS),
        eta_days=round(eta, _ETA_DECIMALS),
        projected_completion_date=_projected_completion(eta, today),
    )


def build_coverage_report(
    *,
    enriched_by_task_class: Mapping[str, int],
    total_properties: int,
    active: bool,
    remaining: int,
    throughput_per_day: Optional[float],
    today: date,
) -> CoverageReport:
    """Assemble the coverage payload from measured counts and lease liveness.

    Every ``EnrichmentTaskClass`` member is always present, in declaration
    order, whether or not the adapter measured it — a signal missing from the
    response would read as "not applicable" instead of "not enriched".
    """
    total = max(0, int(total_properties))
    signals = tuple(
        SignalCoverage(
            task_class=task_class.value,
            enriched=max(0, int(enriched_by_task_class.get(task_class.value, 0) or 0)),
            total=total,
            fraction=coverage_fraction(
                int(enriched_by_task_class.get(task_class.value, 0) or 0), total
            ),
        )
        for task_class in EnrichmentTaskClass
    )
    measured = [s.fraction for s in signals if s.fraction is not None]
    return CoverageReport(
        signals=signals,
        minimum_fraction=min(measured) if measured else None,
        total_properties=total,
        backfill=build_backfill_progress(
            active=active,
            remaining=remaining,
            throughput_per_day=throughput_per_day,
            today=today,
        ),
    )
