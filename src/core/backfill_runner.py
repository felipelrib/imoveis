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
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Iterable, Optional, Tuple

from core.enrichment import EnrichmentTaskClass
from core.enrichment_rerun import (
    STAGES_ALL,
    STAGES_VERDICT_ONLY,
    STAGES_VISUAL_SENTIMENT,
    evaluate_candidate,
    mode_is_missing_ai,
)

# Keep the daily counter around long enough to inspect yesterday's usage.
_BUDGET_TTL_SECONDS = 2 * 24 * 3600
# The attempt ledger has to outlive a multi-day pass; refreshed on every write.
_LEDGER_TTL_SECONDS = 30 * 24 * 3600
# A pause/stop request outlives the runner that has to observe it (an operator
# may pause a run that is mid-sleep across a budget window), but never forever.
_CONTROL_REQUEST_TTL_SECONDS = 7 * 24 * 3600
# Published state is a liveness signal: it must expire so a crashed runner reads
# back as ``idle`` instead of a stuck ``running``.
_STATE_TTL_SECONDS = 120
# How often a working run re-publishes ``running``. Strictly below the state TTL
# (a quarter of it), so ``--status`` and story 1.5's API never read a live run
# back as ``idle`` just because the single startup publish aged out.
_STATE_REFRESH_SECONDS = _STATE_TTL_SECONDS / 4

EnrichFn = Callable[[Any], Awaitable[None]]
SleepFn = Callable[[float], Awaitable[None]]


def _warn_non_atomic_fallback(owner: Any, surface: str) -> None:
    """Say once, per object, that the non-atomic Redis path was selected.

    The lease CAS and the budget reservation downgrade to a multi-round-trip
    sequence whenever the injected client exposes no callable ``eval``. That is
    intended for test doubles, but the sniff is silent: any production client
    that lacked ``eval`` (a wrapper, a restricted command set) would quietly
    stop enforcing mutual exclusion and the RPD ceiling with nothing in the log
    to say so. A guarantee this load-bearing does not get downgraded in silence.
    """
    if getattr(owner, "_fallback_warned", False):
        return
    setattr(owner, "_fallback_warned", True)
    from infra.logging import get_logger

    get_logger(__name__).warning(
        "backfill_non_atomic_redis_fallback",
        surface=surface,
        detail=(
            "redis client exposes no callable eval(); atomicity is NOT enforced "
            "for this surface"
        ),
    )


def _utc_today(now_fn: Callable[[], datetime]) -> date:
    return now_fn().astimezone(timezone.utc).date()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


_WINDOW_SECONDS = 24 * 3600


def _decode(value: Any) -> Any:
    return value.decode() if isinstance(value, bytes) else value


def _reply_is_true(raw: Any) -> bool:
    """Interpret a Lua ``return 1`` / ``return 0`` reply as a boolean.

    A bare ``bool(raw)`` fallback is a trap: a client that hands back the reply
    as bytes turns a *refusal* (``b"0"``) into ``True``, which for a lease renew
    means the runner believes it still owns a lease someone else took over —
    two writers, silently. Decode first, then compare.
    """
    value = _decode(raw)
    if isinstance(value, bool):
        return value
    try:
        return int(value) == 1
    except (TypeError, ValueError):
        return bool(value)


def _parse_iso(raw: Any) -> Optional[datetime]:
    if isinstance(raw, bytes):
        raw = raw.decode()
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


# Window-roll + reserve + limit-check + rollback in one atomic step. Doing the
# roll as a separate round-trip from the increment (as the first cut did) lets
# two writers that both read a stale window each stamp ``count=0`` and wipe the
# other's reservation, so the counter can drift *below* what was really spent
# and the RPD cap is overshot. Redis evaluates this whole script atomically.
#
# ``start_epoch`` is the machine-comparable twin of the human-readable ``start``
# ISO stamp (Lua cannot parse ISO-8601): both are written together and always
# describe the same instant. A hash written before v0.13-s1.3 carries only
# ``start``; :meth:`DailyBudget._migrate_start_epoch` backfills the twin from it
# before the first eval, so an upgrade mid-window does not silently roll the
# window (which would hand the run a second full day's budget inside one real
# 24h and push the account past the provider's RPD).
_BUDGET_RESERVE_LUA = """
local n = tonumber(ARGV[1])
local now = tonumber(ARGV[2])
local window = tonumber(ARGV[3])
local limit = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])
local now_iso = ARGV[6]
local start_epoch = tonumber(redis.call('hget', KEYS[1], 'start_epoch'))
local opened = 0
local count
if (start_epoch == nil) or ((now - start_epoch) >= window) then
  redis.call('hset', KEYS[1], 'count', n, 'start', now_iso, 'start_epoch', now)
  opened = 1
  count = n
else
  count = redis.call('hincrby', KEYS[1], 'count', n)
end
if count > limit then
  if opened == 1 then
    redis.call('del', KEYS[1])
  else
    redis.call('hincrby', KEYS[1], 'count', -n)
  end
  return 0
end
redis.call('expire', KEYS[1], ttl)
return 1
"""


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
        self._epoch_migrated = False

    def _migrate_start_epoch(self) -> None:
        """Give a pre-v0.13-s1.3 budget hash the ``start_epoch`` Lua reads.

        Without this a live window written by the old code looks like *no*
        window to :data:`_BUDGET_RESERVE_LUA`, which would roll it and grant a
        second full day's budget inside one real 24 hours. Checked once per
        runner: after the first reservation the field is always present.
        """
        if self._epoch_migrated:
            return
        self._epoch_migrated = True
        raw = self._redis.hgetall(self._key) or {}
        decoded = {_decode(k): _decode(v) for k, v in raw.items()}
        if not decoded or decoded.get("start_epoch"):
            return
        start = _parse_iso(decoded.get("start"))
        if start is None:
            return
        self._redis.hset(self._key, mapping={"start_epoch": start.timestamp()})

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
        """Reserve ``n`` requests; reserve nothing when that would pass the cap.

        Two branches, and they differ in their guarantees:

        * **Atomic** (the injected client exposes a callable ``eval``, i.e. every
          real Redis client): :data:`_BUDGET_RESERVE_LUA` does the window roll,
          the increment, the limit check and the rollback in one server-side
          step, so two runners (or two coroutines) racing the same counter can
          neither overshoot the provider's RPD cap nor wipe each other's
          reservation by both stamping a fresh ``count=0``.
        * **Fallback** (test doubles and any client without ``eval``): the same
          sequence as separate round-trips. It is *not* atomic — an interleaved
          window roll can still lose a reservation — and exists only so the pure
          logic stays testable against a dict-backed fake.

        Either way, a reservation that opened a fresh window and then failed the
        limit check deletes the key rather than leaving a phantom zero-count
        window behind: such a window would report ~24h of
        :meth:`seconds_until_reset`, which is exactly how ``--continuous`` ended
        up sleeping a day at a time on a limit it could never satisfy
        (v0.13-s1.3, AC-1).
        """
        if n <= 0:
            return True
        now = self._now_fn()
        eval_fn = getattr(self._redis, "eval", None)
        if callable(eval_fn):
            self._migrate_start_epoch()
            raw = eval_fn(
                _BUDGET_RESERVE_LUA,
                1,
                self._key,
                int(n),
                now.timestamp(),
                _WINDOW_SECONDS,
                self._daily_limit,
                _BUDGET_TTL_SECONDS,
                now.isoformat(),
            )
            return _reply_is_true(raw)

        _warn_non_atomic_fallback(self, "daily budget reservation")
        _, start = self._active_window(now)
        opened = start is None
        if opened:
            # No live window: open a fresh one *before* incrementing so the
            # increment can never land on a stale (expired-window) count.
            self._redis.hset(
                self._key,
                mapping={
                    "count": 0,
                    "start": now.isoformat(),
                    "start_epoch": now.timestamp(),
                },
            )
        count = int(self._redis.hincrby(self._key, "count", n) or 0)
        if count > self._daily_limit:
            if opened:
                # Never leave a window this call opened and could not use.
                self._redis.delete(self._key)
            else:
                self._redis.hincrby(self._key, "count", -n)  # give it back
            return False
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


class MigrationGate:
    """Read-only view of the migration-held exclusion key ``<prefix>:migrating``.

    ``migrate-primary.sh`` takes this key (``SET NX EX`` with a per-invocation
    token) **before** it probes the advisory ``:active`` heartbeat, and the
    runner beats ``:active`` **before** it reads this key. Set-then-check on
    both sides is what makes them mutually exclusive: whichever wrote first, at
    least one of the two sees the other's key, so a runner can never launch a
    row into a schema that ``alembic upgrade`` is halfway through (DW-3/DW-4).

    The runner only ever *reads*. The key belongs to the migration and expires
    on its own TTL, so a runner that cleared it would hand itself a green light
    while the upgrade is still running.
    """

    def __init__(self, redis: Any, *, prefix: str) -> None:
        self._redis = redis
        self._key = f"{prefix}:migrating"

    @property
    def key(self) -> str:
        return self._key

    def holder_token(self) -> Optional[str]:
        """Token of the migration holding the key, or None when it is free."""
        return _decode(self._redis.get(self._key)) or None

    def is_migrating(self) -> bool:
        # ``get``, not ``exists``: the key always carries a non-empty token, so
        # the two are equivalent here — but ``get`` is what every other reader
        # in this module (and every Redis double the tests use) implements, and
        # it is what lets a refusal name the holding token.
        return bool(self.holder_token())


class BackfillState(str, Enum):
    """Published control state of the backfill runner.

    This is the wire vocabulary the CLI writes and stories 1.5/1.6 (admin API,
    UI) read. It is *control* state only — never a second progress metric.
    """

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    BACKING_OFF = "backing-off"
    # A primary migration holds the DB (``migrate-primary.sh``). Distinct from
    # ``BACKING_OFF``, which in this vocabulary means "the provider refused on
    # quota": a runner waiting out a migration has hit no quota ceiling at all,
    # and telling an operator (or stories 1.5/1.6) otherwise sends them to the
    # Gemini dashboard for a problem that lives in their own terminal.
    BLOCKED = "blocked"


# Owner-token CAS scripts. Redis evaluates each atomically, so a runner whose
# lease already expired (and was taken over) can never extend or delete its
# successor's lease between the GET and the EXPIRE/DEL.
_LEASE_RENEW_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""

_LEASE_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


class BackfillLease:
    """Single-instance mutual exclusion for the backfill runner (AC-1).

    Distinct from :class:`Heartbeat`: the heartbeat (``<prefix>:active``) is the
    *advisory* signal ``migrate-primary.sh`` observes and stays exactly as it is.
    This lease (``<prefix>:lease``) is the *enforcing* key — ``SET key token NX
    EX ttl`` is atomic, so exactly one runner wins, and ``renew``/``release`` are
    owner-token compare-and-swap. The TTL (not a shutdown hook) is what recovers
    the lease after a hard kill, so a crashed run self-heals without an operator.

    A companion ``<prefix>:lease:meta`` hash carries human-facing provenance
    (who holds it, since when, last seen) for the refusal message. It is
    advisory decoration: correctness rests entirely on the token in the lease key.
    """

    def __init__(
        self,
        redis: Any,
        *,
        prefix: str,
        ttl_seconds: int = 900,
        token: Optional[str] = None,
        owner: str = "",
        now_fn: Callable[[], datetime] = _now_utc,
    ) -> None:
        self._redis = redis
        self._key = f"{prefix}:lease"
        self._meta_key = f"{prefix}:lease:meta"
        self._ttl = max(1, int(ttl_seconds))
        self._token = token or uuid.uuid4().hex
        self._owner = owner
        self._now_fn = now_fn

    @property
    def key(self) -> str:
        return self._key

    @property
    def token(self) -> str:
        return self._token

    @property
    def ttl_seconds(self) -> int:
        return self._ttl

    def _write_meta(self, *, acquired: bool) -> None:
        """Refresh the human-facing provenance hash. Never raises.

        The meta hash is decoration — correctness rests entirely on the token in
        the lease key — but it was written *after* the atomic ``SET NX``, so a
        Redis blip in between propagated out of :meth:`acquire` with the lease
        already taken and no ``finally`` yet in place to hand it back: the next
        run was refused for the whole TTL over a failed cosmetic write. Same for
        :meth:`renew`, whose caller is the launch loop.
        """
        stamp = self._now_fn().isoformat()
        mapping = {"token": self._token, "last_seen": stamp}
        if acquired:
            mapping["acquired_at"] = stamp
            mapping["owner"] = self._owner or "unknown"
        try:
            self._redis.hset(self._meta_key, mapping=mapping)
            self._redis.expire(self._meta_key, self._ttl * 4)
        except Exception as exc:  # noqa: BLE001 - decoration never fails a lease
            _log_lease_meta_failed(exc)

    def acquire(self) -> bool:
        """Atomically take the lease. False means someone else holds it."""
        ok = bool(self._redis.set(self._key, self._token, nx=True, ex=self._ttl))
        if ok:
            self._write_meta(acquired=True)
        return ok

    def _cas(self, script: str, *args: Any) -> bool:
        """Run an owner-token CAS, atomically when the client supports ``eval``."""
        eval_fn = getattr(self._redis, "eval", None)
        if callable(eval_fn):
            return _reply_is_true(eval_fn(script, 1, self._key, self._token, *args))
        # Fallback: guarded check-then-act. Not atomic, but still token-guarded —
        # the window is bounded by the lease TTL, which is minutes wide.
        _warn_non_atomic_fallback(self, "lease CAS")
        if _decode(self._redis.get(self._key)) != self._token:
            return False
        if script is _LEASE_RELEASE_LUA:
            self._redis.delete(self._key)
            return True
        # ``EXPIRE`` returns 0 when the key is already gone: the lease expired
        # between the GET and here. Reporting that as a successful renew is how
        # a runner keeps writing on a lease a successor may already hold.
        return bool(self._redis.expire(self._key, self._ttl))

    def renew(self) -> bool:
        """Extend the TTL iff this process still owns the lease."""
        ok = self._cas(_LEASE_RENEW_LUA, self._ttl)
        if ok:
            self._write_meta(acquired=False)
        return ok

    def release(self) -> bool:
        """Drop the lease iff this process still owns it."""
        return self._cas(_LEASE_RELEASE_LUA)

    def is_held_by_self(self) -> bool:
        return _decode(self._redis.get(self._key)) == self._token

    def holder(self) -> Optional[dict[str, Any]]:
        """Who holds the lease right now, or None when it is free."""
        token = _decode(self._redis.get(self._key))
        if not token:
            return None
        raw = self._redis.hgetall(self._meta_key) or {}
        meta = {_decode(k): _decode(v) for k, v in raw.items()}
        if meta.get("token") != token:
            meta = {}  # stale decoration from a previous holder — ignore it
        last_seen = _parse_iso(meta.get("last_seen"))
        age = None
        if last_seen is not None:
            age = max(0.0, (self._now_fn() - last_seen).total_seconds())
        return {
            "token": str(token),
            "owner": meta.get("owner", "unknown"),
            "acquired_at": meta.get("acquired_at"),
            "last_seen": meta.get("last_seen"),
            "seconds_since_last_seen": age,
            "is_self": str(token) == self._token,
        }


class BackfillControl:
    """Pause / resume / stop requests plus the published runner state.

    Requests are single keys (``<prefix>:control:pause`` / ``:stop``) rather than
    a queue: they are *levels*, not events, so a second pause is idempotent and a
    runner that starts later still observes an outstanding request. The state key
    is published with a short TTL, so a crashed runner decays to ``idle``.

    Story 1.5's admin endpoints construct the same object against the same keys —
    one control path, never a second one (AD-13).
    """

    def __init__(
        self,
        redis: Any,
        *,
        prefix: str,
        state_ttl_seconds: int = _STATE_TTL_SECONDS,
        request_ttl_seconds: int = _CONTROL_REQUEST_TTL_SECONDS,
    ) -> None:
        self._redis = redis
        self._pause_key = f"{prefix}:control:pause"
        self._stop_key = f"{prefix}:control:stop"
        self._state_key = f"{prefix}:state"
        self._state_ttl = max(1, int(state_ttl_seconds))
        self._request_ttl = max(1, int(request_ttl_seconds))

    @property
    def state_ttl_seconds(self) -> int:
        return self._state_ttl

    @property
    def refresh_interval_seconds(self) -> float:
        """How often a live runner must re-publish to keep the state key alive.

        Derived from *this* control's TTL rather than read from the module
        constant: a caller that constructs the control with a shorter
        ``state_ttl_seconds`` (story 1.5 does construct its own) would otherwise
        refresh on the default cadence and let the key expire under a live run.
        """
        return max(1.0, self._state_ttl / 4)

    def request_pause(self) -> None:
        self._redis.set(self._pause_key, "1", ex=self._request_ttl)

    def request_resume(self) -> None:
        """Undo a pause **and** a pending stop — "resume" means both.

        Clearing only the pause key left an outstanding ``--stop`` in force, so
        the runner resumed and immediately stopped again while the caller was
        told it would continue. The CLI worked around this locally; story 1.5's
        endpoints call *this* method, so the semantics belong here — one control
        path, never a second one (AD-13).
        """
        self._redis.delete(self._pause_key)
        self._redis.delete(self._stop_key)

    def clear_stop(self) -> None:
        """Drop a stop request that has been served.

        A honored stop that stays set is reported as still-pending for the whole
        request TTL, and the next start announces it as an operator request being
        discarded — when it had in fact already been carried out.
        """
        self._redis.delete(self._stop_key)

    def request_stop(self) -> None:
        self._redis.set(self._stop_key, "1", ex=self._request_ttl)

    def clear_requests(self) -> None:
        """Drop stale pause/stop requests (a fresh run starts unencumbered)."""
        self._redis.delete(self._pause_key)
        self._redis.delete(self._stop_key)

    def is_paused(self) -> bool:
        return bool(self._redis.get(self._pause_key))

    def should_stop(self) -> bool:
        return bool(self._redis.get(self._stop_key))

    def publish_state(self, state: BackfillState) -> None:
        self._redis.set(self._state_key, BackfillState(state).value, ex=self._state_ttl)

    def state(self) -> BackfillState:
        raw = _decode(self._redis.get(self._state_key))
        try:
            return BackfillState(raw)
        except ValueError:
            return BackfillState.IDLE


# The task classes a cloud backfill drives by default: exactly the three stages
# ``run_enrichment`` performs. VALUATION is statistical (no model call) and
# EMBEDDING is never cloud-eligible (vector-space symmetry).
DEFAULT_BACKFILL_SCOPE = frozenset(
    {
        EnrichmentTaskClass.VISUAL,
        EnrichmentTaskClass.SENTIMENT,
        EnrichmentTaskClass.DEAL_VERDICT,
    }
)

# Scope (story 1.1 vocabulary) → the legacy ``stages`` literal that
# ``fetch_candidate_rows`` / ``run_enrichment`` still speak. The translation
# lives here, at the edge, so the runner and CLI only ever handle task classes.
_STAGES_BY_SCOPE: dict[frozenset, str] = {
    DEFAULT_BACKFILL_SCOPE: STAGES_ALL,
    frozenset(
        {EnrichmentTaskClass.VISUAL, EnrichmentTaskClass.SENTIMENT}
    ): STAGES_VISUAL_SENTIMENT,
    frozenset({EnrichmentTaskClass.DEAL_VERDICT}): STAGES_VERDICT_ONLY,
}


def parse_task_classes(raw: Any) -> frozenset:
    """Parse a comma-separated string (or iterable) into task classes."""
    items = raw.split(",") if isinstance(raw, str) else list(raw or [])
    known = ", ".join(tc.value for tc in EnrichmentTaskClass)
    out = set()
    for item in items:
        name = str(_decode(item)).strip().lower()
        if not name:
            continue
        try:
            out.add(EnrichmentTaskClass(name))
        except ValueError as exc:
            raise ValueError(
                f"unknown enrichment task class '{name}' (expected one of {known})"
            ) from exc
    if not out:
        raise ValueError(f"no enrichment task classes given (expected one of {known})")
    return frozenset(out)


def stages_for_task_classes(task_classes: Iterable) -> str:
    """Translate a backfill scope onto the supported ``stages`` literal."""
    scope = frozenset(EnrichmentTaskClass(tc) for tc in task_classes)
    if not scope:
        raise ValueError("empty backfill scope: at least one task class is required")
    try:
        return _STAGES_BY_SCOPE[scope]
    except KeyError:
        supported = " | ".join(
            "{" + ", ".join(sorted(tc.value for tc in combo)) + "}"
            for combo in _STAGES_BY_SCOPE
        )
        raise ValueError(
            "unsupported backfill scope "
            "{" + ", ".join(sorted(tc.value for tc in scope)) + "}"
            f"; supported combinations are {supported}"
        ) from None


# Substrings that identify a provider quota/rate-limit refusal in an exception
# the adapter layer did not tag. The duck-typed flag is the contract; this is the
# safety net for a transport that raises a plain error.
_QUOTA_MARKERS = (
    "resource_exhausted",
    "quota exceeded",
    "quota exhausted",
    "too many requests",
    "rate limit exceeded",
)


def is_quota_exhausted(exc: BaseException) -> bool:
    """True when ``exc`` means the provider's quota/rate limit is spent.

    Duck-typed on purpose: ``src/core`` must not import ``adapters`` (AD-1), so
    the distinguished ``AIQuotaExhaustedError`` is recognised by its
    ``is_quota_exhausted`` class attribute (and, as a fallback, its class name /
    message) rather than by ``isinstance``.
    """
    if getattr(exc, "is_quota_exhausted", False):
        return True
    if type(exc).__name__ == "AIQuotaExhaustedError":
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _QUOTA_MARKERS)


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

    def rollback_attempt(self, property_id: str) -> int:
        """Undo one recorded attempt and return the remaining count.

        A row whose call died on a provider quota refusal was never really
        attempted — nothing was scored and nothing was written — so charging it
        an attempt would march an innocent row towards quarantine across a
        multi-day run that merely ran out of budget (v0.13-s1.3, AC-2).
        """
        count = int(self._redis.hincrby(self._attempts_key, str(property_id), -1) or 0)
        if count <= 0:
            self._redis.hdel(self._attempts_key, str(property_id))
            return 0
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
    # The provider refused on quota: back off, do not treat rows as failed.
    quota_exhausted: bool = False
    # An operator asked the run to stop (CLI flag, signal, or story 1.5's API).
    stopped: bool = False
    # The single-instance lease was lost mid-run (renew() came back False):
    # another runner may already own the queue, so this one stopped launching
    # rather than become a second writer.
    lease_lost: bool = False
    # A primary migration holds ``<prefix>:migrating``: this run stopped
    # launching rather than write against a schema mid-upgrade. Distinct from
    # ``stopped`` — nobody asked it to end, and the caller may simply wait.
    migration_blocked: bool = False
    # Wall-clock seconds the launch loop spent held by a pause request.
    paused_seconds: float = 0.0
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
            "quota_exhausted": self.quota_exhausted,
            "stopped": self.stopped,
            "lease_lost": self.lease_lost,
            "migration_blocked": self.migration_blocked,
            "paused_seconds": round(self.paused_seconds, 1),
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
    control: Optional[BackfillControl] = None,
    lease: Optional[BackfillLease] = None,
    is_quota_error: Optional[Callable[[BaseException], bool]] = is_quota_exhausted,
    is_migrating: Optional[Callable[[], bool]] = None,
    pause_poll_seconds: float = 2.0,
    lease_renew_interval: Optional[float] = None,
    lease_sleep_fn: SleepFn = asyncio.sleep,
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

    An optional ``control`` makes the run interruptible: a pause request holds
    the launch loop (already-launched rows still finish) and a stop request ends
    it, both without losing the checkpoint.

    An optional ``lease`` is renewed **here**, never by the caller's
    ``on_progress`` hook (that hook only fired on rows, so a storm of failing
    rows or a long pause could let the lease lapse and a second runner start).
    Four sites renew it, and all four stay:

    * a background timer task, every ``lease_renew_interval`` seconds (default
      ``lease.ttl_seconds / 3``, and never longer than that — a slower cadence
      would reinstate the very lapse this exists to prevent — slept with
      ``lease_sleep_fn``, which is deliberately *not* the loop's ``sleep_fn``
      so injecting one does not perturb the launch loop's pacing). This
      is the only renewal that is independent of what the loop is doing, so it
      is what covers a *single row slower than the TTL*, the launch-interval
      sleep, the TPM wait, ``sem.acquire()`` and the closing drain (DW-6). It
      is created only when a ``lease`` was supplied and is cancelled after the
      drain, so it can never outlive the run — nor swallow its exception.
    * once per launch-loop iteration and once per pause poll: those calls are
      also the loop's *stop* decision, not merely a renewal.
    * once per finished row, from the worker's ``finally``, which also refreshes
      the published control state (a tighter TTL than the lease's).

    When ``renew()`` returns ``False`` this process no longer owns the lease:
    another runner may already be working the same queue, so launching anything
    further would make this a second writer. It stops launching immediately —
    at the launch-loop head *and* again right after ``sem.acquire()``, since the
    timer can lose the lease while the loop is parked there — flags
    :attr:`BackfillResult.lease_lost`, and lets already-launched rows drain. A
    ``renew()`` that *raises* inside the timer is logged and ignored: a Redis
    blip is bookkeeping, not a lost lease, and must never abort a run.

    ``is_quota_error`` classifies a row
    failure as *provider quota spent* rather than *this row is bad*: such a row
    costs no error, no ledger attempt and no checkpoint advance — nothing was
    written for it — and the run stops launching so the caller can back off
    (v0.13-s1.3, AC-2). Pass ``is_quota_error=None`` to disable the distinction.

    ``is_migrating`` is a plain predicate (usually
    :meth:`MigrationGate.is_migrating`) answering "is a primary migration
    holding the exclusion key right now?". It is polled at the head of the
    launch loop and on every pause poll, and a ``True`` stops launching with
    :attr:`BackfillResult.migration_blocked` — *not* ``stopped``: nobody asked
    this run to end, the checkpoint is untouched, and the caller is free to wait
    the migration out and come back.
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
    # A non-positive poll would turn the paused loop into a Redis busy-spin.
    # ``AppConfig`` constrains the CLI's value, but this is a public core
    # function story 1.5 calls directly — it defends its own loop.
    poll_seconds = max(0.05, float(pause_poll_seconds))

    last_state_publish = clock()
    current_state = BackfillState.IDLE
    state_refresh_seconds = (
        control.refresh_interval_seconds
        if control is not None
        else _STATE_REFRESH_SECONDS
    )

    def _publish(state: BackfillState) -> None:
        nonlocal last_state_publish, current_state
        # Once the lease is gone the state key describes whoever took it over.
        # The background timer can flag that mid-row, so rows still draining
        # (and a pause that ends right after) would otherwise stamp *our*
        # liveness over the successor's — the same reason the closing publish
        # below is guarded.
        if control is not None and not result.lease_lost:
            control.publish_state(state)
            current_state = state
            last_state_publish = clock()

    def _refresh_state() -> None:
        """Keep the published state alive while the run is alive.

        The state key has a short TTL so a crashed runner decays to ``idle``;
        publishing it only once therefore made any run of real length read back
        as ``idle`` from ``--status`` and story 1.5's API. It re-publishes
        *whatever the current state is* — ``running``, ``paused`` or
        ``backing-off`` — because this is also driven from a worker's ``finally``
        (see :func:`_tick_lease`), which must not stamp ``running`` over a
        deliberate pause or a provider back-off.
        """
        if control is not None and clock() - last_state_publish >= state_refresh_seconds:
            _publish(current_state)

    def _lease_held() -> bool:
        """Renew the lease. False = we lost it; stop launching immediately."""
        if lease is None:
            return True
        # A lost lease is terminal — this run never re-acquires one. Re-running
        # the CAS from every draining row (and from the timer) would only spend
        # calls on a key someone else owns and repeat the loss warning once per
        # drained row.
        if result.lease_lost:
            return False
        if lease.renew():
            return True
        result.lease_lost = True
        _log_lease_lost()
        return False

    def _migration_holds() -> bool:
        """True = a primary migration owns the DB; stop launching immediately."""
        if is_migrating is None or not is_migrating():
            return False
        result.migration_blocked = True
        _log_migration_blocked()
        return True

    def _tick_lease() -> None:
        """Renew the lease and refresh the state from a worker's ``finally``.

        Never raises. The launch loop stops renewing the moment it breaks, so
        the final ``gather`` drain — and any row that outlives the loop — ran on
        a lease nobody was refreshing. The published state has the same problem
        and a tighter deadline: the loop refreshes it once per launch, so a
        single row slower than the state TTL (three cloud calls, each with
        client-side retries, is easily that) let a live run read back as
        ``idle``. A Redis blip here must not abandon in-flight rows, so the
        failure is logged rather than propagated.
        """
        try:
            if lease is not None:
                _lease_held()
            _refresh_state()
        except Exception as exc:  # noqa: BLE001 - bookkeeping never aborts a run
            _log_lease_tick_failed(exc)

    # A third of the TTL is the same cadence the migration watchdog and the
    # CLI's sync sleep loops use: two consecutive misses still leave a margin.
    # The ceiling is what keeps the knob from lying — an interval at or beyond
    # the TTL would reinstate DW-6 silently — and the floor guards an explicitly
    # passed non-positive value, which would turn the timer into a busy-spin.
    _default_interval = lease.ttl_seconds / 3.0 if lease is not None else 0.0
    renew_interval = (
        _default_interval
        if lease_renew_interval is None
        else float(lease_renew_interval)
    )
    if lease is not None:
        renew_interval = min(renew_interval, _default_interval)
    renew_interval = max(0.05, renew_interval)

    async def _renew_lease_periodically() -> None:
        """Renew the lease on a timer, independent of the launch loop (DW-6).

        Every other renewal is event-driven — per launch-loop iteration, per
        pause poll, per finished row — so nothing refreshed the lease *while* a
        row was in flight. One property whose enrichment outlives the TTL let
        the lease lapse under a live writer and a second runner take over the
        same queue.

        It never calls ``clock()`` or ``_refresh_state()``: the published state
        belongs to the loop's own cadence, and the injected clocks the unit
        tests use are finite sequences a timer would exhaust. The extra
        ``asyncio.sleep(0)`` is a real yield point even when the injected sleep
        does not suspend, so this loop can never starve the run it protects.

        It is a coroutine on the run's own event loop, so "independent of the
        launch loop" means *not driven by it* — not preemptive: a blocking
        section inside ``enrich_fn`` (or a slow Redis round-trip) delays the
        tick exactly as it delays everything else. The TTL/3 cadence is the
        margin that absorbs that. It cuts both ways: ``lease.renew()`` is a
        *synchronous* client call, so every tick briefly blocks the loop —
        including the rows it is protecting — for one Redis round trip.

        The whole body is guarded: a caller-supplied ``lease_sleep_fn`` that
        raises would otherwise kill the timer silently and reopen DW-6 for the
        rest of the run, with nothing observing it until the run ended.
        """
        while True:
            try:
                await lease_sleep_fn(renew_interval)
                await asyncio.sleep(0)
                if not _lease_held():
                    return  # lost it: the loop stops launching at its next check
            except Exception as exc:  # noqa: BLE001 - a blip never aborts a run
                _log_lease_renewer_failed(exc, phase="tick")
                # A yield, not a back-off: it keeps a raising ``lease_sleep_fn``
                # from starving the run it protects. Such a seam still retries at
                # event-loop speed — acceptable because the production sleep is
                # ``asyncio.sleep``, and a failing ``renew()`` (the reachable
                # case) is paced by the sleep at the top of the loop.
                await asyncio.sleep(0)

    _publish(BackfillState.RUNNING)

    async def _worker(prop: Any) -> None:
        pid = str(getattr(prop, "id", "?"))
        try:
            await enrich_fn(prop)
        except Exception as exc:  # noqa: BLE001 - one bad row must not abort
            if is_quota_error is not None and is_quota_error(exc):
                # The provider is out of quota: this row was never scored and
                # nothing was persisted for it. Charging an error (or an attempt)
                # would blame the row for the account's ceiling and eventually
                # quarantine a perfectly good property. Back off instead.
                result.quota_exhausted = True
                result.budget_exhausted = True
                if ledger is not None:
                    ledger.rollback_attempt(pid)
                _publish(BackfillState.BACKING_OFF)
                _log_quota_backoff(prop, exc)
            else:
                result.errors += 1
                result.error_ids.append(pid)
                if ledger is not None:
                    ledger.record_error(pid, str(exc))
                _log_row_error(prop, exc)
        else:
            result.processed += 1
            result.last_property_id = str(getattr(prop, "id", ""))
            checkpoint.advance(result.last_property_id)
        finally:
            # Every finished row ticks progress — success, hard error *and*
            # quota refusal. Ticking only on success meant a storm of failing
            # rows never refreshed the caller's heartbeat.
            #
            # The hook is caller-supplied and ``sem.release()`` must survive it:
            # a raising hook that skipped the release would block the launch
            # loop on ``sem.acquire()`` forever while still holding the lease —
            # a hang, not an error. Renewing here as well is what keeps the
            # lease alive through the final ``gather`` drain, which the launch
            # loop has by then stopped covering.
            try:
                if on_progress is not None:
                    on_progress(result)
            except Exception as exc:  # noqa: BLE001 - a hook never aborts a run
                _log_progress_hook_failed(exc)
            finally:
                _tick_lease()
                sem.release()

    async def _may_launch() -> bool:
        """Honor pause/stop. False means: stop launching new rows.

        A pause holds the loop here rather than ending the run, so in-flight
        rows finish and the checkpoint stays exactly where it was. The lease is
        renewed on every poll so an arbitrarily long pause can never let it
        lapse; ``on_progress`` is deliberately *not* ticked here — the caller's
        hook beats the advisory ``:active`` heartbeat, and a paused runner that
        keeps beating it blocks ``migrate-primary.sh`` forever, defeating the
        main reason an operator pauses.
        """
        if control is None:
            return True
        if control.should_stop():
            return False
        if not control.is_paused():
            return True
        _publish(BackfillState.PAUSED)
        paused_at = clock()
        try:
            while control.is_paused():
                if control.should_stop():
                    return False
                # A migration that starts while this run is held must not be
                # resumed into: the pause could end at any poll, and the row it
                # would launch next would write against a schema mid-upgrade.
                if _migration_holds():
                    return False
                if not _lease_held():
                    return False
                # The state key has a short TTL, so publishing ``paused`` once
                # made any longer pause read back as ``idle`` from ``--status``
                # and story 1.5's API — for a runner that is alive, holding the
                # lease and deliberately held.
                _refresh_state()
                await sleep_fn(poll_seconds)
        finally:
            result.paused_seconds += max(0.0, clock() - paused_at)
        _publish(BackfillState.RUNNING)
        return True

    # The drain below lives in a ``finally``: every Redis touch in this loop
    # (lease renew, control reads, budget reservation, ledger writes) can raise
    # on a transient blip, and letting that escape with tasks still pending left
    # in-flight rows to be cancelled at an arbitrary await point by
    # ``asyncio.run`` — mid-enrichment, mid-write. In-flight rows always drain.
    renewer: Optional[asyncio.Task] = None
    try:
        if lease is not None:
            renewer = asyncio.create_task(_renew_lease_periodically())
        try:
            for prop, metrics in rows:
                # A quota refusal means every further launch would 429 too — and each
                # retry burns daily request quota. Stop launching immediately.
                if result.quota_exhausted:
                    break
                # A primary migration holds the exclusion key. The caller beat its
                # ``:active`` heartbeat before handing this predicate in, so the
                # migration either sees that heartbeat and refuses, or it got here
                # first and this run must not launch into its upgrade (DW-3/DW-4).
                if _migration_holds():
                    break
                # The background timer may already have lost it while this loop
                # was in a sleep, a TPM wait or a drain. ``_lease_held()`` below
                # would report the same thing (it short-circuits on the flag);
                # naming the timer's verdict here is what keeps a lost lease from
                # reading as an ordinary failed renew at this break.
                if result.lease_lost:
                    break
                # Renewing here (not in ``on_progress``) means the lease is refreshed
                # even through rows that only ever fail.
                if not _lease_held():
                    break
                if not await _may_launch():
                    # A lost lease is not an operator stop — and neither is a
                    # migration holding the DB. Do not mislabel either.
                    if not result.lease_lost and not result.migration_blocked:
                        result.stopped = True
                    break
                _refresh_state()
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

                await sem.acquire()  # bound in-flight properties to ``concurrency``
                # Waiting for a slot is the point at which an in-flight worker can have
                # discovered the provider is out of quota. Re-check before spending
                # anything on this row: budget reserved here would never be used.
                if result.quota_exhausted:
                    sem.release()
                    break
                # Same window, third writer: the background renewer can have lost
                # the lease while this loop waited for a slot. Launching now would
                # make this a second writer against a queue someone else owns.
                if result.lease_lost:
                    sem.release()
                    break
                # Same reason, different writer: the checks at the loop head ran
                # before the launch interval, the TPM window and this ``acquire`` —
                # minutes, on a busy pass — so a migration that started in between
                # would otherwise get this row launched into its upgrade. Re-read
                # before spending any budget on it.
                if _migration_holds():
                    sem.release()
                    break
                if not budget.try_consume(requests_per_property):
                    sem.release()
                    result.budget_exhausted = True
                    break

                if ledger is not None:
                    # Count the attempt, not just failures: a row that enriches to a
                    # falsy ai_score stays a ``mode=missing`` candidate and would
                    # otherwise be re-fetched every cycle forever.
                    ledger.record_attempt(pid)
                attempted += 1
                result.requests_consumed += requests_per_property
                last_launch = clock()
                tasks.append(asyncio.create_task(_worker(prop)))

        finally:
            if tasks:
                # ``return_exceptions``: ``checkpoint.advance()`` runs outside the
                # worker's ``except``, so a Redis error there would otherwise abort
                # the gather on the first failure and abandon the remaining rows.
                for outcome in await asyncio.gather(*tasks, return_exceptions=True):
                    if isinstance(outcome, BaseException):
                        _log_row_error(None, outcome)
    finally:
        # Cancel *after* the drain: one slow row finishing alone is exactly a
        # window the timer has to cover. Whatever the renewer ends with is
        # logged, never raised, so this can never replace the exception the
        # caller is about to see (or the result it is about to get).
        if renewer is not None:
            renewer.cancel()
            # ``await renewer`` cannot be used here: it raises the renewer's own
            # ``CancelledError``, which is indistinguishable from a cancellation
            # delivered to *this* coroutine (Ctrl-C, a supervising ``wait_for``)
            # while the renewer is finishing — and ``renewer.cancelled()`` is
            # ``True`` either way, so filtering on it swallowed the caller's
            # cancellation and returned a result as if nothing had happened.
            # ``wait`` never re-raises what the awaited task raised, so a
            # ``CancelledError`` out of this line is unambiguously ours to
            # propagate.
            await asyncio.wait({renewer})
            if not renewer.cancelled():
                renewer_exc = renewer.exception()
                if renewer_exc is not None:
                    _log_lease_renewer_failed(renewer_exc, phase="shutdown")
    # A quota-exhausted run stays "backing-off" for the operator/API to see;
    # anything else (including an operator stop) has genuinely gone idle. A run
    # that lost its lease publishes nothing: the state key now describes whoever
    # took the lease over, and stamping ``idle`` on it would erase their liveness.
    if not result.lease_lost:
        _publish(
            BackfillState.BACKING_OFF if result.quota_exhausted else BackfillState.IDLE
        )
    return result


def _log_row_error(prop: Any, exc: Exception) -> None:
    from infra.logging import get_logger

    get_logger(__name__).warning(
        "backfill_row_error",
        property_id=str(getattr(prop, "id", "?")),
        error=str(exc),
    )


def _log_lease_lost() -> None:
    from infra.logging import get_logger

    get_logger(__name__).warning(
        "backfill_lease_lost",
        reason="renew refused — another runner may hold the lease; stopped launching",
    )


def _log_migration_blocked() -> None:
    from infra.logging import get_logger

    get_logger(__name__).warning(
        "backfill_migration_blocked",
        reason="a primary migration holds the exclusion key; stopped launching rows",
    )


def _log_progress_hook_failed(exc: Exception) -> None:
    from infra.logging import get_logger

    get_logger(__name__).warning(
        "backfill_progress_hook_failed",
        error=str(exc),
    )


def _log_lease_meta_failed(exc: Exception) -> None:
    from infra.logging import get_logger

    get_logger(__name__).warning(
        "backfill_lease_meta_write_failed",
        error=str(exc),
    )


def _log_lease_renewer_failed(exc: Exception, *, phase: str) -> None:
    from infra.logging import get_logger

    # ``phase`` separates "one tick blipped, the timer is still running" from
    # "the timer failed on the way out" — without it the two read identically
    # in the log and only one of them means the run went unrenewed.
    get_logger(__name__).warning(
        "backfill_lease_renewer_failed",
        renewer_phase=phase,
        error=str(exc),
    )


def _log_lease_tick_failed(exc: Exception) -> None:
    from infra.logging import get_logger

    get_logger(__name__).warning(
        "backfill_lease_tick_failed",
        error=str(exc),
    )


def _log_quota_backoff(prop: Any, exc: Exception) -> None:
    from infra.logging import get_logger

    get_logger(__name__).warning(
        "backfill_quota_exhausted",
        property_id=str(getattr(prop, "id", "?")),
        error=str(exc),
    )
