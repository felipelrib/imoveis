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
import time
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


_WINDOW_SECONDS = 24 * 3600


def _parse_iso(raw: Any) -> Optional[datetime]:
    if isinstance(raw, bytes):
        raw = raw.decode()
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


class DailyBudget:
    """Redis-backed request counter enforcing an RPD ceiling over a rolling 24h.

    A **rolling 24-hour window** (counter + window-start stored in a Redis hash)
    rather than a calendar day: the window opens on the first reserved request
    and closes 24h later. This is provider-clock-agnostic — RPD resets on the
    provider's calendar day (an unknown, changeable time), and keeping under the
    budget in *any* rolling 24h is automatically under any calendar-day cap when
    ``daily_limit`` < the provider's RPD. It also makes the auto-wait timing
    exact: :meth:`seconds_until_reset` is simply the time left in the window.
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
        self._key = f"{prefix}:budget"

    def _active_window(self, now: datetime) -> tuple[int, Optional[datetime]]:
        """Return ``(count, window_start)`` for the live window, or ``(0, None)``.

        An expired or absent window reads as empty so the next reservation opens
        a fresh one.
        """
        raw = self._redis.hgetall(self._key) or {}
        decoded = {
            (k.decode() if isinstance(k, bytes) else k): v for k, v in raw.items()
        }
        start = _parse_iso(decoded.get("start"))
        if start is None or (now - start).total_seconds() >= _WINDOW_SECONDS:
            return 0, None
        count = int(decoded.get("count", 0) or 0)
        return count, start

    def consumed(self) -> int:
        return self._active_window(self._now_fn())[0]

    def remaining(self) -> int:
        return max(0, self._daily_limit - self.consumed())

    def try_consume(self, n: int) -> bool:
        """Reserve ``n`` requests; return False (and reserve nothing) if over."""
        if n <= 0:
            return True
        now = self._now_fn()
        count, start = self._active_window(now)
        if count + n > self._daily_limit:
            return False
        if start is None:  # open a fresh window on first reservation
            start = now
        self._redis.hset(
            self._key,
            mapping={"count": count + n, "start": start.isoformat()},
        )
        # Expire well after the window so a stale window can't linger forever.
        self._redis.expire(self._key, _BUDGET_TTL_SECONDS)
        return True

    def seconds_until_reset(self) -> float:
        """Seconds until the current window resets (0 when no window is open)."""
        now = self._now_fn()
        _, start = self._active_window(now)
        if start is None:
            return 0.0
        return max(0.0, _WINDOW_SECONDS - (now - start).total_seconds())


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


def launch_interval_for_rpm(requests_per_property: int, rpm_limit: int) -> float:
    """Min seconds between property launches to stay under ``rpm_limit`` req/min.

    Each property fires ``requests_per_property`` requests, so launching one every
    ``60 * rpp / rpm_limit`` seconds caps the request rate at ``rpm_limit``/min
    regardless of concurrency. Returns 0 when ``rpm_limit`` is non-positive.
    """
    if rpm_limit <= 0:
        return 0.0
    return 60.0 * requests_per_property / rpm_limit


def _run_dry(
    rows: Iterable[Tuple[Any, Any]],
    *,
    budget: DailyBudget,
    requests_per_property: int,
    limit: Optional[int],
    force: bool,
) -> BackfillResult:
    """Count how many rows would be processed within budget — no side effects."""
    result = BackfillResult()
    for prop, metrics in rows:
        if not force and not mode_is_missing_ai(metrics):
            result.skipped_already_enriched += 1
            continue
        if limit is not None and result.would_process >= limit:
            break
        projected = (result.would_process + 1) * requests_per_property
        if projected > budget.remaining():
            result.budget_exhausted = True
            break
        result.would_process += 1
    return result


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
    concurrency: int = 1,
    launch_interval: float = 0.0,
    sleep_fn: SleepFn = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
    on_progress: Optional[Callable[[BackfillResult], None]] = None,
) -> BackfillResult:
    """Enrich candidate ``(property, metrics)`` rows, up to ``concurrency`` at once.

    Stops when the daily budget can no longer fund another property
    (``budget_exhausted``), the optional ``limit`` of attempted properties is
    reached, or the rows run out — safe to invoke again to resume. ``enrich_fn``
    raises on hard failure; the row is counted as an error and the run continues.

    Up to ``concurrency`` properties run in parallel (each is ~3 sequential Gemma
    calls, so parallelism is what lifts throughput). ``launch_interval`` spaces
    successive launches to keep the request rate under the per-minute cap; the
    daily budget still gates total requests.

    ``limit`` caps the number of properties *attempted* this run (skipped rows do
    not count). ``dry_run`` reports how many rows *would* be processed within the
    remaining budget without calling the API or consuming budget.
    """
    if dry_run:
        return _run_dry(
            rows,
            budget=budget,
            requests_per_property=requests_per_property,
            limit=limit,
            force=force,
        )

    result = BackfillResult()
    attempted = 0
    last_launch: Optional[float] = None
    sem = asyncio.Semaphore(max(1, concurrency))
    tasks: list[asyncio.Task] = []

    async def _worker(prop: Any) -> None:
        try:
            await enrich_fn(prop)
        except Exception as exc:  # noqa: BLE001 - one bad row must not abort
            result.errors += 1
            result.error_ids.append(str(getattr(prop, "id", "?")))
            _log_row_error(prop, exc)
        else:
            result.processed += 1
            result.last_property_id = str(getattr(prop, "id", ""))
            checkpoint.advance(result.last_property_id)
            if on_progress is not None:
                on_progress(result)
        finally:
            sem.release()

    for prop, metrics in rows:
        # Idempotency: skip rows a concurrent live worker already enriched,
        # unless the operator forces a re-run.
        if not force and not mode_is_missing_ai(metrics):
            result.skipped_already_enriched += 1
            continue
        if limit is not None and attempted >= limit:
            break

        # Rate-limit launches (RPM smoothing) before reserving budget.
        if launch_interval > 0 and last_launch is not None:
            wait = launch_interval - (clock() - last_launch)
            if wait > 0:
                await sleep_fn(wait)

        if not budget.try_consume(requests_per_property):
            result.budget_exhausted = True
            break

        await sem.acquire()  # bound in-flight properties to ``concurrency``
        attempted += 1
        result.requests_consumed += requests_per_property
        last_launch = clock()
        tasks.append(asyncio.create_task(_worker(prop)))

    if tasks:
        await asyncio.gather(*tasks)
    return result


def _log_row_error(prop: Any, exc: Exception) -> None:
    from infra.logging import get_logger

    get_logger(__name__).warning(
        "backfill_row_error",
        property_id=str(getattr(prop, "id", "?")),
        error=str(exc),
    )
