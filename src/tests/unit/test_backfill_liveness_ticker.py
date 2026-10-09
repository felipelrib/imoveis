"""Unit tests for ``LivenessTicker`` and ``run_backfill(liveness=...)`` (v0.14-s1.12).

The ticker keeps three Redis keys alive for a whole backfill run: the lease, the
published control state and the ``<prefix>:active`` heartbeat. Its state machine
is driven here through ``tick()`` with a settable clock and a dict-backed Redis
that honours TTLs on that same clock and can be told to raise, so no test
depends on a thread except the one that checks ``start()`` / ``stop()``.
"""

from __future__ import annotations

import ast
import asyncio
import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import core.backfill_runner as runner
from core.backfill_runner import (
    BackfillControl,
    BackfillLease,
    BackfillState,
    Checkpoint,
    DailyBudget,
    Heartbeat,
    LivenessTicker,
    run_backfill,
)

pytestmark = pytest.mark.unit

_NOW = datetime.fromisoformat("2026-10-08T12:00:00+00:00")


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class _Redis:
    """Dict-backed Redis whose TTLs run on the injected clock.

    ``fail = True`` makes every command raise, which is what a Redis outage
    looks like to the runner. ``log`` records ``(time, command, key)`` for the
    writes, so a test can read how often a key was refreshed.
    """

    def __init__(self, clock) -> None:
        self.clock = clock
        self.kv: dict[str, str] = {}
        self.exp: dict[str, float] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.fail = False
        self.log: list[tuple[float, str, str]] = []

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("redis is down")

    def _expire_due(self, key) -> None:
        due = self.exp.get(key)
        if due is not None and self.clock() >= due:
            self.kv.pop(key, None)
            self.exp.pop(key, None)

    def get(self, key):
        self._check()
        self._expire_due(key)
        return self.kv.get(key)

    def set(self, key, val, ex=None, nx=False):
        self._check()
        self._expire_due(key)
        if nx and key in self.kv:
            return None
        self.kv[key] = str(val)
        if ex:
            self.exp[key] = self.clock() + ex
        else:
            self.exp.pop(key, None)
        self.log.append((self.clock(), "set", key))
        return True

    def expire(self, key, ttl):
        self._check()
        self._expire_due(key)
        if key in self.kv:
            self.exp[key] = self.clock() + ttl
            self.log.append((self.clock(), "expire", key))
            return 1
        return 1 if key in self.hashes else 0

    def delete(self, key):
        self._check()
        existed = key in self.kv or key in self.hashes
        self.kv.pop(key, None)
        self.exp.pop(key, None)
        self.hashes.pop(key, None)
        self.log.append((self.clock(), "delete", key))
        return 1 if existed else 0

    def hgetall(self, key):
        self._check()
        return dict(self.hashes.get(key, {}))

    def hget(self, key, field):
        self._check()
        return self.hashes.get(key, {}).get(field)

    def hset(self, key, field=None, value=None, mapping=None):
        self._check()
        h = self.hashes.setdefault(key, {})
        if mapping:
            h.update({k: str(v) for k, v in mapping.items()})
        if field is not None:
            h[field] = str(value)

    def hincrby(self, key, field, n=1):
        self._check()
        h = self.hashes.setdefault(key, {})
        h[field] = str(int(h.get(field, 0)) + int(n))
        return int(h[field])

    def hdel(self, key, *fields):
        self._check()
        for f in fields:
            self.hashes.setdefault(key, {}).pop(f, None)

    def writes(self, key) -> list[float]:
        """Times at which ``key`` was written or had its TTL extended."""
        return [t for t, cmd, k in self.log if k == key and cmd in ("set", "expire")]


def _max_gap(times: list[float], *, start: float, end: float) -> float:
    points = [start, *times, end]
    return max(b - a for a, b in zip(points, points[1:]))


def _kit(*, lease_ttl=900, state_ttl=120, beat_ttl=300, keepalives=()):
    """A ticker over an acquired lease, a control and a heartbeat on prefix ``t``."""
    clock = _Clock()
    redis = _Redis(clock)
    lease = BackfillLease(redis, prefix="t", ttl_seconds=lease_ttl, token="me")
    assert lease.acquire() is True
    control = BackfillControl(redis, prefix="t", state_ttl_seconds=state_ttl)
    heartbeat = Heartbeat(redis, prefix="t", ttl_seconds=beat_ttl)
    ticker = LivenessTicker(
        lease=lease,
        control=control,
        heartbeat=heartbeat,
        keepalives=keepalives,
        clock=clock,
    )
    return SimpleNamespace(
        clock=clock, redis=redis, lease=lease, control=control,
        heartbeat=heartbeat, ticker=ticker,
    )


def _run_for(kit, seconds: float, *, step: float = 5.0) -> None:
    """Advance the clock in ``step`` increments, ticking after each one."""
    elapsed = 0.0
    while elapsed < seconds:
        kit.clock.advance(step)
        elapsed += step
        kit.ticker.tick()


@pytest.fixture
def lost_log(monkeypatch):
    """Reasons passed to the lease-lost log line."""
    reasons: list[str] = []
    monkeypatch.setattr(runner, "_log_lease_lost", reasons.append)
    return reasons


# ---------------------------------------------------------------------------
# Heartbeat.ttl_seconds
# ---------------------------------------------------------------------------


def test_heartbeat_exposes_its_ttl():
    assert Heartbeat(_Redis(_Clock()), prefix="t", ttl_seconds=45).ttl_seconds == 45
    assert Heartbeat(_Redis(_Clock()), prefix="t").ttl_seconds == 300


# ---------------------------------------------------------------------------
# Cadence
# ---------------------------------------------------------------------------


def test_interval_is_the_smallest_due_period():
    kit = _kit(lease_ttl=900, state_ttl=120, beat_ttl=300)
    # lease 300s, state 30s, heartbeat 100s.
    assert kit.ticker.interval == 30.0
    assert kit.ticker.lease is kit.lease

    supervisor = Heartbeat(kit.redis, prefix="t:supervisor", ttl_seconds=30)
    assert LivenessTicker(keepalives=(supervisor,)).interval == 10.0


def test_every_cadence_is_read_from_the_primitive_it_keeps_alive():
    """Non-default TTLs: a ticker that fell back to the defaults would let all
    three keys lapse here (lease 60s, state 40s, heartbeat 90s)."""
    kit = _kit(lease_ttl=60, state_ttl=40, beat_ttl=90)
    # lease 20s, state 10s, heartbeat 30s.
    assert kit.ticker.interval == 10.0
    kit.ticker.set_state(BackfillState.RUNNING)
    kit.ticker.set_writing(True)

    for _ in range(600):
        kit.clock.advance(1.0)
        kit.ticker.tick()
        assert kit.redis.get("t:active") == "1"
        assert kit.control.state() is BackfillState.RUNNING
        assert kit.lease.is_held_by_self()

    end = kit.clock()
    assert _max_gap(kit.redis.writes("t:lease"), start=0.0, end=end) == 20.0
    assert _max_gap(kit.redis.writes("t:state"), start=0.0, end=end) == 10.0
    assert _max_gap(kit.redis.writes("t:active"), start=0.0, end=end) == 30.0
    assert kit.ticker.lease_lost is False


def test_the_outage_bound_is_the_lease_ttl_of_the_lease_it_was_given():
    kit = _kit(lease_ttl=60)
    kit.clock.advance(59.0)
    assert kit.ticker.lease_lost is False
    kit.clock.advance(1.0)
    assert kit.ticker.lease_lost is True


def test_a_ticker_with_nothing_to_keep_alive_is_valid():
    ticker = LivenessTicker()
    ticker.tick()
    ticker.set_state(BackfillState.RUNNING)
    ticker.set_writing(True)
    ticker.hold_heartbeat()
    ticker.release_heartbeat()
    ticker.set_writing(False)
    assert ticker.renew_now() is True
    assert ticker.lease_lost is False
    assert ticker.lease is None
    assert ticker.interval > 0


def test_slow_row_keeps_all_three_keys_alive_on_their_own_cadence():
    """One row in flight for longer than every TTL (DW-9, DW-20)."""
    kit = _kit()
    kit.ticker.set_state(BackfillState.RUNNING)
    kit.ticker.set_writing(True)

    for _ in range(400):  # 2000s: more than the 900s lease TTL
        kit.clock.advance(5.0)
        kit.ticker.tick()
        assert kit.redis.get("t:active") == "1"
        assert kit.control.state() is BackfillState.RUNNING
        assert kit.lease.is_held_by_self()

    assert kit.ticker.lease_lost is False
    end = kit.clock()
    # Each key is refreshed well inside its own TTL, and not on every tick.
    assert _max_gap(kit.redis.writes("t:active"), start=0.0, end=end) <= 105.0
    assert _max_gap(kit.redis.writes("t:state"), start=0.0, end=end) <= 35.0
    assert _max_gap(kit.redis.writes("t:lease"), start=0.0, end=end) <= 305.0
    assert len(kit.redis.writes("t:lease")) <= 8
    assert len(kit.redis.writes("t:active")) <= 22


def test_at_the_wake_up_interval_of_the_thread_every_key_is_refreshed_inside_its_ttl():
    """The thread wakes every ``interval`` (30 s), not every 5 s: a chore whose
    period is not a multiple of it runs at the next wake-up after it falls due
    (``:active``: due every 100 s, beaten every 120 s)."""
    kit = _kit()
    kit.ticker.set_state(BackfillState.RUNNING)
    kit.ticker.set_writing(True)
    assert kit.ticker.interval == 30.0

    for _ in range(100):  # 3000s of wake-ups at the real cadence
        kit.clock.advance(kit.ticker.interval)
        kit.ticker.tick()
        assert kit.redis.get("t:active") == "1"
        assert kit.control.state() is BackfillState.RUNNING
        assert kit.lease.is_held_by_self()

    end = kit.clock()
    assert _max_gap(kit.redis.writes("t:active"), start=0.0, end=end) == 120.0
    assert _max_gap(kit.redis.writes("t:state"), start=0.0, end=end) == 30.0
    assert _max_gap(kit.redis.writes("t:lease"), start=0.0, end=end) == 300.0
    assert kit.ticker.lease_lost is False


def test_outside_a_pass_the_lease_and_state_stay_alive_but_active_is_not_beaten():
    """Candidate fetch, census, the gap between passes (DW-21)."""
    kit = _kit()
    kit.ticker.set_state(BackfillState.RUNNING)

    _run_for(kit, 2000.0)

    assert kit.lease.is_held_by_self()
    assert kit.control.state() is BackfillState.RUNNING
    assert kit.redis.writes("t:active") == []
    assert kit.redis.get("t:active") is None
    assert kit.ticker.lease_lost is False


def test_the_ticker_republishes_whatever_state_the_run_last_set():
    kit = _kit()
    kit.ticker.set_state(BackfillState.BACKING_OFF)
    _run_for(kit, 300.0)
    assert kit.control.state() is BackfillState.BACKING_OFF

    kit.ticker.set_state(BackfillState.BLOCKED)
    assert kit.control.state() is BackfillState.BLOCKED
    _run_for(kit, 300.0)
    assert kit.control.state() is BackfillState.BLOCKED


def test_no_state_is_published_before_the_run_sets_one():
    kit = _kit()
    _run_for(kit, 300.0)
    assert kit.redis.writes("t:state") == []


# ---------------------------------------------------------------------------
# `:active` — only while rows may be written
# ---------------------------------------------------------------------------


def test_set_writing_beats_on_the_callers_thread_and_clears_on_the_way_out():
    kit = _kit()
    kit.ticker.set_writing(True)
    assert kit.redis.get("t:active") == "1"  # before any tick

    kit.ticker.set_writing(False)
    assert kit.redis.get("t:active") is None
    _run_for(kit, 600.0)
    assert kit.redis.get("t:active") is None  # the timer stopped beating too


def test_a_pause_with_nothing_in_flight_lets_active_lapse_and_resume_beats_at_once():
    kit = _kit()
    kit.ticker.set_state(BackfillState.PAUSED)
    kit.ticker.set_writing(True)
    kit.ticker.hold_heartbeat()
    beats_before = len(kit.redis.writes("t:active"))

    _run_for(kit, 1000.0)

    # The key lapsed on its own TTL: a paused runner reads as idle to the
    # migration guard, while the lease and the state are still the run's.
    assert len(kit.redis.writes("t:active")) == beats_before
    assert kit.redis.get("t:active") is None
    assert kit.lease.is_held_by_self()
    assert kit.control.state() is BackfillState.PAUSED

    kit.ticker.release_heartbeat()
    assert kit.redis.get("t:active") == "1"  # synchronously, before any tick
    _run_for(kit, 600.0)
    assert kit.redis.get("t:active") == "1"


def test_release_without_writing_does_not_beat():
    kit = _kit()
    kit.ticker.hold_heartbeat()
    kit.ticker.release_heartbeat()
    assert kit.redis.get("t:active") is None


def test_a_new_pass_is_not_held_by_the_previous_pause():
    kit = _kit()
    kit.ticker.set_writing(True)
    kit.ticker.hold_heartbeat()
    kit.ticker.set_writing(False)

    kit.ticker.set_writing(True)
    _run_for(kit, 1000.0)
    assert kit.redis.get("t:active") == "1"


# ---------------------------------------------------------------------------
# Redis failures
# ---------------------------------------------------------------------------


def test_a_redis_blip_shorter_than_the_lease_ttl_changes_nothing(lost_log):
    kit = _kit()
    kit.ticker.set_state(BackfillState.RUNNING)
    kit.ticker.set_writing(True)
    _run_for(kit, 290.0)

    attempts: list[float] = []
    real_renew = kit.lease.renew

    def _counting_renew():
        attempts.append(kit.clock())
        return real_renew()

    kit.lease.renew = _counting_renew
    kit.redis.fail = True
    _run_for(kit, 600.0)  # never raises out of tick()
    assert kit.ticker.lease_lost is False
    # After the first failed renew it retries on every tick, not every ttl/3.
    assert len(attempts) >= 100

    kit.redis.fail = False
    _run_for(kit, 10.0)
    assert kit.ticker.lease_lost is False
    assert kit.lease.is_held_by_self()
    assert kit.control.state() is BackfillState.RUNNING
    assert kit.redis.get("t:active") == "1"
    assert lost_log == []
    # Recovered: back on the ttl/3 cadence.
    attempts.clear()
    _run_for(kit, 290.0)
    assert len(attempts) <= 1


def test_an_outage_as_long_as_the_lease_ttl_latches_lease_lost_once(lost_log):
    kit = _kit()
    kit.ticker.set_state(BackfillState.RUNNING)
    _run_for(kit, 100.0)
    kit.redis.fail = True

    _run_for(kit, 1200.0)

    assert kit.ticker.lease_lost is True
    assert len(lost_log) == 1

    # Terminal: Redis coming back does not un-lose it, and nothing is renewed
    # or published for a key that may now describe a successor.
    kit.redis.fail = False
    kit.redis.kv.clear()
    kit.redis.log.clear()
    _run_for(kit, 600.0)
    assert kit.ticker.lease_lost is True
    assert kit.redis.log == []
    assert len(lost_log) == 1


def test_lease_lost_is_true_after_a_ttl_even_when_no_tick_ever_completes(lost_log):
    """A ticker thread stuck in a socket call must not hide a lapsed lease."""
    kit = _kit()
    kit.clock.advance(899.0)
    assert kit.ticker.lease_lost is False
    kit.clock.advance(1.0)
    assert kit.ticker.lease_lost is True
    assert kit.ticker.lease_lost is True
    assert len(lost_log) == 1
    assert kit.ticker.renew_now() is False


def test_the_outage_bound_runs_from_the_last_successful_renew():
    kit = _kit()
    _run_for(kit, 600.0)  # renewed at 300 and 600
    kit.redis.fail = True
    _run_for(kit, 895.0)
    assert kit.ticker.lease_lost is False
    _run_for(kit, 10.0)
    assert kit.ticker.lease_lost is True


class _SlowLease:
    """Lease double whose ``renew`` takes ``seconds`` of the injected clock."""

    ttl_seconds = 900

    def __init__(self, clock, seconds: float) -> None:
        self._clock = clock
        self.seconds = seconds

    def renew(self) -> bool:
        self._clock.advance(self.seconds)
        return True


def test_the_outage_bound_counts_from_before_the_renew_call_that_succeeded():
    """The TTL in Redis restarts no earlier than the moment the call was sent,
    so the bound must not count from the moment the reply came back."""
    clock = _Clock()
    ticker = LivenessTicker(lease=_SlowLease(clock, 100.0), clock=clock)
    clock.advance(50.0)

    assert ticker.renew_now() is True  # sent at 50, answered at 150

    clock.advance(799.0)  # 949: under 900s since the call was sent
    assert ticker.lease_lost is False
    clock.advance(1.0)  # 950 = 50 + 900 (counting from the reply would say 1050)
    assert ticker.lease_lost is True


def test_a_renew_that_takes_a_whole_ttl_to_answer_is_a_lost_lease(lost_log):
    clock = _Clock()
    ticker = LivenessTicker(lease=_SlowLease(clock, 900.0), clock=clock)

    assert ticker.renew_now() is False

    assert ticker.lease_lost is True
    assert len(lost_log) == 1


def test_a_refused_renew_latches_at_once_and_leaves_the_successors_keys_alone(lost_log):
    kit = _kit()
    kit.ticker.set_state(BackfillState.RUNNING)
    kit.ticker.set_writing(True)
    _run_for(kit, 100.0)

    # A successor took the lease; the next renew (at 300s) is refused.
    kit.redis.kv["t:lease"] = "successor"
    kit.redis.exp.pop("t:lease", None)
    _run_for(kit, 195.0)
    assert kit.ticker.lease_lost is False  # not found out yet
    _run_for(kit, 5.0)
    assert kit.ticker.lease_lost is True
    assert len(lost_log) == 1

    # From here on the shared keys describe the successor.
    kit.redis.kv["t:state"] = "paused"
    kit.redis.kv["t:active"] = "1"
    kit.redis.exp.pop("t:state", None)
    kit.redis.exp.pop("t:active", None)
    kit.redis.log.clear()

    kit.ticker.set_state(BackfillState.RUNNING)
    kit.ticker.set_writing(False)
    _run_for(kit, 600.0)
    assert kit.redis.kv["t:lease"] == "successor"
    assert kit.redis.kv["t:state"] == "paused"
    assert kit.redis.kv["t:active"] == "1"
    assert kit.redis.log == []
    assert len(lost_log) == 1


def test_active_keeps_being_beaten_after_a_lost_lease_while_the_pass_drains():
    """In-flight rows drain after a loss and are still writing."""
    kit = _kit()
    kit.ticker.set_writing(True)
    kit.redis.kv["t:lease"] = "successor"
    kit.redis.exp.pop("t:lease", None)
    assert kit.ticker.renew_now() is False

    for _ in range(200):  # 1000s of draining: longer than the 300s TTL
        kit.clock.advance(5.0)
        kit.ticker.tick()
        assert kit.redis.get("t:active") == "1"

    # The pass ends: the beating stops, and the key is not cleared, because a
    # successor may be beating it too.
    kit.ticker.set_writing(False)
    assert kit.redis.get("t:active") == "1"
    beats = len(kit.redis.writes("t:active"))
    _run_for(kit, 600.0)
    assert len(kit.redis.writes("t:active")) == beats
    assert kit.redis.kv["t:lease"] == "successor"


def test_no_beating_starts_once_the_lease_is_lost():
    kit = _kit()
    kit.redis.kv["t:lease"] = "successor"
    kit.redis.exp.pop("t:lease", None)
    assert kit.ticker.renew_now() is False

    kit.ticker.set_writing(True)  # a pass that begins on a lost lease
    _run_for(kit, 600.0)
    assert kit.redis.writes("t:active") == []


def test_a_pause_hold_is_not_released_once_the_lease_is_lost():
    kit = _kit()
    kit.ticker.set_writing(True)
    kit.ticker.hold_heartbeat()
    kit.redis.kv["t:lease"] = "successor"
    kit.redis.exp.pop("t:lease", None)
    assert kit.ticker.renew_now() is False
    beats = len(kit.redis.writes("t:active"))

    kit.ticker.release_heartbeat()
    _run_for(kit, 600.0)

    assert len(kit.redis.writes("t:active")) == beats


def test_renew_now_is_a_synchronous_cas_that_shares_the_bookkeeping(lost_log):
    kit = _kit()
    kit.clock.advance(250.0)
    assert kit.ticker.renew_now() is True
    assert kit.redis.writes("t:lease")[-1] == 250.0

    # The timer counts from that renew, so it does not renew again at 300.
    kit.redis.log.clear()
    _run_for(kit, 100.0)
    assert kit.redis.writes("t:lease") == []

    kit.redis.fail = True
    with pytest.raises(ConnectionError):
        kit.ticker.renew_now()
    assert kit.ticker.lease_lost is False
    kit.redis.fail = False

    kit.redis.kv["t:lease"] = "successor"
    assert kit.ticker.renew_now() is False
    assert kit.ticker.lease_lost is True
    kit.redis.fail = True  # once lost, no further Redis call is made
    assert kit.ticker.renew_now() is False
    assert len(lost_log) == 1


def test_note_lease_lost_latches_without_a_second_log_line(lost_log):
    kit = _kit()
    kit.ticker.note_lease_lost("checkpoint advance refused")
    kit.ticker.note_lease_lost("again")
    assert kit.ticker.lease_lost is True
    assert lost_log == ["checkpoint advance refused"]


def test_the_synchronous_transitions_raise_and_the_way_out_never_does():
    kit = _kit()
    kit.redis.fail = True
    with pytest.raises(ConnectionError):
        kit.ticker.set_state(BackfillState.RUNNING)
    with pytest.raises(ConnectionError):
        kit.ticker.set_writing(True)
    kit.ticker.set_writing(False)  # never raises
    kit.ticker.hold_heartbeat()
    kit.ticker.tick()  # never raises


def test_a_failing_chore_does_not_starve_the_others():
    kit = _kit()
    kit.ticker.set_state(BackfillState.RUNNING)
    kit.ticker.set_writing(True)

    def _boom(_state):
        raise ConnectionError("state key only")

    kit.control.publish_state = _boom
    _run_for(kit, 1000.0)

    assert kit.lease.is_held_by_self()
    assert kit.redis.get("t:active") == "1"
    assert kit.ticker.lease_lost is False


# ---------------------------------------------------------------------------
# A tick stuck in a socket
# ---------------------------------------------------------------------------


class _LockHolder:
    """Holds the ticker's I/O lock on another thread, as a stuck tick would."""

    def __init__(self, ticker) -> None:
        self._ticker = ticker
        self._holding = threading.Event()
        self._let_go = threading.Event()
        self._thread = threading.Thread(target=self._hold, daemon=True)

    def _hold(self) -> None:
        with self._ticker._io_lock:
            self._holding.set()
            self._let_go.wait(30.0)

    def __enter__(self):
        self._thread.start()
        assert self._holding.wait(5.0)
        return self

    def __exit__(self, *_exc_info) -> None:
        self._let_go.set()
        self._thread.join(5.0)


def test_a_stuck_tick_cannot_block_the_callers_transitions(monkeypatch):
    """The launch loop must reach its next ``lease_lost`` read (DW-10)."""
    import time

    monkeypatch.setattr(runner, "_LIVENESS_LOCK_WAIT_SECONDS", 0.2)
    kit = _kit()

    with _LockHolder(kit.ticker):
        started = time.monotonic()
        kit.ticker.set_state(BackfillState.BACKING_OFF)
        kit.ticker.set_writing(True)
        kit.ticker.hold_heartbeat()
        kit.ticker.release_heartbeat()
        kit.ticker.set_writing(False)
        waited = time.monotonic() - started

        # Four bounded waits (0.2s each), then on without the lock.
        assert waited < 5.0
        assert kit.control.state() is BackfillState.BACKING_OFF
        assert len(kit.redis.writes("t:active")) == 2  # set_writing + release
        assert kit.redis.get("t:active") is None  # cleared on the way out
        assert kit.ticker.lease_lost is False


def test_a_tick_skips_the_state_and_active_chores_while_a_caller_holds_the_lock():
    import time

    kit = _kit()
    kit.ticker.set_state(BackfillState.RUNNING)
    kit.ticker.set_writing(True)
    kit.redis.log.clear()
    kit.clock.advance(400.0)  # lease, state and heartbeat are all due

    with _LockHolder(kit.ticker):
        started = time.monotonic()
        kit.ticker.tick()
        assert time.monotonic() - started < 2.0  # did not wait for the lock
        assert kit.redis.writes("t:state") == []
        assert kit.redis.writes("t:active") == []
        assert kit.redis.writes("t:lease") == [400.0]  # not under that lock

    kit.ticker.tick()  # the lock is free again: the skipped chores run
    assert kit.redis.writes("t:state") == [400.0]
    assert kit.redis.writes("t:active") == [400.0]


# ---------------------------------------------------------------------------
# Keepalives (the supervisor's heartbeat)
# ---------------------------------------------------------------------------


def test_keepalives_are_beaten_whatever_the_lease_or_writing_state():
    clock = _Clock()
    redis = _Redis(clock)
    supervisor = Heartbeat(redis, prefix="t:supervisor", ttl_seconds=30)
    ticker = LivenessTicker(keepalives=(supervisor,), clock=clock)

    for _ in range(100):
        clock.advance(5.0)
        ticker.tick()
        assert redis.get("t:supervisor:active") == "1"
    assert redis.get("t:active") is None


def test_keepalives_outlive_a_lost_lease():
    supervisor_kit = _kit()
    supervisor = Heartbeat(supervisor_kit.redis, prefix="t:supervisor", ttl_seconds=30)
    ticker = LivenessTicker(
        lease=supervisor_kit.lease, keepalives=(supervisor,), clock=supervisor_kit.clock
    )
    supervisor_kit.redis.kv["t:lease"] = "successor"
    assert ticker.renew_now() is False

    supervisor_kit.clock.advance(60.0)
    ticker.tick()
    assert supervisor_kit.redis.get("t:supervisor:active") == "1"


# ---------------------------------------------------------------------------
# The thread
# ---------------------------------------------------------------------------


class _EventHeartbeat:
    """Heartbeat double whose beats a test can wait for."""

    ttl_seconds = 0.15  # → one beat every 0.05s

    def __init__(self) -> None:
        self.beats = 0
        self.beaten = threading.Event()

    def beat(self) -> None:
        self.beats += 1
        self.beaten.set()

    def clear(self) -> None:
        pass


def test_start_ticks_on_a_daemon_thread_and_stop_ends_it():
    keepalive = _EventHeartbeat()
    ticker = LivenessTicker(keepalives=(keepalive,))

    assert ticker.start() is ticker
    try:
        assert keepalive.beaten.wait(5.0), "the thread never ticked"
        threads = [t for t in threading.enumerate() if t.name == "backfill-liveness"]
        assert threads and all(t.daemon for t in threads)
        ticker.start()  # idempotent: still one thread
        assert len(
            [t for t in threading.enumerate() if t.name == "backfill-liveness"]
        ) == len(threads)
    finally:
        ticker.stop()

    assert not [t for t in threading.enumerate() if t.name == "backfill-liveness"]
    after = keepalive.beats
    ticker.tick()  # a stopped ticker does nothing more
    assert keepalive.beats == after
    ticker.stop()  # twice is fine


def test_a_renew_that_answers_after_stop_does_not_report_a_lost_lease(lost_log):
    """The renew was inside the socket when ``stop()`` gave up waiting; the
    owner then released the lease, so the CAS comes back refused."""
    kit = _kit()
    real_renew = kit.lease.renew

    def _renew_that_outlives_stop():
        kit.ticker.stop()
        kit.lease.release()
        return real_renew()

    kit.lease.renew = _renew_that_outlives_stop
    kit.clock.advance(400.0)

    kit.ticker._tick_lease(kit.clock())

    assert lost_log == []
    assert kit.ticker.lease_lost is False


def test_a_chore_that_recovers_says_so_once(monkeypatch):
    kit = _kit()
    failed: list[str] = []
    recovered: list[str] = []
    monkeypatch.setattr(runner, "_log_liveness_failed", lambda chore, exc: failed.append(chore))
    monkeypatch.setattr(runner, "_log_liveness_recovered", recovered.append)
    kit.ticker.set_state(BackfillState.RUNNING)

    kit.redis.fail = True
    _run_for(kit, 120.0, step=30.0)
    assert failed == ["state"]  # once per streak
    assert recovered == []

    kit.redis.fail = False
    _run_for(kit, 120.0, step=30.0)
    assert recovered == ["state"]


def test_a_tick_that_outlives_stop_makes_no_redis_call():
    """After ``stop()`` the owner releases the lease and clears its keys."""
    kit = _kit()
    supervisor = Heartbeat(kit.redis, prefix="t:supervisor", ttl_seconds=30)
    ticker = LivenessTicker(lease=kit.lease, keepalives=(supervisor,), clock=kit.clock)
    kit.clock.advance(400.0)
    kit.redis.log.clear()

    ticker.stop()
    # What a tick already past its first stop check would run next.
    ticker._tick_lease(kit.clock())
    ticker._tick_keepalive(ticker._keepalives[0], kit.clock())

    assert kit.redis.log == []
    assert ticker.lease_lost is False


def test_stop_says_so_when_the_thread_is_still_inside_a_tick(monkeypatch):
    logged = []
    monkeypatch.setattr(
        runner, "_log_liveness_failed", lambda chore, exc: logged.append((chore, str(exc)))
    )
    entered = threading.Event()
    let_go = threading.Event()

    class _StuckHeartbeat:
        ttl_seconds = 0.15

        def beat(self) -> None:
            entered.set()
            let_go.wait(30.0)

    ticker = LivenessTicker(keepalives=(_StuckHeartbeat(),)).start()
    try:
        assert entered.wait(5.0)
        ticker.stop(timeout=0.05)  # returns; never raises
        assert [chore for chore, _ in logged] == ["stop"]
    finally:
        let_go.set()
    ticker.stop()  # the thread has ended now: nothing more to report
    assert [chore for chore, _ in logged] == ["stop"]


def test_the_ticker_is_a_context_manager():
    keepalive = _EventHeartbeat()
    with LivenessTicker(keepalives=(keepalive,)) as ticker:
        assert isinstance(ticker, LivenessTicker)
        assert keepalive.beaten.wait(5.0)
    assert not [t for t in threading.enumerate() if t.name == "backfill-liveness"]


def test_stop_before_start_is_harmless():
    LivenessTicker().stop()


# ---------------------------------------------------------------------------
# run_backfill(liveness=...)
# ---------------------------------------------------------------------------


def _rows(n):
    return [
        (SimpleNamespace(id=f"prop-{i}"), SimpleNamespace(ai_score=None))
        for i in range(n)
    ]


async def _noop_sleep(_seconds):
    return None


def _backfill(kit, rows, enrich_fn, **kw):
    kw.setdefault("budget", DailyBudget(kit.redis, prefix="t", daily_limit=1000, now_fn=lambda: _NOW))
    kw.setdefault(
        "checkpoint",
        Checkpoint(kit.redis, prefix="t", now_fn=lambda: _NOW, lease=kit.lease),
    )
    kw.setdefault("sleep_fn", _noop_sleep)
    return asyncio.run(
        run_backfill(
            rows,
            enrich_fn=enrich_fn,
            requests_per_property=3,
            lease=kit.lease,
            liveness=kit.ticker,
            **kw,
        )
    )


def test_run_backfill_slow_row_reads_as_running_for_its_whole_length():
    kit = _kit()
    kit.ticker.set_writing(True)  # what the pass does before it reads the gate
    seen = []

    async def _slow(_prop):
        for _ in range(40):  # 2000s inside one row
            kit.clock.advance(50.0)
            kit.ticker.tick()  # what the thread does
            seen.append(
                (
                    kit.redis.get("t:active"),
                    kit.control.state(),
                    kit.lease.is_held_by_self(),
                )
            )

    result = _backfill(kit, _rows(1), _slow, control=kit.control)

    assert result.processed == 1
    assert result.lease_lost is False
    assert set(seen) == {("1", BackfillState.RUNNING, True)}


def test_run_backfill_stops_launching_after_an_outage_longer_than_the_lease_ttl(lost_log):
    kit = _kit()
    launched = []

    async def _row_during_an_outage(prop):
        launched.append(prop.id)
        kit.redis.fail = True
        for _ in range(19):  # 950s without one successful renew
            kit.clock.advance(50.0)
            kit.ticker.tick()

    result = _backfill(kit, _rows(3), _row_during_an_outage)

    assert launched == ["prop-0"]
    assert result.lease_lost is True
    assert result.processed == 1
    # The row finished after the loss: enriched, but not recorded on the
    # checkpoint that now belongs to whoever holds the lease.
    assert result.unrecorded_completions == 1
    assert len(lost_log) == 1


def test_run_backfill_reads_the_lease_flag_before_the_migration_key(lost_log):
    """Redis is still down after the loss: the loop head must not raise on the
    migration read before it gets to the flag."""
    kit = _kit()
    kit.clock.advance(900.0)  # a whole TTL without a renew: lost
    launched = []

    def _migrating():
        raise ConnectionError("redis is down")

    async def _row(prop):
        launched.append(prop.id)

    kit.redis.fail = True
    result = _backfill(kit, _rows(2), _row, is_migrating=_migrating)

    assert launched == []
    assert result.lease_lost is True
    assert result.migration_blocked is False


def test_run_backfill_reads_a_loss_the_ticker_found_while_the_loop_was_parked(lost_log):
    kit = _kit()
    launched = []

    async def _row(prop):
        launched.append(prop.id)
        kit.redis.kv["t:lease"] = "successor"
        kit.clock.advance(300.0)
        kit.ticker.tick()  # the timer's renew is refused mid-row

    result = _backfill(kit, _rows(3), _row, control=kit.control)

    assert launched == ["prop-0"]
    assert result.lease_lost is True
    assert kit.redis.kv["t:lease"] == "successor"
    assert len(lost_log) == 1


def test_run_backfill_takes_the_lease_from_the_ticker_when_none_is_passed():
    """One lease inside the pass: the finished-row renew goes through the
    ticker even when the caller passed only ``liveness=``."""
    kit = _kit()
    renews: list[float] = []
    real_renew = kit.lease.renew

    def _counting_renew():
        renews.append(kit.clock())
        return real_renew()

    kit.lease.renew = _counting_renew

    async def enrich(_prop):
        renews.clear()  # whatever the launch loop renewed before this row
        return True

    result = asyncio.run(
        run_backfill(
            _rows(1),
            enrich_fn=enrich,
            requests_per_property=3,
            budget=DailyBudget(kit.redis, prefix="t", daily_limit=1000, now_fn=lambda: _NOW),
            checkpoint=Checkpoint(kit.redis, prefix="t", now_fn=lambda: _NOW, lease=kit.lease),
            sleep_fn=_noop_sleep,
            liveness=kit.ticker,
        )
    )

    assert result.processed == 1
    assert len(renews) >= 1  # the finished row renewed


def test_run_backfill_creates_no_asyncio_renewer_when_a_ticker_is_supplied():
    def _renewers():
        return [
            t for t in asyncio.all_tasks()
            if "_renew_lease_periodically" in repr(t.get_coro())
        ]

    kit = _kit()
    with_ticker = []

    async def _probe(_prop):
        with_ticker.append(len(_renewers()))

    _backfill(kit, _rows(1), _probe)
    assert with_ticker == [0]

    # The lock on the unchanged path: without a ticker the timer task is there.
    without = _kit()
    without_ticker = []

    async def _probe_plain(_prop):
        without_ticker.append(len(_renewers()))

    asyncio.run(
        run_backfill(
            _rows(1),
            enrich_fn=_probe_plain,
            budget=DailyBudget(without.redis, prefix="t", daily_limit=1000, now_fn=lambda: _NOW),
            checkpoint=Checkpoint(
                without.redis, prefix="t", now_fn=lambda: _NOW, lease=without.lease
            ),
            requests_per_property=3,
            lease=without.lease,
        )
    )
    assert without_ticker == [1]


def test_run_backfill_leaves_the_state_running_at_exit_when_a_ticker_owns_it():
    kit = _kit()

    async def _ok(_prop):
        return None

    published = []
    publish = kit.control.publish_state

    def _recording_publish(state):
        published.append(state)
        publish(state)

    kit.control.publish_state = _recording_publish

    result = _backfill(kit, _rows(2), _ok, control=kit.control)

    assert result.processed == 2
    # No ``idle``: the ticker's owner ends the run, and the census that follows
    # a pass must not read as an idle runner.
    assert kit.control.state() is BackfillState.RUNNING
    assert published and BackfillState.IDLE not in published


def test_run_backfill_without_a_ticker_still_publishes_idle_at_exit():
    kit = _kit()

    async def _ok(_prop):
        return None

    asyncio.run(
        run_backfill(
            _rows(1),
            enrich_fn=_ok,
            budget=DailyBudget(kit.redis, prefix="t", daily_limit=1000, now_fn=lambda: _NOW),
            checkpoint=Checkpoint(kit.redis, prefix="t", now_fn=lambda: _NOW, lease=kit.lease),
            requests_per_property=3,
            lease=kit.lease,
            control=kit.control,
        )
    )
    assert kit.control.state() is BackfillState.IDLE


def test_run_backfill_still_publishes_backing_off_through_the_ticker():
    kit = _kit()

    class _Quota(RuntimeError):
        is_quota_exhausted = True

    async def _refused(_prop):
        raise _Quota("429")

    result = _backfill(kit, _rows(2), _refused, control=kit.control)

    assert result.quota_exhausted is True
    assert kit.control.state() is BackfillState.BACKING_OFF
    # ...and the ticker keeps that state alive, not ``running``.
    _run_for(kit, 300.0)
    assert kit.control.state() is BackfillState.BACKING_OFF


class _PausingControl:
    """Reports a pause for ``polls`` reads of ``is_paused``, then resumes."""

    def __init__(self, control, polls: int) -> None:
        self._control = control
        self._left = polls

    def is_paused(self) -> bool:
        if self._left > 0:
            self._left -= 1
            return True
        return False

    def should_stop(self) -> bool:
        return False

    def publish_state(self, state) -> None:
        self._control.publish_state(state)

    @property
    def refresh_interval_seconds(self) -> float:
        return self._control.refresh_interval_seconds


def test_run_backfill_pause_with_nothing_in_flight_holds_active_and_resume_beats_first():
    kit = _kit()
    kit.ticker.set_writing(True)
    events: list[str] = []
    paused_states = []

    async def _paused_sleep(_seconds):
        # Each pause poll is 100s of wall clock with the timer ticking.
        kit.clock.advance(100.0)
        kit.ticker.tick()
        events.append("poll")
        paused_states.append((kit.control.state(), kit.lease.is_held_by_self()))

    async def _enrich(_prop):
        # Read *at launch*: the resume beat happened before this row started.
        events.append(f"enrich active={kit.redis.get('t:active')}")

    beats_at_start = len(kit.redis.writes("t:active"))
    result = _backfill(
        kit,
        _rows(1),
        _enrich,
        control=_PausingControl(kit.control, polls=12),
        sleep_fn=_paused_sleep,
    )

    assert result.processed == 1
    polls = events.count("poll")
    assert polls >= 9  # > 900s paused: longer than every TTL
    # Nothing was in flight, so the pause never beat `:active`: after its 300s
    # TTL the key was gone and the runner read as idle to the migration guard.
    beats = kit.redis.writes("t:active")
    assert len(beats) == beats_at_start + 1
    assert beats[-1] == kit.clock()  # the one beat is the resume beat
    assert events[-1] == "enrich active=1"
    assert set(paused_states) == {(BackfillState.PAUSED, True)}
    assert kit.control.state() is BackfillState.RUNNING


def test_run_backfill_pause_keeps_beating_active_while_rows_are_in_flight():
    kit = _kit()
    kit.ticker.set_writing(True)
    release = None
    observed: list[tuple[str, str | None]] = []
    polls = {"n": 0}

    async def _enrich(prop):
        if prop.id == "prop-0":
            await release.wait()

    async def _paused_sleep(_seconds):
        polls["n"] += 1
        kit.clock.advance(100.0)
        kit.ticker.tick()
        if polls["n"] <= 6:
            # 600s into the pause, row 0 still in flight: `:active` is alive.
            observed.append(("in-flight", kit.redis.get("t:active")))
        if polls["n"] == 6:
            release.set()
            for _ in range(5):  # let row 0 finish and release its slot
                await asyncio.sleep(0)
        if polls["n"] > 6:
            observed.append(("drained", kit.redis.get("t:active")))

    class _PauseAfterFirstLaunch(_PausingControl):
        """Not paused for the first row, then paused for ``polls`` reads."""

        def __init__(self, control, polls):
            super().__init__(control, polls)
            self._first = True

        def is_paused(self):
            if self._first:
                self._first = False
                return False
            return super().is_paused()

    async def _main():
        nonlocal release
        release = asyncio.Event()
        return await run_backfill(
            _rows(2),
            enrich_fn=_enrich,
            budget=DailyBudget(kit.redis, prefix="t", daily_limit=1000, now_fn=lambda: _NOW),
            checkpoint=Checkpoint(kit.redis, prefix="t", now_fn=lambda: _NOW, lease=kit.lease),
            requests_per_property=3,
            concurrency=2,
            lease=kit.lease,
            liveness=kit.ticker,
            control=_PauseAfterFirstLaunch(kit.control, polls=14),
            sleep_fn=_paused_sleep,
        )

    result = asyncio.run(_main())

    assert result.processed == 2
    in_flight = [value for phase, value in observed if phase == "in-flight"]
    drained = [value for phase, value in observed if phase == "drained"]
    assert in_flight and set(in_flight) == {"1"}
    # Once the last row finished the hold applies and the key lapses.
    assert drained and drained[-1] is None


def test_run_backfill_tells_the_ticker_about_a_refused_checkpoint_write(lost_log):
    kit = _kit()

    class _RefusingCheckpoint:
        lease_gated = True

        def advance(self, _property_id):
            return False

    async def _ok(_prop):
        return None

    result = _backfill(kit, _rows(2), _ok, checkpoint=_RefusingCheckpoint(), control=kit.control)

    assert result.lease_lost is True
    assert kit.ticker.lease_lost is True
    assert len(lost_log) == 1


# ---------------------------------------------------------------------------
# Layering
# ---------------------------------------------------------------------------


def test_backfill_runner_imports_no_adapter_or_api_module():
    source = Path(runner.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    roots = {name.split(".")[0] for name in imported}
    assert not roots & {"adapters", "api"}, sorted(imported)
    # "src.adapters" / "src.api" spellings count too.
    assert not [name for name in imported if name.startswith(("src.adapters", "src.api"))]
