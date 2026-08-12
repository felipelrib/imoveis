"""Consecutive-degraded-result circuit breaker in ``run_backfill`` (v0.13-s3.2).

The corruption this closes (DW-17): every non-quota AI-client failure — a
revoked key (401), a retired model id (404), a DNS/proxy outage — used to be
swallowed into a fabricated ``0.5`` score that ``run_enrichment`` persisted and
``mode=missing`` would never re-queue. Story 3.2 turns that fallback into a
typed marker, ``run_enrichment`` refuses to persist it (see
``test_run_enrichment_degraded.py``), and the runner counts the resulting
*consecutive* failures into a breaker that stops launching.

Pure ``src/core`` logic against dict-backed doubles — no DB, network, Celery or
adapter import. The doubles mirror ``test_backfill_control.py``'s deliberately:
there is no shared backfill fixture, and each runner suite owns its fakes.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from core.backfill_runner import (
    _STATE_REFRESH_SECONDS,
    AttemptLedger,
    BackfillResult,
    BackfillState,
    Checkpoint,
    DailyBudget,
    is_degraded_result,
    is_quota_exhausted,
    run_backfill,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fakes (mirrors of test_backfill_control.py's — same reason, same shapes)
# ---------------------------------------------------------------------------


class FakeRedis:
    """Dict-backed Redis with ``SET NX EX`` semantics and no ``eval``."""

    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.expires: dict[str, int] = {}

    def get(self, key):
        return self.kv.get(key)

    def set(self, key, val, ex=None, nx=False):
        if nx and key in self.kv:
            return None
        self.kv[key] = str(val)
        if ex:
            self.expires[key] = ex
        return True

    def expire(self, key, ttl):
        self.expires[key] = ttl
        return 1 if key in self.kv or key in self.hashes else 0

    def delete(self, key):
        existed = key in self.kv or key in self.hashes
        self.kv.pop(key, None)
        self.hashes.pop(key, None)
        return 1 if existed else 0

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hset(self, key, field=None, value=None, mapping=None):
        h = self.hashes.setdefault(key, {})
        if mapping:
            h.update({k: str(v) for k, v in mapping.items()})
        if field is not None:
            h[field] = str(value)

    def hincrby(self, key, field, n=1):
        h = self.hashes.setdefault(key, {})
        h[field] = str(int(h.get(field, 0)) + int(n))
        return int(h[field])

    def hdel(self, key, *fields):
        for f in fields:
            self.hashes.setdefault(key, {}).pop(f, None)


def _rows(n, *, enriched_ids=()):
    rows = []
    for i in range(n):
        pid = f"prop-{i}"
        ai = 0.8 if pid in enriched_ids else None
        rows.append((SimpleNamespace(id=pid), SimpleNamespace(ai_score=ai)))
    return rows


def _budget(redis, limit):
    fixed = datetime.fromisoformat("2026-08-12T12:00:00+00:00")
    return DailyBudget(redis, prefix="t", daily_limit=limit, now_fn=lambda: fixed)


def _checkpoint(redis):
    fixed = datetime.fromisoformat("2026-08-12T12:00:00+00:00")
    return Checkpoint(redis, prefix="t", now_fn=lambda: fixed)


async def _noop_sleep(_):
    return None


class _ScriptedControl:
    """Control double recording the states a run publishes."""

    def is_paused(self):
        return False

    def should_stop(self):
        return False

    def __init__(self) -> None:
        self.states: list[BackfillState] = []

    def publish_state(self, state):
        self.states.append(state)

    @property
    def refresh_interval_seconds(self):
        return _STATE_REFRESH_SECONDS


class _QuotaError(RuntimeError):
    is_quota_exhausted = True


class _DegradedError(RuntimeError):
    """Stand-in for ``adapters.ai.client.AIResultDegradedError`` (AD-1).

    ``src/core`` never imports adapters, so the runner recognises the real error
    by the same duck-typed attribute this double sets.
    """

    is_degraded_result = True


def _run(rows, enrich, redis, **kw):
    return asyncio.run(
        run_backfill(
            rows,
            enrich_fn=enrich,
            budget=_budget(redis, kw.pop("daily_limit", 1000)),
            checkpoint=_checkpoint(redis),
            requests_per_property=3,
            sleep_fn=_noop_sleep,
            **kw,
        )
    )


# ---------------------------------------------------------------------------
# The predicate (duck-typed, deliberately without a text safety net)
# ---------------------------------------------------------------------------


def test_degraded_predicate_is_duck_typed_not_isinstance():
    assert is_degraded_result(_DegradedError("visual fell back")) is True
    assert is_degraded_result(RuntimeError("bad json")) is False


def test_degraded_predicate_has_no_text_safety_net():
    """Unlike the quota predicate: the marker is set by *our* gate, never by a
    transport, so a message that merely says "degraded" must not classify."""

    assert is_degraded_result(RuntimeError("the result was degraded")) is False


def test_a_quota_error_is_never_read_as_degraded():
    assert is_degraded_result(_QuotaError("429 quota exhausted")) is False
    assert is_quota_exhausted(_DegradedError("visual fell back")) is False


# ---------------------------------------------------------------------------
# Counting, tripping, recovering
# ---------------------------------------------------------------------------


def test_degraded_rows_below_the_threshold_do_not_stop_the_run():
    r = FakeRedis()
    calls: list[str] = []

    async def enrich(prop):
        calls.append(prop.id)
        if prop.id in ("prop-0", "prop-1"):
            raise _DegradedError("visual fell back")

    result = _run(_rows(4), enrich, r, max_consecutive_ai_failures=3)

    assert calls == ["prop-0", "prop-1", "prop-2", "prop-3"]
    assert result.ai_circuit_open is False
    assert result.ai_fallbacks == 2
    assert result.errors == 2
    assert result.error_ids == ["prop-0", "prop-1"]
    assert result.processed == 2


def test_the_threshold_th_consecutive_degraded_row_stops_launching():
    r = FakeRedis()
    calls: list[str] = []

    async def enrich(prop):
        calls.append(prop.id)
        raise _DegradedError("401 from the provider; visual fell back")

    result = _run(_rows(10), enrich, r, max_consecutive_ai_failures=3)

    assert calls == ["prop-0", "prop-1", "prop-2"]  # the 4th is never launched
    assert result.ai_circuit_open is True
    assert result.ai_fallbacks == 3
    assert result.errors == 3
    assert result.processed == 0
    # Nothing was persisted for any of them: the gate raises before SessionLocal.
    assert _checkpoint(r).processed_total() == 0
    assert result.last_property_id is None


def test_one_success_resets_the_consecutive_counter():
    r = FakeRedis()
    calls: list[str] = []

    async def enrich(prop):
        calls.append(prop.id)
        if prop.id != "prop-2":
            raise _DegradedError("transient transport failure")

    result = _run(_rows(5), enrich, r, max_consecutive_ai_failures=3)

    # 2 degraded, a success, then 2 more degraded — never 3 in a row.
    assert calls == ["prop-0", "prop-1", "prop-2", "prop-3", "prop-4"]
    assert result.ai_circuit_open is False
    assert result.ai_fallbacks == 4
    assert result.processed == 1
    assert _checkpoint(r).processed_total() == 1


def test_an_ordinary_error_neither_trips_the_breaker_nor_resets_it():
    """A bad image or a DB blip is not evidence the provider is broken."""
    r = FakeRedis()

    async def enrich(prop):
        if prop.id == "prop-1":
            raise ValueError("bad json")
        raise _DegradedError("visual fell back")

    result = _run(_rows(6), enrich, r, max_consecutive_ai_failures=3)

    # prop-0, prop-2, prop-3 are the three consecutive *degraded* completions;
    # the ordinary error in between neither counts nor clears the run of them.
    assert result.ai_circuit_open is True
    assert result.ai_fallbacks == 3
    assert result.errors == 4  # the ordinary one is still charged as an error


def test_a_run_of_ordinary_errors_alone_never_trips_the_breaker():
    r = FakeRedis()

    async def enrich(prop):
        raise ValueError("bad json")

    result = _run(_rows(5), enrich, r, max_consecutive_ai_failures=3)

    assert result.ai_circuit_open is False
    assert result.ai_fallbacks == 0
    assert result.errors == 5


# ---------------------------------------------------------------------------
# Accounting: the ledger, the checkpoint, the progress hook
# ---------------------------------------------------------------------------


def test_a_degraded_row_is_charged_an_attempt_and_an_error():
    """Ambiguous by nature (a dead key or one unparseable response), so the
    ledger's quarantine still owns the per-row case."""
    r = FakeRedis()
    ledger = AttemptLedger(r, prefix="t", max_attempts=5)

    async def enrich(prop):
        raise _DegradedError("visual fell back")

    result = _run(_rows(2), enrich, r, ledger=ledger, max_consecutive_ai_failures=0)

    assert result.errors == 2
    assert ledger.attempts("prop-0") == 1
    assert ledger.attempts("prop-1") == 1
    assert ledger.reason_for("prop-0")  # the quarantine report names the reason


def test_tripping_the_breaker_rolls_back_the_attempts_it_charged():
    """The unbroken run proves the backend, not the row, was at fault.

    Nothing is persisted and the checkpoint does not move, so the next start
    re-fetches exactly these rows. Keeping the charge would quarantine three
    innocent properties after ``max_attempts`` restarts against a key nobody
    has fixed yet — while the CLI banner promises they are still candidates.
    """
    r = FakeRedis()
    ledger = AttemptLedger(r, prefix="t", max_attempts=3)

    async def enrich(prop):
        raise _DegradedError("visual fell back")

    result = _run(_rows(6), enrich, r, ledger=ledger, max_consecutive_ai_failures=3)

    assert result.ai_circuit_open is True
    assert result.ai_fallbacks == 3
    for pid in ("prop-0", "prop-1", "prop-2"):
        assert ledger.attempts(pid) == 0, f"{pid} still carries a charge"
        assert ledger.is_quarantined(pid) is False
    # Errors are still reported honestly — only the quarantine charge is undone.
    assert result.errors == 3
    assert result.error_ids == ["prop-0", "prop-1", "prop-2"]


def test_three_restarts_against_a_dead_backend_quarantine_nothing():
    """The regression the rollback exists for, across passes rather than rows."""
    r = FakeRedis()
    ledger = AttemptLedger(r, prefix="t", max_attempts=3)

    async def enrich(prop):
        raise _DegradedError("visual fell back")

    for _ in range(3):
        _run(_rows(6), enrich, r, ledger=ledger, max_consecutive_ai_failures=3)

    for pid in ("prop-0", "prop-1", "prop-2"):
        assert ledger.is_quarantined(pid) is False


def test_degradation_below_the_threshold_keeps_its_charge():
    """A row nobody can enrich must still march towards quarantine, or
    ``--continuous`` pays for it every cycle forever."""
    r = FakeRedis()
    ledger = AttemptLedger(r, prefix="t", max_attempts=5)

    async def enrich(prop):
        if prop.id in ("prop-0", "prop-2"):
            raise _DegradedError("visual fell back")

    result = _run(_rows(4), enrich, r, ledger=ledger, max_consecutive_ai_failures=3)

    assert result.ai_circuit_open is False
    assert ledger.attempts("prop-0") == 1
    assert ledger.attempts("prop-2") == 1


def test_a_degraded_row_never_advances_the_checkpoint_or_counts_as_processed():
    r = FakeRedis()
    checkpoint = _checkpoint(r)

    async def enrich(prop):
        if prop.id == "prop-0":
            return
        raise _DegradedError("visual fell back")

    result = asyncio.run(
        run_backfill(
            _rows(3),
            enrich_fn=enrich,
            budget=_budget(r, 1000),
            checkpoint=checkpoint,
            requests_per_property=3,
            sleep_fn=_noop_sleep,
            max_consecutive_ai_failures=0,
        )
    )

    assert result.processed == 1
    assert result.last_property_id == "prop-0"  # not rewound by the failures
    assert checkpoint.processed_total() == 1
    assert checkpoint.load()["last_property_id"] == "prop-0"


def test_progress_still_ticks_on_a_degraded_row():
    """A storm of degraded rows must keep the caller's heartbeat alive."""
    r = FakeRedis()
    ticks: list[int] = []

    async def enrich(prop):
        raise _DegradedError("visual fell back")

    _run(
        _rows(3),
        enrich,
        r,
        on_progress=lambda res: ticks.append(res.ai_fallbacks),
        max_consecutive_ai_failures=0,
    )

    assert ticks == [1, 2, 3]


# ---------------------------------------------------------------------------
# Interaction with the quota path (story 1.3) — quota always wins
# ---------------------------------------------------------------------------


def test_a_quota_refusal_after_degraded_rows_keeps_the_quota_semantics():
    r = FakeRedis()
    ledger = AttemptLedger(r, prefix="t", max_attempts=5)
    control = _ScriptedControl()

    async def enrich(prop):
        if prop.id == "prop-2":
            raise _QuotaError("Gemini quota exhausted: 429")
        raise _DegradedError("visual fell back")

    result = _run(
        _rows(6),
        enrich,
        r,
        ledger=ledger,
        control=control,
        max_consecutive_ai_failures=5,
    )

    assert result.quota_exhausted is True
    assert result.budget_exhausted is True
    assert result.ai_circuit_open is False  # the breaker never tripped
    assert result.ai_fallbacks == 2  # the quota row did not feed the counter
    assert result.errors == 2  # …and was not blamed for the account's ceiling
    assert ledger.attempts("prop-2") == 0  # rolled back, as before
    assert control.states[-1] is BackfillState.BACKING_OFF


def test_a_tripped_breaker_publishes_idle_not_backing_off():
    """``BACKING_OFF`` means "the provider refused on quota"; a revoked key
    would send the operator to the wrong dashboard, and this epic forbids a new
    state value."""
    r = FakeRedis()
    control = _ScriptedControl()

    async def enrich(prop):
        raise _DegradedError("401 from the provider")

    result = _run(
        _rows(4), enrich, r, control=control, max_consecutive_ai_failures=2
    )

    assert result.ai_circuit_open is True
    assert result.quota_exhausted is False
    assert control.states[0] is BackfillState.RUNNING
    assert control.states[-1] is BackfillState.IDLE


# ---------------------------------------------------------------------------
# Disabling, draining, reporting
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("threshold", [0, -1])
def test_a_non_positive_threshold_disables_the_breaker_only(threshold):
    """``<= 0`` means "never stop the pass" — never "go back to fabricating"."""
    r = FakeRedis()
    calls: list[str] = []

    async def enrich(prop):
        calls.append(prop.id)
        raise _DegradedError("visual fell back")

    result = _run(_rows(4), enrich, r, max_consecutive_ai_failures=threshold)

    assert calls == ["prop-0", "prop-1", "prop-2", "prop-3"]
    assert result.ai_circuit_open is False
    assert result.ai_fallbacks == 4
    assert result.processed == 0
    assert _checkpoint(r).processed_total() == 0


def test_degraded_classification_can_be_disabled_like_the_quota_one():
    r = FakeRedis()

    async def enrich(prop):
        raise _DegradedError("visual fell back")

    result = _run(
        _rows(3),
        enrich,
        r,
        is_degraded_error=None,
        max_consecutive_ai_failures=1,
    )

    assert result.ai_circuit_open is False
    assert result.ai_fallbacks == 0
    assert result.errors == 3  # ordinary row errors, run continues


def test_rows_already_in_flight_when_the_breaker_trips_still_drain():
    r = FakeRedis()
    started: list[str] = []
    finished: list[str] = []
    in_flight = 0
    peak_in_flight = 0

    async def enrich(prop):
        nonlocal in_flight, peak_in_flight
        started.append(prop.id)
        in_flight += 1
        peak_in_flight = max(peak_in_flight, in_flight)
        await asyncio.sleep(0)
        in_flight -= 1
        finished.append(prop.id)
        raise _DegradedError("visual fell back")

    result = _run(
        _rows(8), enrich, r, concurrency=3, max_consecutive_ai_failures=1
    )

    assert result.ai_circuit_open is True
    # The point of the case: rows really were running *together* when the first
    # completion tripped the breaker. Without this the assertions below would
    # also pass on a run that launched exactly one row, which proves nothing
    # about the drain.
    assert peak_in_flight > 1
    # It stopped launching — 8 rows were available and at most one slot-full
    # went out (``concurrency - 1`` extra were already in flight at the trip).
    assert 1 < len(started) <= 3
    # ...and every launched row ran to completion: cancelling mid-enrichment is
    # what leaves half-written properties behind.
    assert finished == started
    assert len(set(started)) == len(started)
    assert result.ai_fallbacks == len(started)
    assert result.errors == len(started)


def test_to_dict_reports_the_breaker_to_the_caller():
    payload = BackfillResult(ai_fallbacks=3, ai_circuit_open=True).to_dict()

    assert payload["ai_fallbacks"] == 3
    assert payload["ai_circuit_open"] is True
    # Unchanged keys the CLI/admin surfaces already read.
    assert payload["quota_exhausted"] is False
    assert payload["errors"] == 0
