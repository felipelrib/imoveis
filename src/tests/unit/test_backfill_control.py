"""Unit tests for the backfill control core (v0.13-s1.3).

Pure ``src/core`` logic against dict-backed fake Redis clients — no DB, network,
Celery or adapter import. Covers the single-instance lease (both the atomic
``eval`` branch and the check-then-act fallback), the pause/resume/stop control
state machine, the now-atomic daily budget, task-class scope translation, and
``run_backfill``'s pause / stop / quota-back-off branches.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from core.backfill_runner import (
    _BUDGET_RESERVE_LUA,
    _LEASE_RELEASE_LUA,
    _LEASE_RENEW_LUA,
    _STATE_REFRESH_SECONDS,
    DEFAULT_BACKFILL_SCOPE,
    AttemptLedger,
    BackfillControl,
    BackfillLease,
    BackfillState,
    Checkpoint,
    DailyBudget,
    Heartbeat,
    MigrationGate,
    is_quota_exhausted,
    parse_task_classes,
    run_backfill,
    stages_for_task_classes,
)
from core.enrichment import EnrichmentTaskClass

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fakes
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


class EvalRedis(FakeRedis):
    """Fake that also exposes ``eval``, exercising the atomic script branches.

    The bodies below mirror the Lua in ``core.backfill_runner`` one-for-one —
    the point is to exercise the *Python* side of each atomic branch (argument
    order, return decoding, which key ends up in which state), not to reimplement
    Redis.
    """

    def __init__(self) -> None:
        super().__init__()
        self.eval_calls = 0

    def eval(self, script, numkeys, key, *args):
        self.eval_calls += 1
        assert numkeys == 1
        if script is _BUDGET_RESERVE_LUA:
            return self._budget_reserve(key, *args)
        token = args[0]
        if self.kv.get(key) != token:
            return 0
        if script is _LEASE_RELEASE_LUA:
            self.delete(key)
            return 1
        if script is _LEASE_RENEW_LUA:
            self.expires[key] = int(args[1])
            return 1
        raise AssertionError("unknown lease script")

    def _budget_reserve(self, key, n, now, window, limit, ttl, now_iso):
        n, now, window, limit = int(n), float(now), float(window), int(limit)
        h = self.hashes.setdefault(key, {})
        try:
            start_epoch = float(h["start_epoch"])
        except (KeyError, TypeError, ValueError):
            start_epoch = None
        opened = start_epoch is None or (now - start_epoch) >= window
        if opened:
            h.update({"count": str(n), "start": str(now_iso), "start_epoch": str(now)})
            count = n
        else:
            count = self.hincrby(key, "count", n)
        if count > limit:
            if opened:
                self.delete(key)  # never leave a phantom window behind
            else:
                self.hincrby(key, "count", -n)
            return 0
        self.expires[key] = int(ttl)
        return 1


class BytesRedis(FakeRedis):
    """Raw-bytes client (``decode_responses=False``, as ``get_redis()`` is)."""

    def get(self, key):
        raw = super().get(key)
        return None if raw is None else raw.encode()

    def hgetall(self, key):
        return {k.encode(): v.encode() for k, v in super().hgetall(key).items()}


def _rows(n, *, enriched_ids=()):
    rows = []
    for i in range(n):
        pid = f"prop-{i}"
        ai = 0.8 if pid in enriched_ids else None
        rows.append((SimpleNamespace(id=pid), SimpleNamespace(ai_score=ai)))
    return rows


def _budget(redis, limit, *, now=None):
    fixed = now or datetime.fromisoformat("2026-08-06T12:00:00+00:00")
    return DailyBudget(redis, prefix="t", daily_limit=limit, now_fn=lambda: fixed)


def _checkpoint(redis):
    fixed = datetime.fromisoformat("2026-08-06T12:00:00+00:00")
    return Checkpoint(redis, prefix="t", now_fn=lambda: fixed)


async def _noop_sleep(_):
    return None


class _ScriptedControl:
    """Control double driving deterministic pause/stop sequences."""

    def __init__(self, *, paused=(), stops=()):
        self._paused = list(paused)
        self._stops = list(stops)
        self.states: list[BackfillState] = []

    def _pop(self, queue):
        return queue.pop(0) if queue else False

    def is_paused(self):
        return self._pop(self._paused)

    def should_stop(self):
        return self._pop(self._stops)

    def publish_state(self, state):
        self.states.append(state)

    @property
    def refresh_interval_seconds(self):
        return _STATE_REFRESH_SECONDS


class _QuotaError(RuntimeError):
    is_quota_exhausted = True


# ---------------------------------------------------------------------------
# BackfillLease
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("client_cls", [FakeRedis, EvalRedis, BytesRedis])
def test_lease_free_is_acquired_then_held_against_a_second_runner(client_cls):
    r = client_cls()
    first = BackfillLease(r, prefix="t", ttl_seconds=60, owner="host:1")
    second = BackfillLease(r, prefix="t", ttl_seconds=60, owner="host:2")

    assert first.acquire() is True
    assert second.acquire() is False  # SET NX lost the race
    assert r.expires["t:lease"] == 60

    holder = second.holder()
    assert holder is not None
    assert holder["owner"] == "host:1"
    assert holder["is_self"] is False
    assert holder["seconds_since_last_seen"] is not None


@pytest.mark.parametrize("client_cls", [FakeRedis, EvalRedis, BytesRedis])
def test_lease_release_is_owner_guarded(client_cls):
    r = client_cls()
    owner = BackfillLease(r, prefix="t", ttl_seconds=60)
    intruder = BackfillLease(r, prefix="t", ttl_seconds=60)
    assert owner.acquire() is True

    # A non-owner must delete nothing — otherwise a stale runner could free a
    # successor's lease and let a third one in.
    assert intruder.release() is False
    assert owner.is_held_by_self() is True

    assert owner.release() is True
    assert owner.holder() is None
    assert BackfillLease(r, prefix="t").acquire() is True  # free again


@pytest.mark.parametrize("client_cls", [FakeRedis, EvalRedis, BytesRedis])
def test_lease_renew_extends_only_for_the_owner(client_cls):
    r = client_cls()
    owner = BackfillLease(r, prefix="t", ttl_seconds=120)
    intruder = BackfillLease(r, prefix="t", ttl_seconds=999)
    assert owner.acquire() is True

    assert owner.renew() is True
    assert r.expires["t:lease"] == 120
    assert intruder.renew() is False
    assert r.expires["t:lease"] == 120  # untouched by the non-owner


def test_lease_uses_the_atomic_eval_branch_when_available():
    r = EvalRedis()
    lease = BackfillLease(r, prefix="t", ttl_seconds=30)
    lease.acquire()
    lease.renew()
    lease.release()
    assert r.eval_calls == 2  # renew + release both went through Lua


def test_lease_falls_back_to_check_then_act_without_eval():
    r = FakeRedis()
    assert not hasattr(r, "eval")
    lease = BackfillLease(r, prefix="t", ttl_seconds=30)
    assert lease.acquire() is True
    assert lease.renew() is True
    assert lease.release() is True


def test_lease_holder_ignores_stale_meta_from_a_previous_holder():
    r = FakeRedis()
    first = BackfillLease(r, prefix="t", ttl_seconds=60, owner="gone:1")
    first.acquire()
    first.release()
    second = BackfillLease(r, prefix="t", ttl_seconds=60, owner="live:2")
    # Meta from the dead holder is still in Redis; only the token decides.
    r.hset("t:lease:meta", mapping={"token": "stale", "owner": "gone:1"})
    second.acquire()

    holder = second.holder()
    assert holder["owner"] == "live:2"
    assert holder["is_self"] is True


# ---------------------------------------------------------------------------
# BackfillControl
# ---------------------------------------------------------------------------


def test_control_pause_resume_stop_round_trip():
    r = FakeRedis()
    control = BackfillControl(r, prefix="t")

    assert control.is_paused() is False
    assert control.should_stop() is False

    control.request_pause()
    assert control.is_paused() is True
    control.request_pause()  # idempotent: a level, not an event
    assert control.is_paused() is True

    control.request_resume()
    assert control.is_paused() is False

    control.request_stop()
    assert control.should_stop() is True
    control.clear_requests()
    assert control.should_stop() is False
    assert control.is_paused() is False


def test_control_state_publishes_with_ttl_and_decays_to_idle():
    r = FakeRedis()
    control = BackfillControl(r, prefix="t", state_ttl_seconds=30)

    assert control.state() is BackfillState.IDLE  # nothing published yet
    control.publish_state(BackfillState.RUNNING)
    assert control.state() is BackfillState.RUNNING
    assert r.expires["t:state"] == 30  # a crashed runner decays back to idle

    control.publish_state(BackfillState.BACKING_OFF)
    assert control.state() is BackfillState.BACKING_OFF
    assert r.kv["t:state"] == "backing-off"

    r.kv["t:state"] = "nonsense"
    assert control.state() is BackfillState.IDLE


def test_control_reads_raw_bytes_state():
    r = BytesRedis()
    control = BackfillControl(r, prefix="t")
    control.publish_state(BackfillState.PAUSED)
    assert control.state() is BackfillState.PAUSED


# ---------------------------------------------------------------------------
# DailyBudget — reservation (Lua branch and non-atomic fallback)
# ---------------------------------------------------------------------------

# Every budget case runs against both clients: ``EvalRedis`` takes the atomic
# ``_BUDGET_RESERVE_LUA`` path a real Redis takes, ``FakeRedis`` the documented
# multi-op fallback for clients without ``eval``. They must behave identically.
_BUDGET_CLIENTS = [FakeRedis, EvalRedis]


@pytest.mark.parametrize("client_cls", _BUDGET_CLIENTS)
def test_budget_reserves_under_the_cap(client_cls):
    r = client_cls()
    b = _budget(r, 10)
    assert b.try_consume(6) is True
    assert b.try_consume(3) is True
    assert b.consumed() == 9
    assert b.remaining() == 1


@pytest.mark.parametrize("client_cls", _BUDGET_CLIENTS)
def test_budget_overshoot_is_rolled_back_not_reserved(client_cls):
    r = client_cls()
    b = _budget(r, 10)
    b.try_consume(9)
    assert b.try_consume(3) is False
    # The counter must be exactly back to 9 — a leaked +3 would silently shrink
    # every later day's usable budget.
    assert b.consumed() == 9
    assert r.hashes["t:budget"]["count"] == "9"


@pytest.mark.parametrize("client_cls", _BUDGET_CLIENTS)
def test_budget_refusal_that_opened_a_window_leaves_no_phantom(client_cls):
    """A reservation too big for the cap must not open a window it cannot use.

    The phantom window was a real deadlock: ``seconds_until_reset()`` then
    reported ~24h against a ``count=0`` window, so ``--continuous`` slept a full
    day, woke, refused the same reservation, and slept another day forever.
    """
    r = client_cls()
    b = _budget(r, 2)  # daily_limit 2 < requests_per_property 3
    assert b.try_consume(3) is False
    assert b.consumed() == 0
    assert b.remaining() == 2
    assert b.seconds_until_reset() == 0.0  # no window was left open
    assert "t:budget" not in r.hashes


def test_budget_upgrade_mid_window_does_not_grant_a_second_day():
    """A pre-v0.13-s1.3 hash has no ``start_epoch``; the Lua must still see it.

    The atomic script compares ``start_epoch`` because Lua cannot parse the ISO
    ``start`` stamp. Left unmigrated, a window opened by the old code reads as
    *no window*, rolls, and hands the run a second full day's budget inside one
    real 24h — straight past the provider's RPD.
    """
    r = EvalRedis()
    now = datetime.fromisoformat("2026-08-06T12:00:00+00:00")
    b = _budget(r, 10, now=now)
    # Exactly what the pre-upgrade code wrote: count + ISO start, no epoch twin.
    started = now - timedelta(hours=2)
    r.hashes["t:budget"] = {"count": "9", "start": started.isoformat()}

    assert b.try_consume(3) is False  # 9 + 3 > 10 — the live window still binds
    assert b.consumed() == 9
    assert r.hashes["t:budget"]["start_epoch"] == str(started.timestamp())


@pytest.mark.parametrize("client_cls", _BUDGET_CLIENTS)
def test_budget_refusal_inside_a_live_window_keeps_that_window(client_cls):
    """The delete-on-refusal fix must not wipe a window that was already open."""
    r = client_cls()
    b = _budget(r, 10)
    assert b.try_consume(9) is True
    assert b.try_consume(5) is False
    assert b.consumed() == 9  # window (and its count) survives the refusal
    assert b.seconds_until_reset() > 0


@pytest.mark.parametrize("client_cls", _BUDGET_CLIENTS)
def test_budget_never_exceeds_the_cap_under_interleaved_reservations(client_cls):
    """Two runners racing the same counter must not both get the last slot."""
    r = client_cls()
    a = _budget(r, 10)
    b = _budget(r, 10)
    granted = sum(1 for budget in (a, b, a, b, a, b) if budget.try_consume(3))
    assert granted == 3  # 3+3+3 = 9 ≤ 10; the fourth would overshoot
    assert a.consumed() == 9


@pytest.mark.parametrize("client_cls", _BUDGET_CLIENTS)
def test_budget_window_roll_restarts_the_count(client_cls):
    r = client_cls()
    day1 = datetime.fromisoformat("2026-08-06T12:00:00+00:00")
    _budget(r, 10, now=day1).try_consume(9)
    later = day1 + timedelta(hours=25)
    rolled = _budget(r, 10, now=later)
    assert rolled.consumed() == 0
    # The stale count must not be added to: the fresh window starts at n.
    assert rolled.try_consume(4) is True
    assert rolled.consumed() == 4


@pytest.mark.parametrize("client_cls", _BUDGET_CLIENTS)
def test_budget_zero_or_negative_reservation_is_free(client_cls):
    r = client_cls()
    b = _budget(r, 10)
    assert b.try_consume(0) is True
    assert b.consumed() == 0


def test_budget_uses_the_atomic_script_when_the_client_has_eval():
    r = EvalRedis()
    assert _budget(r, 10).try_consume(3) is True
    assert r.eval_calls == 1  # went through Lua, not the multi-op fallback


def test_budget_window_roll_is_one_atomic_step_not_a_read_then_write():
    """The roll must not be a separate ``hset`` two writers can both perform."""
    r = EvalRedis()
    a, b = _budget(r, 10), _budget(r, 10)
    assert a.try_consume(4) is True   # opens the window at 4
    assert b.try_consume(4) is True   # must add to it, never restamp count=0
    assert a.consumed() == 8


# ---------------------------------------------------------------------------
# AttemptLedger.rollback_attempt
# ---------------------------------------------------------------------------


def test_ledger_rollback_undoes_one_attempt():
    r = FakeRedis()
    ledger = AttemptLedger(r, prefix="t", max_attempts=3)
    ledger.record_attempt("p1")
    ledger.record_attempt("p1")
    assert ledger.attempts("p1") == 2

    assert ledger.rollback_attempt("p1") == 1
    assert ledger.attempts("p1") == 1
    assert ledger.rollback_attempt("p1") == 0
    assert ledger.attempts("p1") == 0
    # Never goes negative, and the field is dropped entirely at zero.
    assert ledger.rollback_attempt("p1") == 0


# ---------------------------------------------------------------------------
# Scope → stages
# ---------------------------------------------------------------------------


def test_stages_for_the_default_scope_is_all():
    assert stages_for_task_classes(DEFAULT_BACKFILL_SCOPE) == "all"


@pytest.mark.parametrize(
    "classes,expected",
    [
        ({EnrichmentTaskClass.VISUAL, EnrichmentTaskClass.SENTIMENT}, "visual+sentiment"),
        ({EnrichmentTaskClass.DEAL_VERDICT}, "verdict_only"),
    ],
)
def test_stages_for_supported_scopes(classes, expected):
    assert stages_for_task_classes(classes) == expected


@pytest.mark.parametrize(
    "classes",
    [
        {EnrichmentTaskClass.VISUAL},
        {EnrichmentTaskClass.EMBEDDING},
        {EnrichmentTaskClass.VISUAL, EnrichmentTaskClass.DEAL_VERDICT},
        set(),
    ],
)
def test_unsupported_scope_raises_naming_the_classes(classes):
    with pytest.raises(ValueError) as exc:
        stages_for_task_classes(classes)
    for tc in classes:
        assert tc.value in str(exc.value)


def test_parse_task_classes_accepts_a_csv_string():
    got = parse_task_classes(" visual , DEAL_VERDICT ")
    assert got == frozenset(
        {EnrichmentTaskClass.VISUAL, EnrichmentTaskClass.DEAL_VERDICT}
    )


def test_parse_task_classes_rejects_an_unknown_name():
    with pytest.raises(ValueError) as exc:
        parse_task_classes("visual,teleport")
    assert "teleport" in str(exc.value)
    assert "sentiment" in str(exc.value)  # names the valid vocabulary


def test_parse_task_classes_rejects_empty_input():
    with pytest.raises(ValueError):
        parse_task_classes(" , ")


# ---------------------------------------------------------------------------
# Quota predicate
# ---------------------------------------------------------------------------


def test_quota_predicate_is_duck_typed_not_isinstance():
    assert is_quota_exhausted(_QuotaError("boom")) is True


def test_quota_predicate_matches_provider_wording():
    assert is_quota_exhausted(RuntimeError("RESOURCE_EXHAUSTED: quota")) is True
    assert is_quota_exhausted(RuntimeError("Too Many Requests")) is True


def test_quota_predicate_ignores_ordinary_failures():
    assert is_quota_exhausted(ValueError("bad json")) is False
    assert is_quota_exhausted(RuntimeError("Gemini API error: 500")) is False


# ---------------------------------------------------------------------------
# run_backfill — pause / stop / quota
# ---------------------------------------------------------------------------


def test_run_backfill_pause_holds_launches_then_resumes():
    r = FakeRedis()
    seen: list[str] = []

    async def enrich(prop):
        seen.append(prop.id)

    # Paused for two polls before row 0, then free.
    control = _ScriptedControl(paused=[True, True, False])

    result = asyncio.run(
        run_backfill(
            _rows(2),
            enrich_fn=enrich,
            budget=_budget(r, 100),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            sleep_fn=_noop_sleep,
            control=control,
            pause_poll_seconds=0.0,
        )
    )

    assert seen == ["prop-0", "prop-1"]  # pause holds, it does not drop rows
    assert result.processed == 2
    assert result.stopped is False
    assert BackfillState.PAUSED in control.states
    assert control.states[-1] is BackfillState.IDLE


def test_run_backfill_stop_breaks_and_keeps_the_checkpoint():
    r = FakeRedis()
    seen: list[str] = []

    async def enrich(prop):
        seen.append(prop.id)

    # Row 0 launches, then a stop lands.
    control = _ScriptedControl(stops=[False, True])

    result = asyncio.run(
        run_backfill(
            _rows(5),
            enrich_fn=enrich,
            budget=_budget(r, 100),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            sleep_fn=_noop_sleep,
            control=control,
        )
    )

    assert seen == ["prop-0"]  # already-launched row still finished
    assert result.stopped is True
    assert result.processed == 1
    assert _checkpoint(r).processed_total() == 1  # resume point survives
    assert control.states[-1] is BackfillState.IDLE


def test_run_backfill_ticks_progress_on_error_and_quota_rows_too():
    """The hook is the caller's heartbeat: a failing row must still tick it.

    It used to fire only in the success branch, so a storm of failing rows left
    the caller's ``:active`` heartbeat to expire while the run was very much
    alive.
    """
    r = FakeRedis()
    ticks: list[tuple[int, int, bool]] = []

    async def enrich(prop):
        if prop.id == "prop-0":
            raise ValueError("bad json")
        if prop.id == "prop-2":
            raise _QuotaError("429")

    asyncio.run(
        run_backfill(
            _rows(4),
            enrich_fn=enrich,
            budget=_budget(r, 100),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            sleep_fn=_noop_sleep,
            on_progress=lambda res: ticks.append(
                (res.processed, res.errors, res.quota_exhausted)
            ),
        )
    )

    # error row + success row + quota row — three finished rows, three ticks.
    assert len(ticks) == 3
    assert ticks[0] == (0, 1, False)  # the error row ticked
    assert ticks[-1][2] is True       # and so did the quota row


def test_run_backfill_does_not_tick_progress_while_paused():
    """A paused runner must stop beating the caller's ``:active`` heartbeat.

    That heartbeat is what ``migrate-primary.sh`` refuses on, so a paused run
    that kept ticking blocked the migration an operator paused *in order to*
    run. The lease is renewed from inside ``run_backfill`` instead.
    """
    r = FakeRedis()
    ticks: list[int] = []
    lease = BackfillLease(r, prefix="t", ttl_seconds=60)
    assert lease.acquire() is True
    control = _ScriptedControl(paused=[True, True, True, False])

    async def enrich(prop):
        return None

    asyncio.run(
        run_backfill(
            _rows(1),
            enrich_fn=enrich,
            budget=_budget(r, 100),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            sleep_fn=_noop_sleep,
            control=control,
            lease=lease,
            on_progress=lambda res: ticks.append(res.processed),
        )
    )

    assert ticks == [1]  # the processed row only — no pause polls
    assert lease.is_held_by_self() is True  # the pause kept the lease alive


def test_run_backfill_quota_error_writes_nothing_and_stops_launching():
    r = FakeRedis()
    ledger = AttemptLedger(r, prefix="t", max_attempts=3)
    calls: list[str] = []

    async def enrich(prop):
        calls.append(prop.id)
        raise _QuotaError("Gemini quota exhausted: 429")

    result = asyncio.run(
        run_backfill(
            _rows(5),
            enrich_fn=enrich,
            budget=_budget(r, 100),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            ledger=ledger,
            sleep_fn=_noop_sleep,
        )
    )

    assert calls == ["prop-0"]  # no further launches once quota is gone
    assert result.quota_exhausted is True
    assert result.budget_exhausted is True  # → the caller backs off
    assert result.errors == 0  # the row is not to blame
    assert result.error_ids == []
    assert result.processed == 0
    # Nothing was persisted for it: no checkpoint advance, no ledger attempt.
    assert _checkpoint(r).processed_total() == 0
    assert ledger.attempts("prop-0") == 0


def test_run_backfill_quota_publishes_backing_off_state():
    r = FakeRedis()
    control = _ScriptedControl()

    async def enrich(prop):
        raise _QuotaError("RESOURCE_EXHAUSTED")

    result = asyncio.run(
        run_backfill(
            _rows(3),
            enrich_fn=enrich,
            budget=_budget(r, 100),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            sleep_fn=_noop_sleep,
            control=control,
        )
    )

    assert result.quota_exhausted is True
    assert control.states[0] is BackfillState.RUNNING
    assert control.states[-1] is BackfillState.BACKING_OFF


def test_run_backfill_ordinary_error_still_counts_and_continues():
    """The quota branch must not swallow real per-row failures."""
    r = FakeRedis()
    ledger = AttemptLedger(r, prefix="t", max_attempts=5)

    async def enrich(prop):
        if prop.id == "prop-0":
            raise ValueError("bad json")

    result = asyncio.run(
        run_backfill(
            _rows(3),
            enrich_fn=enrich,
            budget=_budget(r, 100),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            ledger=ledger,
            sleep_fn=_noop_sleep,
        )
    )

    assert result.errors == 1
    assert result.error_ids == ["prop-0"]
    assert result.processed == 2
    assert result.quota_exhausted is False
    assert ledger.attempts("prop-0") == 1  # a real failure IS charged


def test_run_backfill_quota_classification_can_be_disabled():
    r = FakeRedis()

    async def enrich(prop):
        raise _QuotaError("429")

    result = asyncio.run(
        run_backfill(
            _rows(1),
            enrich_fn=enrich,
            budget=_budget(r, 100),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            sleep_fn=_noop_sleep,
            is_quota_error=None,
        )
    )

    assert result.quota_exhausted is False
    assert result.errors == 1


# ---------------------------------------------------------------------------
# run_backfill against a REAL BackfillControl (level, not event, semantics)
# ---------------------------------------------------------------------------
#
# The ``_ScriptedControl`` double pops each value once, which is *event*
# semantics. ``BackfillControl`` documents *levels* — a pause key stays set
# until someone resumes — so a regression that made ``is_paused()`` consume the
# key would pass every scripted test and still break a real pause. These drive
# the real object against the fake Redis.


def _run_with_real_control(rows, *, enrich, redis, control, sleep_fn=None, **kw):
    return asyncio.run(
        run_backfill(
            rows,
            enrich_fn=enrich,
            budget=_budget(redis, 1000),
            checkpoint=_checkpoint(redis),
            requests_per_property=3,
            sleep_fn=sleep_fn or _noop_sleep,
            control=control,
            pause_poll_seconds=0.0,
            **kw,
        )
    )


def test_real_control_pause_holds_across_many_polls_then_resumes():
    r = FakeRedis()
    control = BackfillControl(r, prefix="t")
    control.request_pause()
    seen: list[str] = []
    polls = {"n": 0}

    async def sleep_fn(_seconds):
        polls["n"] += 1
        if polls["n"] >= 5:  # an operator finally resumes
            control.request_resume()

    async def enrich(prop):
        seen.append(prop.id)

    result = _run_with_real_control(
        _rows(2), enrich=enrich, redis=r, control=control, sleep_fn=sleep_fn
    )

    # A pause that survives five polls: reading the key must not consume it.
    assert polls["n"] == 5
    assert seen == ["prop-0", "prop-1"]  # held, never dropped
    assert result.processed == 2
    assert result.stopped is False
    assert control.is_paused() is False
    assert control.state() is BackfillState.IDLE


def test_real_control_pause_outstanding_before_the_run_is_observed():
    """A request issued before the runner started is still a level it must see."""
    r = FakeRedis()
    control = BackfillControl(r, prefix="t")
    control.request_pause()
    polls = {"n": 0}

    async def sleep_fn(_seconds):
        polls["n"] += 1
        control.request_resume()

    async def enrich(prop):
        return None

    _run_with_real_control(
        _rows(1), enrich=enrich, redis=r, control=control, sleep_fn=sleep_fn
    )

    assert polls["n"] == 1  # it paused at once rather than launching first
    assert control.state() is BackfillState.IDLE


def test_real_control_pending_stop_launches_nothing():
    r = FakeRedis()
    control = BackfillControl(r, prefix="t")
    control.request_stop()
    seen: list[str] = []

    async def enrich(prop):
        seen.append(prop.id)

    result = _run_with_real_control(_rows(5), enrich=enrich, redis=r, control=control)

    assert seen == []
    assert result.stopped is True
    assert result.processed == 0
    assert control.should_stop() is True  # a level: reading it does not clear it


def test_real_control_stop_mid_run_drains_and_keeps_the_checkpoint():
    r = FakeRedis()
    control = BackfillControl(r, prefix="t")
    seen: list[str] = []

    async def enrich(prop):
        seen.append(prop.id)
        if prop.id == "prop-0":
            control.request_stop()  # operator stops while row 0 is in flight

    result = _run_with_real_control(_rows(6), enrich=enrich, redis=r, control=control)

    assert result.stopped is True
    assert 0 < len(seen) < 6  # stopped early, but launched rows still finished
    assert result.processed == len(seen)
    assert _checkpoint(r).processed_total() == result.processed
    assert control.state() is BackfillState.IDLE


# ---------------------------------------------------------------------------
# run_backfill — lease renewal / lease loss
# ---------------------------------------------------------------------------


def test_run_backfill_renews_the_lease_through_rows_that_only_fail():
    """The old design renewed from ``on_progress``, which failing rows skipped."""
    r = FakeRedis()
    lease = BackfillLease(r, prefix="t", ttl_seconds=60)
    assert lease.acquire() is True
    r.expires["t:lease"] = 1  # pretend the TTL has nearly run out

    async def enrich(prop):
        raise ValueError("every row fails")

    result = asyncio.run(
        run_backfill(
            _rows(3),
            enrich_fn=enrich,
            budget=_budget(r, 100),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            sleep_fn=_noop_sleep,
            lease=lease,
        )
    )

    assert result.errors == 3
    assert result.lease_lost is False
    assert r.expires["t:lease"] == 60  # renewed despite zero successful rows


def test_run_backfill_stops_launching_when_the_owner_loses_its_own_lease():
    """Not an intruder being refused — *this* runner discovering it lost it.

    Losing the lease means another runner may already own the queue, so a
    process that kept launching would be a second writer against the same rows.
    """
    r = FakeRedis()
    lease = BackfillLease(r, prefix="t", ttl_seconds=60, owner="me:1")
    assert lease.acquire() is True
    seen: list[str] = []

    async def enrich(prop):
        seen.append(prop.id)
        # The lease TTL lapsed and a second runner took it over.
        r.kv["t:lease"] = "another-runners-token"

    result = asyncio.run(
        run_backfill(
            _rows(8),
            enrich_fn=enrich,
            budget=_budget(r, 1000),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            sleep_fn=_noop_sleep,
            lease=lease,
        )
    )

    assert result.lease_lost is True
    assert result.to_dict()["lease_lost"] is True
    assert 0 < len(seen) < 8  # already-launched rows drained; nothing new started
    assert result.stopped is False  # a lost lease is not an operator stop
    assert r.kv["t:lease"] == "another-runners-token"  # never stolen back


def test_run_backfill_lease_lost_during_a_pause_ends_the_run():
    r = FakeRedis()
    lease = BackfillLease(r, prefix="t", ttl_seconds=60)
    assert lease.acquire() is True
    control = BackfillControl(r, prefix="t")
    control.request_pause()

    async def sleep_fn(_seconds):
        r.kv["t:lease"] = "someone-else"  # taken over while we were paused

    async def enrich(prop):
        raise AssertionError("nothing may launch after the lease is gone")

    result = _run_with_real_control(
        _rows(3),
        enrich=enrich,
        redis=r,
        control=control,
        sleep_fn=sleep_fn,
        lease=lease,
    )

    assert result.lease_lost is True
    assert result.stopped is False
    assert result.processed == 0


def test_run_backfill_republishes_running_so_the_state_key_stays_fresh():
    """The state key TTLs out in 120s; one publish at start-up is not enough."""
    r = FakeRedis()
    control = _ScriptedControl()
    ticks = iter([0.0] + [60.0 * i for i in range(1, 40)])

    async def enrich(prop):
        return None

    asyncio.run(
        run_backfill(
            _rows(4),
            enrich_fn=enrich,
            budget=_budget(r, 1000),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            sleep_fn=_noop_sleep,
            control=control,
            clock=lambda: next(ticks),
        )
    )

    running = [s for s in control.states if s is BackfillState.RUNNING]
    assert len(running) > 1  # refreshed while working, not published once


def test_run_backfill_without_control_is_unchanged():
    """Every new parameter defaults to today's behaviour."""
    r = FakeRedis()

    async def enrich(prop):
        return None

    result = asyncio.run(
        run_backfill(
            _rows(3),
            enrich_fn=enrich,
            budget=_budget(r, 100),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            sleep_fn=_noop_sleep,
        )
    )

    assert result.processed == 3
    assert result.stopped is False
    assert result.paused_seconds == 0.0
    assert result.to_dict()["quota_exhausted"] is False


# ---------------------------------------------------------------------------
# run_backfill — background lease renewer (v0.13-fu7, DW-6)
# ---------------------------------------------------------------------------


def test_the_background_renewer_ticks_while_a_single_slow_row_is_in_flight():
    """DW-6: nothing renewed the lease *while* one long row was being enriched.

    Every renewal used to be event-driven — one per launch-loop iteration, one
    per pause poll, one per finished row — so a single property whose ~3 cloud
    calls outlived the TTL let the lease lapse under a live writer.
    """
    r = EvalRedis()
    lease = BackfillLease(r, prefix="t", ttl_seconds=60)
    assert lease.acquire() is True
    gate = asyncio.Event()
    renewals = {"n": 0}
    at_row_start = {"n": -1}
    during_the_row = {"renewals": -1, "ttl": -1}
    polls = {"n": 0}

    original_renew = lease.renew

    def counting_renew():
        renewals["n"] += 1
        return original_renew()

    lease.renew = counting_renew  # type: ignore[method-assign]

    async def lease_sleeper(_seconds):
        # The yield comes first *on purpose*: it is what lets the worker reach
        # ``enrich`` and record ``at_row_start`` before this tick's renew, so
        # the two counters below are captured in the right order. Swapping
        # these two lines silently breaks the comparison, hence the sentinel
        # assertion at the end of the test.
        await asyncio.sleep(0)
        polls["n"] += 1
        if polls["n"] == 2:
            # One renewer tick has fired since the row started; the row is still
            # in flight (the gate opens only now).
            during_the_row["renewals"] = renewals["n"]
            during_the_row["ttl"] = r.expires["t:lease"]
            gate.set()

    async def enrich(_prop):
        r.expires["t:lease"] = 1  # the TTL has all but run out under this row
        at_row_start["n"] = renewals["n"]
        await gate.wait()

    result = asyncio.run(
        asyncio.wait_for(
            run_backfill(
                _rows(1),
                enrich_fn=enrich,
                budget=_budget(r, 100),
                checkpoint=_checkpoint(r),
                requests_per_property=3,
                sleep_fn=_noop_sleep,
                lease=lease,
                lease_sleep_fn=lease_sleeper,
            ),
            timeout=5,
        )
    )

    assert at_row_start["n"] >= 0  # the row really was in flight when it ticked
    assert during_the_row["renewals"] > at_row_start["n"]  # renewed mid-row
    assert during_the_row["ttl"] == 60  # ... and the TTL was restored
    assert result.processed == 1
    assert result.lease_lost is False


def test_the_renewer_losing_the_lease_mid_row_stops_further_launches():
    """A lease taken over mid-row must stop launches at the next observation.

    The launch loop can be parked in ``sem.acquire()`` for minutes, so the flag
    is re-checked there as well — otherwise the row waiting for that slot is
    launched against a queue another runner already owns.
    """
    r = EvalRedis()
    lease = BackfillLease(r, prefix="t", ttl_seconds=60, owner="me:1")
    assert lease.acquire() is True
    gate = asyncio.Event()
    seen: list[str] = []

    async def lease_sleeper(_seconds):
        await asyncio.sleep(0)
        r.kv["t:lease"] = "another-runners-token"  # taken over mid-row
        gate.set()

    async def enrich(prop):
        seen.append(prop.id)
        await gate.wait()

    result = asyncio.run(
        asyncio.wait_for(
            run_backfill(
                _rows(6),
                enrich_fn=enrich,
                budget=_budget(r, 1000),
                checkpoint=_checkpoint(r),
                requests_per_property=3,
                concurrency=1,
                sleep_fn=_noop_sleep,
                lease=lease,
                lease_sleep_fn=lease_sleeper,
            ),
            timeout=5,
        )
    )

    assert result.lease_lost is True
    assert result.stopped is False  # a lost lease is not an operator stop
    # Row 1 was already waiting on the semaphore when the lease went: the
    # re-check after ``sem.acquire()`` is what keeps it from being launched.
    assert seen == ["prop-0"]
    assert r.kv["t:lease"] == "another-runners-token"  # never stolen back


def test_the_renewer_task_is_cancelled_when_the_run_returns():
    """A leaked timer task would keep renewing a lease this run has finished with.

    ``lease_sleep_fn`` here never suspends, which is also the regression the
    renewer's own ``asyncio.sleep(0)`` guards: without that yield the timer
    would spin and the run would never complete.
    """
    r = EvalRedis()
    lease = BackfillLease(r, prefix="t", ttl_seconds=60)
    assert lease.acquire() is True

    async def enrich(_prop):
        return None

    async def scenario():
        await asyncio.wait_for(
            run_backfill(
                _rows(3),
                enrich_fn=enrich,
                budget=_budget(r, 100),
                checkpoint=_checkpoint(r),
                requests_per_property=3,
                sleep_fn=_noop_sleep,
                lease=lease,
                lease_sleep_fn=_noop_sleep,
            ),
            timeout=5,
        )
        return {t for t in asyncio.all_tasks() if t is not asyncio.current_task()}

    assert asyncio.run(scenario()) == set()


def test_the_renewer_task_is_cancelled_when_the_launch_loop_raises():
    """The original exception must reach the caller, with nothing left pending.

    Cancelling the renewer happens after the in-flight drain and swallows only
    its own ``CancelledError``, so it can never replace what the loop raised.
    """
    r = EvalRedis()
    lease = BackfillLease(r, prefix="t", ttl_seconds=60)
    assert lease.acquire() is True
    gate = asyncio.Event()
    drained: list[str] = []

    def exploding_rows():
        yield from _rows(1)
        raise ConnectionError("redis went away mid-iteration")

    async def lease_sleeper(_seconds):
        # The gate opens only from the timer, so the row can finish *only*
        # while the renewer is still alive — which is the drain window the
        # cancellation must not close early.
        await asyncio.sleep(0)
        gate.set()

    async def enrich(prop):
        await gate.wait()
        drained.append(prop.id)

    async def scenario():
        with pytest.raises(ConnectionError):
            await asyncio.wait_for(
                run_backfill(
                    exploding_rows(),
                    enrich_fn=enrich,
                    budget=_budget(r, 100),
                    checkpoint=_checkpoint(r),
                    requests_per_property=3,
                    sleep_fn=_noop_sleep,
                    lease=lease,
                    lease_sleep_fn=lease_sleeper,
                ),
                timeout=5,
            )
        return {t for t in asyncio.all_tasks() if t is not asyncio.current_task()}

    assert asyncio.run(scenario()) == set()
    assert drained == ["prop-0"]  # the row in flight when it raised still drained


def test_a_redis_blip_inside_the_renewer_never_aborts_the_run():
    """Bookkeeping never fails a run — and a raise is not a lost lease.

    The timer keeps ticking after a failed ``renew()``; propagating it out of
    the background task would abandon rows that are still enriching.
    """
    r = EvalRedis()
    lease = BackfillLease(r, prefix="t", ttl_seconds=60)
    assert lease.acquire() is True
    gate = asyncio.Event()
    polls = {"n": 0}
    raised = {"n": 0}

    original_renew = lease.renew

    def renew_that_blips():
        # Only the renewer renews inside this window: the launch loop has
        # already exhausted its single row and the worker is still gated.
        if polls["n"] >= 1 and not gate.is_set():
            raised["n"] += 1
            raise ConnectionError("redis blip")
        return original_renew()

    lease.renew = renew_that_blips  # type: ignore[method-assign]

    async def lease_sleeper(_seconds):
        await asyncio.sleep(0)
        polls["n"] += 1
        if polls["n"] >= 3:
            gate.set()

    async def enrich(_prop):
        await gate.wait()

    result = asyncio.run(
        asyncio.wait_for(
            run_backfill(
                _rows(1),
                enrich_fn=enrich,
                budget=_budget(r, 100),
                checkpoint=_checkpoint(r),
                requests_per_property=3,
                sleep_fn=_noop_sleep,
                lease=lease,
                lease_sleep_fn=lease_sleeper,
            ),
            timeout=5,
        )
    )

    assert raised["n"] >= 1  # the renewer really did hit the blip
    assert result.processed == 1
    assert result.lease_lost is False  # a raise is not a refusal


def test_a_raising_sleep_does_not_kill_the_renewer():
    """The reason the *whole* renewer body is guarded, not just ``renew()``.

    A sleep seam that raises would otherwise end the timer silently and reopen
    DW-6 for the rest of the run, with nothing observing it until the run
    finished. The timer has to survive its own sleep failing.
    """
    r = EvalRedis()
    lease = BackfillLease(r, prefix="t", ttl_seconds=60)
    assert lease.acquire() is True
    gate = asyncio.Event()
    calls = {"n": 0}

    async def lease_sleeper(_seconds):
        calls["n"] += 1
        await asyncio.sleep(0)
        if calls["n"] == 1:
            raise RuntimeError("the injected timer seam blew up")
        # Only a *surviving* timer ever reaches this: the row is gated open
        # from the tick after the raise, so the run cannot finish otherwise.
        gate.set()

    async def enrich(_prop):
        await gate.wait()

    result = asyncio.run(
        asyncio.wait_for(
            run_backfill(
                _rows(1),
                enrich_fn=enrich,
                budget=_budget(r, 100),
                checkpoint=_checkpoint(r),
                requests_per_property=3,
                sleep_fn=_noop_sleep,
                lease=lease,
                lease_sleep_fn=lease_sleeper,
            ),
            timeout=5,
        )
    )

    assert calls["n"] >= 2  # it ticked again after its sleep raised
    assert result.processed == 1
    assert result.lease_lost is False


def test_no_background_task_is_created_when_no_lease_is_supplied():
    """``lease=None`` stays byte-identical to today: row workers only."""

    async def scenario(lease, r):
        # Names of the coroutines running while the single row is in flight —
        # asserting on identity, not on a count, so this cannot pass because
        # some *other* task happened to exist.
        live: set[str] = set()

        async def enrich(_prop):
            live.update(
                getattr(t.get_coro(), "__name__", "?") for t in asyncio.all_tasks()
            )

        await asyncio.wait_for(
            run_backfill(
                _rows(1),
                enrich_fn=enrich,
                budget=_budget(r, 100),
                checkpoint=_checkpoint(r),
                requests_per_property=3,
                concurrency=1,
                sleep_fn=_noop_sleep,
                lease=lease,
                lease_sleep_fn=_noop_sleep,
            ),
            timeout=5,
        )
        return live

    r = EvalRedis()
    held = BackfillLease(r, prefix="t", ttl_seconds=60)
    assert held.acquire() is True

    without_lease = asyncio.run(scenario(None, EvalRedis()))
    with_lease = asyncio.run(scenario(held, r))

    assert "_renew_lease_periodically" in with_lease
    assert "_renew_lease_periodically" not in without_lease


def test_nothing_publishes_state_after_the_renewer_loses_the_lease():
    """The state key belongs to whoever took the lease over.

    The closing publish was already guarded, but the timer can lose the lease
    with rows still draining — and each drained row's ``_tick_lease`` refreshes
    the state, stamping this runner's liveness over its successor's.
    """
    r = EvalRedis()
    lease = BackfillLease(r, prefix="t", ttl_seconds=60)
    assert lease.acquire() is True
    control = _ScriptedControl()
    gate = asyncio.Event()
    at_loss = {"n": -1}
    # Every read jumps ten minutes, so every ``_refresh_state`` is due.
    ticks = iter([600.0 * i for i in range(200)])

    async def lease_sleeper(_seconds):
        await asyncio.sleep(0)
        if not gate.is_set():
            r.kv["t:lease"] = "another-runners-token"
            at_loss["n"] = len(control.states)
            gate.set()

    async def enrich(_prop):
        await gate.wait()

    result = asyncio.run(
        asyncio.wait_for(
            run_backfill(
                _rows(4),
                enrich_fn=enrich,
                budget=_budget(r, 100),
                checkpoint=_checkpoint(r),
                requests_per_property=3,
                concurrency=1,
                sleep_fn=_noop_sleep,
                clock=lambda: next(ticks),
                control=control,
                lease=lease,
                lease_sleep_fn=lease_sleeper,
            ),
            timeout=5,
        )
    )

    assert result.lease_lost is True
    assert at_loss["n"] >= 0  # the loss really happened mid-run
    assert len(control.states) == at_loss["n"]  # nothing published after it


def test_the_renewer_interval_defaults_to_a_third_of_the_ttl_and_is_clamped_both_ways():
    """The cadence is the whole fix: a slower one silently reinstates DW-6.

    Nothing else pins it — flip the default to ``ttl * 3`` and every other test
    in this block still passes, because they drive the timer through an
    injected sleep that ignores the interval it is handed.
    """

    def intervals_for(**kwargs):
        r = EvalRedis()
        lease = BackfillLease(r, prefix="t", ttl_seconds=60)
        assert lease.acquire() is True
        slept: list[float] = []

        async def lease_sleeper(seconds):
            slept.append(seconds)
            await asyncio.sleep(0)

        async def enrich(_prop):
            await asyncio.sleep(0)

        asyncio.run(
            asyncio.wait_for(
                run_backfill(
                    _rows(2),
                    enrich_fn=enrich,
                    budget=_budget(r, 100),
                    checkpoint=_checkpoint(r),
                    requests_per_property=3,
                    sleep_fn=_noop_sleep,
                    lease=lease,
                    lease_sleep_fn=lease_sleeper,
                    **kwargs,
                ),
                timeout=5,
            )
        )
        assert slept, "the timer never ticked"
        return set(slept)

    assert intervals_for() == {20.0}  # ttl / 3
    assert intervals_for(lease_renew_interval=1.5) == {1.5}  # tighter is allowed
    assert intervals_for(lease_renew_interval=99_999) == {20.0}  # slower is not
    # A non-positive interval would make the timer a Redis busy-spin; the floor
    # is the same defence ``pause_poll_seconds`` gets one screen above it.
    assert intervals_for(lease_renew_interval=0) == {0.05}
    assert intervals_for(lease_renew_interval=-5) == {0.05}


# ---------------------------------------------------------------------------
# MigrationGate — mutual exclusion with migrate-primary.sh (v0.13-fu6, DW-3/DW-4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("client_cls", [FakeRedis, BytesRedis])
def test_migration_gate_reads_the_key_the_script_writes(client_cls):
    r = client_cls()
    gate = MigrationGate(r, prefix="t")

    assert gate.key == "t:migrating"
    assert gate.is_migrating() is False
    assert gate.holder_token() is None

    # Exactly what migrate-primary.sh writes: the key carries its token.
    r.set("t:migrating", "migrate-primary:host:42:1754500000")
    assert gate.is_migrating() is True
    assert gate.holder_token() == "migrate-primary:host:42:1754500000"


def test_migration_gate_reads_the_key_with_get_and_names_the_holder():
    """The refusal names the holder, and every Redis double here implements ``get``.

    ``exists`` would work against a real client and blow up on the minimal fakes
    the backfill CLI tests use — and it could not report which invocation holds
    the key.
    """

    class _GetOnlyRedis:
        """Exactly the surface the gate is allowed to use."""

        def __init__(self) -> None:
            self.kv: dict[str, str] = {}
            self.reads: list[str] = []

        def get(self, key):
            self.reads.append(key)
            return self.kv.get(key)

    r = _GetOnlyRedis()
    r.kv["t:migrating"] = "migrate-primary:host:42:1754500000"
    gate = MigrationGate(r, prefix="t")

    assert gate.is_migrating() is True
    assert gate.holder_token() == "migrate-primary:host:42:1754500000"
    # The requirement is *which* key it reads, not how many round-trips it takes
    # — pinning the call count would fail a memoising gate that is just as correct.
    assert set(r.reads) == {"t:migrating"}


def _script_half(r):
    """``migrate-primary.sh``'s set-then-check, as its two observable steps."""
    state = {}

    def acquire():
        state["took"] = bool(r.set("t:migrating", "migrate-primary:tok", nx=True, ex=1800))

    def proceed() -> bool:
        # Won the lock AND no live heartbeat — the script's two refusal points.
        return bool(state["took"]) and r.get("t:active") is None

    return acquire, proceed


def _runner_half(r):
    """The runner's set-then-check: beat ``:active``, then read ``:migrating``."""
    heartbeat = Heartbeat(r, prefix="t")
    gate = MigrationGate(r, prefix="t")
    return heartbeat.beat, lambda: not gate.is_migrating()


@pytest.mark.parametrize("script_first", [True, False], ids=["script-first", "runner-first"])
def test_the_two_halves_are_mutually_exclusive_in_both_interleavings(script_first):
    """The headline AC: in any interleaving, at least one side refuses.

    Both halves against ONE Redis, fully interleaved. If the runner does not see
    ``:migrating`` its read happened before the script's write, so its heartbeat
    was already there when the script probed — and the script refuses. Symmetric
    the other way. Both refusing is safe (``--continuous`` waits); both
    proceeding is the bug this feature exists to make impossible.
    """
    r = FakeRedis()
    acquire, script_proceeds = _script_half(r)
    beat, runner_proceeds = _runner_half(r)

    if script_first:
        acquire()
        beat()
        script_ok = script_proceeds()
        runner_ok = runner_proceeds()
    else:
        beat()
        acquire()
        runner_ok = runner_proceeds()
        script_ok = script_proceeds()

    assert not (script_ok and runner_ok), (
        "both the migration and the backfill runner proceeded against the same "
        "primary DB"
    )
    assert (script_ok, runner_ok) == (False, False)  # this interleaving refuses both


def test_an_uncontended_migration_and_an_uncontended_runner_each_proceed():
    """The guard must not be a permanent refusal — the other half of the AC."""
    r = FakeRedis()
    acquire, script_proceeds = _script_half(r)
    acquire()
    assert script_proceeds() is True  # nobody beat :active

    r.delete("t:migrating")  # the migration finished and released it
    beat, runner_proceeds = _runner_half(r)
    beat()
    assert runner_proceeds() is True


def test_run_backfill_launches_nothing_while_a_migration_holds_the_key():
    """DW-3: a runner must not write into a schema ``alembic`` is upgrading."""
    r = FakeRedis()
    seen: list[str] = []

    async def enrich(prop):
        seen.append(prop.id)

    result = asyncio.run(
        run_backfill(
            _rows(3),
            enrich_fn=enrich,
            budget=_budget(r, 100),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            sleep_fn=_noop_sleep,
            is_migrating=lambda: True,
        )
    )

    assert seen == []
    assert result.migration_blocked is True
    assert result.processed == 0
    assert result.requests_consumed == 0  # no budget spent on a blocked pass
    # A blocked pass is not a stall, a stop, or a completion.
    assert result.stopped is False
    assert _checkpoint(r).processed_total() == 0
    assert result.to_dict()["migration_blocked"] is True


def test_run_backfill_stops_launching_when_a_migration_starts_mid_run():
    r = FakeRedis()
    seen: list[str] = []
    reads = {"n": 0}

    def is_migrating():
        reads["n"] += 1
        # Two reads per row — at the loop head and again after ``sem.acquire()``,
        # because minutes of launch-interval/TPM/semaphore waiting sit between
        # them — so the migration lands after two rows launched.
        return reads["n"] > 4

    async def enrich(prop):
        seen.append(prop.id)

    result = asyncio.run(
        run_backfill(
            _rows(5),
            enrich_fn=enrich,
            budget=_budget(r, 100),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            sleep_fn=_noop_sleep,
            is_migrating=is_migrating,
        )
    )

    assert seen == ["prop-0", "prop-1"]  # in-flight rows still drained
    assert result.migration_blocked is True
    assert result.processed == 2
    assert _checkpoint(r).processed_total() == 2  # resume point survives


def test_run_backfill_rechecks_the_migration_after_waiting_for_a_slot():
    """The loop-head check can be minutes stale by the time a slot frees up.

    ``launch_interval``, the TPM window and ``sem.acquire()`` all sit between the
    head check and the actual launch — the same reason the ``quota_exhausted``
    re-check exists right there. Without it, a migration starting in that window
    still gets one row launched into it, and its budget spent.
    """
    r = FakeRedis()
    seen: list[str] = []
    reads = {"n": 0}

    def is_migrating():
        reads["n"] += 1
        return reads["n"] == 2  # free at the loop head, held after the acquire

    async def enrich(prop):
        seen.append(prop.id)

    result = asyncio.run(
        run_backfill(
            _rows(3),
            enrich_fn=enrich,
            budget=_budget(r, 100),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            sleep_fn=_noop_sleep,
            is_migrating=is_migrating,
        )
    )

    assert seen == []
    assert result.migration_blocked is True
    assert result.requests_consumed == 0  # the row cost nothing


def test_run_backfill_migration_during_a_pause_is_not_reported_as_stopped():
    """A pause could end at any poll — the resume must see the migration first."""
    r = FakeRedis()
    seen: list[str] = []
    reads = {"n": 0}

    def is_migrating():
        reads["n"] += 1
        return reads["n"] >= 2  # free at the loop head, held at the pause poll

    async def enrich(prop):
        seen.append(prop.id)

    control = _ScriptedControl(paused=[True, True, False])

    result = asyncio.run(
        run_backfill(
            _rows(2),
            enrich_fn=enrich,
            budget=_budget(r, 100),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            sleep_fn=_noop_sleep,
            control=control,
            is_migrating=is_migrating,
            pause_poll_seconds=0.0,
        )
    )

    assert seen == []
    assert result.migration_blocked is True
    # ``stopped`` would tell the CLI an operator ended this run and make
    # --continuous exit EXIT_STOPPED instead of waiting the migration out.
    assert result.stopped is False


def test_run_backfill_without_a_migration_gate_never_blocks():
    """``is_migrating=None`` (story 1.5's API, dry runs) is today's behaviour."""
    r = FakeRedis()

    async def enrich(prop):
        return None

    result = asyncio.run(
        run_backfill(
            _rows(2),
            enrich_fn=enrich,
            budget=_budget(r, 100),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            sleep_fn=_noop_sleep,
        )
    )

    assert result.processed == 2
    assert result.migration_blocked is False


# ---------------------------------------------------------------------------
# Follow-up review pass (v0.13-s1.3): regressions for the review-driven fixes
# ---------------------------------------------------------------------------


def test_raising_progress_hook_does_not_wedge_the_launch_loop():
    """A caller-supplied hook must never skip ``sem.release()``.

    ``on_progress`` used to run *before* the release in the worker's ``finally``
    without a guard, so a hook that raised left the semaphore permanently down.
    With ``concurrency=1`` the launch loop then blocked on ``sem.acquire()``
    forever — holding the lease, renewing nothing, and hanging rather than
    failing. The run must still finish every row.
    """
    r = FakeRedis()
    seen = []

    async def enrich(prop):
        seen.append(prop.id)

    def exploding_hook(_res):
        raise RuntimeError("bookkeeping backend is down")

    result = asyncio.run(
        asyncio.wait_for(
            run_backfill(
                _rows(3),
                enrich_fn=enrich,
                budget=_budget(r, 100),
                checkpoint=_checkpoint(r),
                requests_per_property=3,
                concurrency=1,
                sleep_fn=_noop_sleep,
                on_progress=exploding_hook,
            ),
            timeout=5,
        )
    )

    assert seen == ["prop-0", "prop-1", "prop-2"]
    assert result.processed == 3


def test_worker_renews_the_lease_so_the_final_drain_is_covered():
    """The launch loop stops renewing once it breaks — the drain must not.

    Renewing only per launch-loop iteration left the closing
    ``asyncio.gather`` running on a lease nobody refreshed.
    """
    r = EvalRedis()
    lease = BackfillLease(r, prefix="t", ttl_seconds=900)
    assert lease.acquire()
    renewals = []

    original_renew = lease.renew

    def counting_renew():
        renewals.append(1)
        return original_renew()

    lease.renew = counting_renew  # type: ignore[method-assign]

    async def enrich(_prop):
        return None

    asyncio.run(
        run_backfill(
            _rows(2),
            enrich_fn=enrich,
            budget=_budget(r, 100),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            sleep_fn=_noop_sleep,
            lease=lease,
        )
    )

    # 2 launch-loop ticks + 2 worker ticks: strictly more than the loop alone.
    assert len(renewals) > 2


def test_lease_tick_failure_in_a_worker_never_aborts_the_run():
    """A Redis blip on the *worker's* renew must not abandon in-flight rows.

    The worker tick lives in the same ``finally`` as ``sem.release()``, so a
    raise there would strand the semaphore and wedge the launch loop. The
    launch-loop tick is deliberately left unguarded — it runs between rows, with
    nothing in flight to strand.
    """
    r = FakeRedis()
    lease = BackfillLease(r, prefix="t", ttl_seconds=900)
    assert lease.acquire()
    just_enriched = {"flag": False}

    def flaky_renew():
        if just_enriched["flag"]:
            just_enriched["flag"] = False
            raise ConnectionError("redis blip")
        return True

    lease.renew = flaky_renew  # type: ignore[method-assign]

    async def enrich(_prop):
        just_enriched["flag"] = True

    result = asyncio.run(
        run_backfill(
            _rows(3),
            enrich_fn=enrich,
            budget=_budget(r, 100),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            sleep_fn=_noop_sleep,
            lease=lease,
        )
    )

    assert result.processed == 3
    assert result.lease_lost is False


def test_paused_state_is_republished_before_the_key_can_decay():
    """A pause longer than the state TTL must not read back as ``idle``.

    ``publish_state`` writes with a 120s TTL, so publishing ``paused`` once made
    a long hold look like a dead runner to ``--status`` and story 1.5's API.
    """
    from core.backfill_runner import _STATE_REFRESH_SECONDS

    r = FakeRedis()
    control = BackfillControl(r, prefix="t")
    control.request_pause()
    ticks = {"n": 0}

    # Each poll advances the clock past the refresh interval; the third poll
    # lifts the pause so the run can finish.
    def clock():
        return ticks["n"] * (_STATE_REFRESH_SECONDS + 1)

    async def sleep_fn(_):
        ticks["n"] += 1
        if ticks["n"] >= 3:
            control.request_resume()

    published = []
    original_publish = control.publish_state

    def recording_publish(state):
        published.append(state)
        original_publish(state)

    control.publish_state = recording_publish  # type: ignore[method-assign]

    async def enrich(_prop):
        return None

    asyncio.run(
        run_backfill(
            _rows(1),
            enrich_fn=enrich,
            budget=_budget(r, 100),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            sleep_fn=sleep_fn,
            clock=clock,
            control=control,
            pause_poll_seconds=0.0,
        )
    )

    assert published.count(BackfillState.PAUSED) > 1


def test_request_resume_clears_a_pending_stop_too():
    """"Resume" means both keys — story 1.5 calls this method, not the CLI's.

    Clearing only the pause key left an outstanding stop in force, so the runner
    resumed and immediately stopped while the caller was told it would continue.
    """
    r = FakeRedis()
    control = BackfillControl(r, prefix="t")
    control.request_pause()
    control.request_stop()

    control.request_resume()

    assert control.is_paused() is False
    assert control.should_stop() is False


def test_clear_stop_retires_a_served_request():
    """A honored stop must not linger and be re-reported as pending."""
    r = FakeRedis()
    control = BackfillControl(r, prefix="t")
    control.request_pause()
    control.request_stop()

    control.clear_stop()

    assert control.should_stop() is False
    assert control.is_paused() is True  # only the stop was retired


def test_lease_cas_reply_as_bytes_is_not_read_as_success():
    """``bool(b"0")`` is ``True`` — a refused renew must not read as owned.

    The decode fallback turned a *lost* lease into a held one for any client
    handing back the Lua reply as bytes: two writers, silently.
    """

    class BytesReplyRedis(FakeRedis):
        def eval(self, script, numkeys, key, *args):
            return b"0"

    r = BytesReplyRedis()
    lease = BackfillLease(r, prefix="t", ttl_seconds=900)

    assert lease.renew() is False
    assert lease.release() is False


def test_budget_reply_as_bytes_is_not_read_as_a_reservation():
    """Same decode trap on the budget's atomic branch."""

    class BytesReplyRedis(FakeRedis):
        def eval(self, script, numkeys, key, *args):
            return b"0"

    budget = _budget(BytesReplyRedis(), 100)

    assert budget.try_consume(3) is False


# ---------------------------------------------------------------------------
# Follow-up review pass 3 (v0.13-s1.3)
# ---------------------------------------------------------------------------


def test_launch_loop_failure_still_drains_in_flight_rows():
    """A Redis blip in the loop must not abandon rows already launched.

    Every control/budget/ledger read in the launch loop can raise. Letting that
    escape with tasks pending left ``asyncio.run`` to cancel in-flight
    enrichments at an arbitrary await point — mid-call, mid-write. The drain is
    now a ``finally``.
    """
    r = FakeRedis()
    finished = []

    async def enrich(prop):
        await asyncio.sleep(0)
        finished.append(prop.id)

    class ExplodingControl(_ScriptedControl):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def should_stop(self):
            self.calls += 1
            if self.calls > 1:  # blows up while row 0 is still in flight
                raise ConnectionError("redis went away")
            return False

    async def _go():
        with pytest.raises(ConnectionError):
            await run_backfill(
                _rows(3),
                enrich_fn=enrich,
                budget=_budget(r, 100),
                checkpoint=_checkpoint(r),
                requests_per_property=3,
                concurrency=2,
                sleep_fn=_noop_sleep,
                control=ExplodingControl(),
            )

    asyncio.run(asyncio.wait_for(_go(), timeout=5))

    # Row 0 was launched before the failure and must have been awaited, not
    # cancelled on the way out.
    assert finished == ["prop-0"]


def test_a_worker_exception_does_not_abandon_its_siblings():
    """``checkpoint.advance`` runs outside the worker's ``except``.

    A Redis error there escapes ``_worker``; a bare ``gather`` would abort on it
    and leave the remaining rows pending.
    """
    r = FakeRedis()
    done = []

    class OneShotCheckpoint(Checkpoint):
        def advance(self, property_id):
            if property_id == "prop-0":
                raise ConnectionError("checkpoint write failed")
            done.append(property_id)

    async def enrich(prop):
        await asyncio.sleep(0)

    result = asyncio.run(
        asyncio.wait_for(
            run_backfill(
                _rows(3),
                enrich_fn=enrich,
                budget=_budget(r, 100),
                checkpoint=OneShotCheckpoint(r, prefix="t"),
                requests_per_property=3,
                concurrency=3,
                sleep_fn=_noop_sleep,
            ),
            timeout=5,
        )
    )

    assert done == ["prop-1", "prop-2"]  # siblings still completed
    assert result.processed == 3


def test_a_slow_row_does_not_let_the_state_key_decay_to_idle():
    """One row longer than the state TTL made a live run read back ``idle``.

    The launch loop refreshes state once per launch, so with ``concurrency=1``
    the refresh cadence is the *row* duration. The worker's tick now refreshes
    it too.
    """
    r = FakeRedis()
    control = _ScriptedControl()
    # Clock jumps 10 minutes per read: every row outlives the 120s state TTL.
    ticks = iter([600.0 * i for i in range(200)])

    async def enrich(prop):
        return None

    asyncio.run(
        run_backfill(
            _rows(3),
            enrich_fn=enrich,
            budget=_budget(r, 100),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            concurrency=1,
            sleep_fn=_noop_sleep,
            control=control,
            clock=lambda: next(ticks),
        )
    )

    # One publish per row at least, not a single start-up publish.
    assert len([s for s in control.states if s is BackfillState.RUNNING]) >= 3


def test_the_worker_tick_never_stamps_running_over_a_pause():
    """The refresh re-publishes the *current* state, not a hardcoded ``running``.

    Driving the state refresh from a worker's ``finally`` is what keeps a slow
    row from letting the key decay — but a row that finishes while the operator
    has the run paused must not stamp ``running`` over the ``paused`` the launch
    loop published.
    """
    r = FakeRedis()
    gate = asyncio.Event()
    ticks = iter([600.0 * i for i in range(200)])

    class _PauseAfterFirstLaunch(_ScriptedControl):
        def __init__(self):
            super().__init__()
            self.checks = 0
            self.stop = False

        def is_paused(self):
            self.checks += 1
            return self.checks > 1  # row 0 launches, then the operator pauses

        def should_stop(self):
            return self.stop

    control = _PauseAfterFirstLaunch()
    polls = {"n": 0}

    async def sleeper(_):
        polls["n"] += 1
        if polls["n"] == 1:
            gate.set()  # the in-flight row completes *during* the pause
        elif polls["n"] >= 3:
            control.stop = True
        await asyncio.sleep(0)

    async def enrich(prop):
        await gate.wait()

    asyncio.run(
        asyncio.wait_for(
            run_backfill(
                _rows(3),
                enrich_fn=enrich,
                budget=_budget(r, 100),
                checkpoint=_checkpoint(r),
                requests_per_property=3,
                concurrency=2,
                sleep_fn=sleeper,
                control=control,
                clock=lambda: next(ticks),
            ),
            timeout=5,
        )
    )

    first_pause = control.states.index(BackfillState.PAUSED)
    after = control.states[first_pause:]
    assert BackfillState.RUNNING not in after  # only paused, then idle on exit


def test_state_refresh_follows_a_custom_control_ttl():
    """Story 1.5 constructs its own control; a shorter TTL must refresh faster."""
    control = BackfillControl(FakeRedis(), prefix="t", state_ttl_seconds=20)

    assert control.state_ttl_seconds == 20
    assert control.refresh_interval_seconds < 20


def test_a_non_positive_pause_poll_cannot_busy_spin():
    """``AppConfig`` guards the CLI's value; core guards its own loop."""
    r = FakeRedis()
    control = BackfillControl(r, prefix="t")
    control.request_pause()
    waits = []

    async def sleeper(seconds):
        waits.append(seconds)
        if len(waits) >= 2:
            control.request_stop()

    async def enrich(prop):
        return None

    asyncio.run(
        asyncio.wait_for(
            run_backfill(
                _rows(1),
                enrich_fn=enrich,
                budget=_budget(r, 100),
                checkpoint=_checkpoint(r),
                requests_per_property=3,
                sleep_fn=sleeper,
                control=control,
                pause_poll_seconds=0.0,
            ),
            timeout=5,
        )
    )

    assert waits and all(w > 0 for w in waits)


def test_non_atomic_renew_reports_an_already_expired_lease():
    """``EXPIRE`` returns 0 when the key is gone — that is not a renewal.

    The fallback path returned an unconditional ``True``, so a runner whose
    lease had already lapsed kept writing while a successor held it.
    """
    r = FakeRedis()
    lease = BackfillLease(r, prefix="t", ttl_seconds=60)
    assert lease.acquire() is True
    assert lease.renew() is True

    r.kv.pop("t:lease")  # TTL fired between the GET and the EXPIRE

    assert lease.renew() is False


def test_acquire_keeps_the_lease_usable_when_the_meta_write_fails():
    """The meta hash is decoration; a blip there must not orphan the lease.

    ``SET NX`` had already taken the lease, so an exception out of ``acquire()``
    (before the caller's ``try/finally`` exists) locked the next run out for the
    whole TTL over a failed cosmetic write.
    """

    class NoHashRedis(FakeRedis):
        def hset(self, *a, **kw):
            raise ConnectionError("redis went away")

    r = NoHashRedis()
    lease = BackfillLease(r, prefix="t", ttl_seconds=60)

    assert lease.acquire() is True
    assert lease.is_held_by_self() is True
    assert lease.release() is True


def test_the_non_atomic_fallback_announces_itself(caplog):
    """A silently downgraded RPD ceiling is worse than a loud one."""
    import logging

    r = FakeRedis()  # no ``eval``
    budget = _budget(r, 100)

    with caplog.at_level(logging.WARNING):
        budget.try_consume(3)
        budget.try_consume(3)

    warned = [rec for rec in caplog.records
              if "backfill_non_atomic_redis_fallback" in rec.getMessage()]
    assert len(warned) == 1  # once per object, not once per reservation
