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

from core.enrichment_rerun import evaluate_candidate, mode_is_missing_ai

# Keep the daily counter around long enough to inspect yesterday's usage.
_BUDGET_TTL_SECONDS = 2 * 24 * 3600
# The attempt ledger has to outlive a multi-day pass; refreshed on every write.
_LEDGER_TTL_SECONDS = 30 * 24 * 3600

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


@dataclass(frozen=True)
class QueueCensus:
    """Honest accounting of the backfill work queue (v0.13-fu3).

    Completion used to be measured as ``total properties - enriched``, but the
    runner only ever fetches **active** rows (``active_only=True``). Inactive
    un-enriched listings — 494 of them on 2026-08-05 — kept that difference
    permanently positive, so the ``remaining == 0`` branch could never fire and a
    finished backfill exited through the "no progress this cycle" safety valve
    instead.

    ``candidates`` is what ``fetch_candidate_rows`` would actually return;
    ``remaining`` further drops the rows the pipeline can never score. The
    denominator to quote a human is :attr:`enrichable`, not ``total_properties``.
    """

    total_properties: int
    enriched: int
    candidates: int
    blocked_no_photos: int = 0
    quarantined: int = 0

    @property
    def blocked_total(self) -> int:
        """Candidate rows fetched but permanently unworkable."""
        return self.blocked_no_photos + self.quarantined

    @property
    def remaining(self) -> int:
        """Rows the runner can still meaningfully attempt."""
        return max(0, self.candidates - self.blocked_total)

    @property
    def enrichable(self) -> int:
        """The truthful denominator: already scored + still workable."""
        return self.enriched + self.remaining

    @property
    def non_enrichable(self) -> int:
        """Rows outside the queue for good — inactive, photo-blocked, quarantined."""
        return max(0, self.total_properties - self.enrichable)

    @property
    def is_complete(self) -> bool:
        return self.remaining == 0

    @property
    def progress_pct(self) -> float:
        """Percent of the *enrichable* set that is scored (100 when there is none)."""
        if self.enrichable <= 0:
            return 100.0
        return 100.0 * self.enriched / self.enrichable

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_properties": self.total_properties,
            "enriched": self.enriched,
            "candidates": self.candidates,
            "blocked_no_photos": self.blocked_no_photos,
            "quarantined": self.quarantined,
            "remaining": self.remaining,
            "enrichable": self.enrichable,
            "non_enrichable": self.non_enrichable,
            "progress_pct": round(self.progress_pct, 2),
        }


def _decode(value: Any) -> Any:
    return value.decode() if isinstance(value, bytes) else value


class AttemptLedger:
    """Persistent per-property attempt counter that retires rows that never clear.

    ``run_backfill`` deliberately does not checkpoint a row it failed on, so
    ``--continuous`` re-fetches it next cycle and spends RPD/TPM on it again —
    forever, if the failure is deterministic. A row can also *succeed* and still
    come back: ``mode=missing`` treats a falsy ``ai_score`` as un-enriched, so an
    enrichment that lands on 0.0 re-queues itself.

    Counting **attempts** rather than only errors retires both shapes. A row that
    enriches normally leaves the candidate set and never reaches the ceiling.
    """

    def __init__(
        self,
        redis: Any,
        *,
        prefix: str,
        max_attempts: int = 3,
        ttl_seconds: int = _LEDGER_TTL_SECONDS,
    ) -> None:
        self._redis = redis
        self._attempts_key = f"{prefix}:attempts"
        self._errors_key = f"{prefix}:last_error"
        self._max_attempts = max(1, int(max_attempts))
        self._ttl = ttl_seconds

    @property
    def max_attempts(self) -> int:
        return self._max_attempts

    def _touch(self, key: str) -> None:
        self._redis.expire(key, self._ttl)

    def attempts(self, property_id: str) -> int:
        raw = _decode(self._redis.hget(self._attempts_key, str(property_id)))
        try:
            return int(raw or 0)
        except (TypeError, ValueError):
            return 0

    def record_attempt(self, property_id: str) -> int:
        """Increment and return this row's attempt count."""
        count = int(self._redis.hincrby(self._attempts_key, str(property_id), 1))
        self._touch(self._attempts_key)
        return count

    def record_error(self, property_id: str, reason: str) -> None:
        """Remember why a row failed, for the quarantine report."""
        self._redis.hset(self._errors_key, str(property_id), str(reason)[:300])
        self._touch(self._errors_key)

    def is_quarantined(self, property_id: str) -> bool:
        return self.attempts(property_id) >= self._max_attempts

    def _all_attempts(self) -> dict[str, int]:
        raw = self._redis.hgetall(self._attempts_key) or {}
        out: dict[str, int] = {}
        for k, v in raw.items():
            try:
                out[_decode(k)] = int(_decode(v) or 0)
            except (TypeError, ValueError):
                continue
        return out

    def quarantined_ids(self) -> list[str]:
        return sorted(
            pid for pid, n in self._all_attempts().items() if n >= self._max_attempts
        )

    def quarantined_count(self) -> int:
        return len(self.quarantined_ids())

    def reason_for(self, property_id: str) -> str:
        reason = _decode(self._redis.hget(self._errors_key, str(property_id)))
        if reason:
            return str(reason)
        return (
            f"no error recorded — still a candidate after "
            f"{self.attempts(property_id)} attempts"
        )

    def quarantine_report(self) -> dict[str, str]:
        return {pid: self.reason_for(pid) for pid in self.quarantined_ids()}

    def clear(self, property_id: str) -> None:
        """Release one row back into the queue (operator retry)."""
        self._redis.hdel(self._attempts_key, str(property_id))
        self._redis.hdel(self._errors_key, str(property_id))

    def reset_all(self) -> None:
        self._redis.delete(self._attempts_key)
        self._redis.delete(self._errors_key)


@dataclass
class CandidatePartition:
    """Candidate rows split into workable work and permanently excluded ids."""

    workable: list[Tuple[Any, Any]] = field(default_factory=list)
    blocked_no_photos: list[str] = field(default_factory=list)
    quarantined: list[str] = field(default_factory=list)

    @property
    def blocked_total(self) -> int:
        return len(self.blocked_no_photos) + len(self.quarantined)


def partition_candidates(
    rows: Iterable[Tuple[Any, Any]],
    *,
    gate_kwargs: dict[str, Any],
    ledger: Optional[AttemptLedger] = None,
    stages: str = "all",
) -> CandidatePartition:
    """Split fetched candidates into workable rows and permanently excluded ones.

    ``fetch_candidate_rows`` applies only the property-level SQL filters; the
    photo gate lives in ``evaluate_candidate`` and the backfill never called it,
    so a gallery-less row would be "enriched" from zero images. Rows the ledger
    has retired are dropped here too, before they can cost any budget.

    A row is counted in exactly one bucket, so the counts sum back to the input.
    """
    part = CandidatePartition()
    quarantined = set(ledger.quarantined_ids()) if ledger is not None else set()
    for prop, metrics in rows:
        pid = str(getattr(prop, "id", ""))
        action, _ = evaluate_candidate(prop, metrics, stages, gate_kwargs)
        if action != "queue":
            part.blocked_no_photos.append(pid)
            continue
        if pid in quarantined:
            part.quarantined.append(pid)
            continue
        part.workable.append((prop, metrics))
    return part


@dataclass
class BackfillResult:
    """Outcome of one backfill invocation."""

    processed: int = 0
    would_process: int = 0
    skipped_already_enriched: int = 0
    # Rows the attempt ledger has retired — re-attempting them only burns budget.
    skipped_quarantined: int = 0
    errors: int = 0
    requests_consumed: int = 0
    budget_exhausted: bool = False
    last_property_id: Optional[str] = None
    error_ids: list[str] = field(default_factory=list)
    # How often (and how long) the TPM limiter held launches back — the signal
    # that tokens, not requests, are the binding constraint.
    tpm_waits: int = 0
    tpm_wait_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "processed": self.processed,
            "would_process": self.would_process,
            "skipped_already_enriched": self.skipped_already_enriched,
            "skipped_quarantined": self.skipped_quarantined,
            "errors": self.errors,
            "requests_consumed": self.requests_consumed,
            "budget_exhausted": self.budget_exhausted,
            "last_property_id": self.last_property_id,
            "tpm_waits": self.tpm_waits,
            "tpm_wait_seconds": round(self.tpm_wait_seconds, 1),
        }


def estimate_eta_days(remaining_properties: int, daily_property_rate: float) -> float:
    """Whole-and-fractional days to finish at ``daily_property_rate`` props/day."""
    if daily_property_rate <= 0:
        return float("inf")
    return remaining_properties / daily_property_rate


class TokenBudget:
    """Sliding-60s token limiter that keeps the run under the provider's TPM cap.

    The daily budget gates *requests* and the launch interval gates *requests per
    minute*, but the free-tier ceiling that actually bites on image-heavy
    enrichment is **tokens per minute**: one property costs ~7,000 tokens
    (measured on ``gemma-4-31b-it``: visual with 8×768px images ≈ 3,538, sentiment
    ≈ 1,706, verdict ≈ 1,706), so 16K TPM allows only ~2.3 properties/min. Relying
    on the client's reactive 429 backoff was not enough — it throttles only *after*
    the violation and every retry silently consumes daily request quota.

    This reserves a property's estimated tokens *before* it launches and makes the
    caller wait until the trailing 60-second window has room, so the cap is
    respected proactively and concurrency self-regulates.
    """

    WINDOW_SECONDS = 60.0

    def __init__(
        self,
        *,
        tpm_limit: int,
        tokens_per_property: int,
        safety_margin: float = 0.9,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._effective_limit = max(1.0, float(tpm_limit) * safety_margin)
        self._tokens_per_property = max(1, int(tokens_per_property))
        self._clock = clock
        # (timestamp, tokens) reservations inside the trailing window.
        self._events: list[tuple[float, int]] = []

    @property
    def tokens_per_property(self) -> int:
        return self._tokens_per_property

    def _prune(self, now: float) -> None:
        cutoff = now - self.WINDOW_SECONDS
        self._events = [(ts, tok) for ts, tok in self._events if ts > cutoff]

    def used(self) -> int:
        """Tokens reserved within the trailing 60s window."""
        self._prune(self._clock())
        return sum(tok for _, tok in self._events)

    def seconds_until_room(self, tokens: Optional[int] = None) -> float:
        """Seconds to wait before ``tokens`` fit in the window (0 if they fit now)."""
        need = self._tokens_per_property if tokens is None else int(tokens)
        now = self._clock()
        self._prune(now)
        used = sum(tok for _, tok in self._events)
        if used + need <= self._effective_limit:
            return 0.0
        # Wait for the oldest reservations to age out until `need` fits.
        freed = 0.0
        for ts, tok in self._events:  # oldest first
            freed += tok
            if used - freed + need <= self._effective_limit:
                return max(0.0, ts + self.WINDOW_SECONDS - now)
        # Even an empty window cannot fit it (property costs more than the cap):
        # let it through once the window drains rather than deadlocking.
        if self._events:
            return max(0.0, self._events[-1][0] + self.WINDOW_SECONDS - now)
        return 0.0

    def reserve(self, tokens: Optional[int] = None) -> None:
        """Record a reservation. Call after waiting ``seconds_until_room``."""
        need = self._tokens_per_property if tokens is None else int(tokens)
        self._events.append((self._clock(), need))


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
    ledger: Optional[AttemptLedger] = None,
) -> BackfillResult:
    """Count how many rows would be processed within budget — no side effects."""
    result = BackfillResult()
    quarantined = set(ledger.quarantined_ids()) if ledger is not None else set()
    for prop, metrics in rows:
        if not force and not mode_is_missing_ai(metrics):
            result.skipped_already_enriched += 1
            continue
        if str(getattr(prop, "id", "")) in quarantined:
            result.skipped_quarantined += 1
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
    token_budget: Optional[TokenBudget] = None,
    ledger: Optional[AttemptLedger] = None,
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
    calls, so parallelism is what lifts throughput). Three independent governors
    keep the run inside the provider's limits: the daily ``budget`` (RPD),
    ``launch_interval`` (RPM), and ``token_budget`` (TPM — usually the binding one
    for image-heavy enrichment, which throttles launches so concurrency
    self-regulates).

    ``limit`` caps the number of properties *attempted* this run (skipped rows do
    not count). ``dry_run`` reports how many rows *would* be processed within the
    remaining budget without calling the API or consuming budget.

    An optional ``ledger`` makes repeat failures terminal: every launched row
    records an attempt, errors record their reason, and a row that has been
    attempted ``max_attempts`` times without leaving the candidate set is skipped
    for free from then on instead of burning budget every cycle.
    """
    if dry_run:
        return _run_dry(
            rows,
            budget=budget,
            requests_per_property=requests_per_property,
            limit=limit,
            force=force,
            ledger=ledger,
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
            if ledger is not None:
                ledger.record_error(str(getattr(prop, "id", "?")), str(exc))
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
        # Rows retired by the ledger cost nothing: no budget, no tokens, no call.
        pid = str(getattr(prop, "id", ""))
        if ledger is not None and ledger.is_quarantined(pid):
            result.skipped_quarantined += 1
            continue
        if limit is not None and attempted >= limit:
            break

        # Rate-limit launches (RPM smoothing) before reserving budget.
        if launch_interval > 0 and last_launch is not None:
            wait = launch_interval - (clock() - last_launch)
            if wait > 0:
                await sleep_fn(wait)

        # Proactively stay under the tokens-per-minute ceiling: wait until this
        # property's estimated tokens fit the trailing 60s window, then reserve.
        if token_budget is not None:
            tpm_wait = token_budget.seconds_until_room()
            if tpm_wait > 0:
                result.tpm_waits += 1
                result.tpm_wait_seconds += tpm_wait
                await sleep_fn(tpm_wait)
            token_budget.reserve()

        if not budget.try_consume(requests_per_property):
            result.budget_exhausted = True
            break

        await sem.acquire()  # bound in-flight properties to ``concurrency``
        if ledger is not None:
            # Count the attempt, not just failures: a row that enriches to a
            # falsy ai_score stays a ``mode=missing`` candidate and would
            # otherwise be re-fetched every cycle forever.
            ledger.record_attempt(pid)
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
