"""Resumable, RPD-aware enrichment backfill loop (BIN-248).

Free-tier Gemma is capped at ~14,400 requests/day and 16K TPM, so a full ~26k
property pass spreads over ~6 days. This module holds the **pure, injectable**
control logic — daily-budget accounting, a resume checkpoint, and the iteration
loop — with Redis, the DB, the AI client, and the clock all injected. It imports
no Celery/DB/network module, so it unit-tests with a dict-backed fake Redis and a
fake ``enrich_fn``.

Coordination with the live pipeline: the runner never enqueues onto the ``ai``
Celery queue and never touches the GPU semaphore. It calls the shared
``run_enrichment`` orchestration directly against a remote Gemma client and paces
on the API budget, so it cannot contend with local, GPU-bound ``ai_enrich``
workers. ``mode=missing`` selection plus a ``force``-gated skip keep it idempotent
if a live worker enriched a row in between.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable, Iterable, Optional, Tuple

from core.enrichment_rerun import mode_is_missing_ai

# Keep the daily counter around long enough to inspect yesterday's usage.
_BUDGET_TTL_SECONDS = 2 * 24 * 3600

EnrichFn = Callable[[Any], Awaitable[None]]
SleepFn = Callable[[float], Awaitable[None]]


def _utc_today(now_fn: Callable[[], datetime]) -> date:
    return now_fn().astimezone(timezone.utc).date()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class DailyBudget:
    """Redis-backed daily request counter enforcing an RPD ceiling.

    The counter key rolls over per UTC calendar day (matching a provider's
    once-a-day RPD reset). ``try_consume`` is the gate: it reserves ``n``
    requests only if that keeps the day under ``daily_limit``.
    """

    def __init__(
        self,
        redis: Any,
        *,
        prefix: str,
        daily_limit: int,
        now_fn: Callable[[], datetime] = _now_utc,
    ) -> None:
        self._redis = redis
        self._prefix = prefix
        self._daily_limit = int(daily_limit)
        self._now_fn = now_fn

    def _key(self) -> str:
        return f"{self._prefix}:budget:{_utc_today(self._now_fn).isoformat()}"

    def consumed(self) -> int:
        return int(self._redis.get(self._key()) or 0)

    def remaining(self) -> int:
        return max(0, self._daily_limit - self.consumed())

    def try_consume(self, n: int) -> bool:
        """Reserve ``n`` requests; return False (and reserve nothing) if over."""
        if n <= 0:
            return True
        key = self._key()
        new_total = int(self._redis.incrby(key, n))
        if new_total == n:  # first write today → set expiry once
            self._redis.expire(key, _BUDGET_TTL_SECONDS)
        if new_total > self._daily_limit:
            self._redis.incrby(key, -n)  # roll back the over-reservation
            return False
        return True


class Checkpoint:
    """Resume marker: last property processed + running total + last run date."""

    def __init__(
        self,
        redis: Any,
        *,
        prefix: str,
        now_fn: Callable[[], datetime] = _now_utc,
    ) -> None:
        self._redis = redis
        self._key = f"{prefix}:checkpoint"
        self._now_fn = now_fn

    def load(self) -> dict[str, str]:
        raw = self._redis.hgetall(self._key) or {}
        # Tolerate both decoded and bytes Redis clients.
        out: dict[str, str] = {}
        for k, v in raw.items():
            out[k.decode() if isinstance(k, bytes) else k] = (
                v.decode() if isinstance(v, bytes) else v
            )
        return out

    def processed_total(self) -> int:
        return int(self.load().get("processed_total", 0) or 0)

    def advance(self, property_id: str) -> None:
        self._redis.hset(
            self._key,
            mapping={
                "last_property_id": str(property_id),
                "last_run_date": _utc_today(self._now_fn).isoformat(),
            },
        )
        self._redis.hincrby(self._key, "processed_total", 1)


class Heartbeat:
    """Short-TTL 'backfill active' flag other components can observe."""

    def __init__(self, redis: Any, *, prefix: str, ttl_seconds: int = 300) -> None:
        self._redis = redis
        self._key = f"{prefix}:active"
        self._ttl = ttl_seconds

    def beat(self) -> None:
        self._redis.set(self._key, "1", ex=self._ttl)

    def clear(self) -> None:
        self._redis.delete(self._key)


@dataclass
class BackfillResult:
    """Outcome of one backfill invocation."""

    processed: int = 0
    would_process: int = 0
    skipped_already_enriched: int = 0
    errors: int = 0
    requests_consumed: int = 0
    budget_exhausted: bool = False
    last_property_id: Optional[str] = None
    error_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "processed": self.processed,
            "would_process": self.would_process,
            "skipped_already_enriched": self.skipped_already_enriched,
            "errors": self.errors,
            "requests_consumed": self.requests_consumed,
            "budget_exhausted": self.budget_exhausted,
            "last_property_id": self.last_property_id,
        }


def estimate_eta_days(remaining_properties: int, daily_property_rate: float) -> float:
    """Whole-and-fractional days to finish at ``daily_property_rate`` props/day."""
    if daily_property_rate <= 0:
        return float("inf")
    return remaining_properties / daily_property_rate


def pace_seconds_for_budget(requests_per_property: int, daily_request_budget: int) -> float:
    """Seconds to wait per property so the daily budget spreads evenly over 24h.

    Spreading the budget across the full day keeps the request rate far under the
    free-tier per-minute cap (30 RPM) as well as the daily RPD ceiling. Returns 0
    when the budget is non-positive (pacing disabled).
    """
    if daily_request_budget <= 0:
        return 0.0
    return requests_per_property * 86400.0 / daily_request_budget


async def run_backfill(
    rows: Iterable[Tuple[Any, Any]],
    *,
    enrich_fn: EnrichFn,
    budget: DailyBudget,
    checkpoint: Checkpoint,
    requests_per_property: int,
    limit: Optional[int] = None,
    force: bool = False,
    dry_run: bool = False,
    pace_seconds: float = 0.0,
    sleep_fn: SleepFn = asyncio.sleep,
    on_progress: Optional[Callable[[BackfillResult], None]] = None,
) -> BackfillResult:
    """Iterate candidate ``(property, metrics)`` rows, enriching within budget.

    Stops when the daily budget can no longer fund another property
    (``budget_exhausted``), the optional ``limit`` of attempted properties is
    reached, or the rows run out — either way it's safe to invoke again the next
    day to resume. ``enrich_fn`` raises on hard failure; the row is counted as an
    error and the loop continues.

    ``limit`` caps the number of properties *attempted* this run (skipped rows do
    not count), so a small ``--limit`` trial touches exactly that many.

    ``dry_run`` reports how many rows *would* be processed within the remaining
    budget without calling the API or consuming budget.
    """
    result = BackfillResult()
    attempted = 0

    for prop, metrics in rows:
        # Idempotency: skip rows a concurrent live worker already enriched,
        # unless the operator forces a re-run.
        if not force and not mode_is_missing_ai(metrics):
            result.skipped_already_enriched += 1
            continue

        if limit is not None and attempted >= limit:
            break

        if dry_run:
            # Simulate budget without reserving it.
            projected = (result.would_process + 1) * requests_per_property
            if projected > budget.remaining():
                result.budget_exhausted = True
                break
            result.would_process += 1
            attempted += 1
            continue

        if not budget.try_consume(requests_per_property):
            result.budget_exhausted = True
            break

        attempted += 1
        result.requests_consumed += requests_per_property
        try:
            await enrich_fn(prop)
        except Exception as exc:  # noqa: BLE001 - one bad row must not abort
            result.errors += 1
            result.error_ids.append(str(getattr(prop, "id", "?")))
            _log_row_error(prop, exc)
            continue

        result.processed += 1
        result.last_property_id = str(getattr(prop, "id", ""))
        checkpoint.advance(result.last_property_id)
        if on_progress is not None:
            on_progress(result)

        if pace_seconds > 0:
            await sleep_fn(pace_seconds)

    return result


def _log_row_error(prop: Any, exc: Exception) -> None:
    from infra.logging import get_logger

    get_logger(__name__).warning(
        "backfill_row_error",
        property_id=str(getattr(prop, "id", "?")),
        error=str(exc),
    )
