"""The backfill's Lua scripts, executed by a real Redis (v0.13-s1.3 follow-up).

The unit-level fakes dispatch on script *identity* (``script is _BUDGET_RESERVE_LUA``)
and then re-implement the logic in Python. That exercises the calling
convention — argument order, reply decoding, which key ends up in which state —
but it never runs a single line of the shipped Lua. A typo in a script body (a
wrong ``ARGV`` index, a ``hincrby`` on the wrong field, a syntax error) therefore
passed the entire unit suite and would first surface against a real Redis, where
every reservation or renew raises ``ResponseError`` and a multi-day run dies on
row one.

These scripts *are* the mutual exclusion and the never-exceed-budget guarantee
(AC-1), so they get executed for real here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.backfill_runner import BackfillLease, DailyBudget
from tests.env_helpers import get_redis_url
from tests.redis_isolation import assert_wipe_safe_redis_url

pytestmark = pytest.mark.integration

_PREFIX = "test:backfill-lua"


@pytest.fixture
def redis_client():
    redis_url = get_redis_url()
    if not redis_url:
        pytest.skip("REDIS_URL not set — run via scripts/agent/validate.sh backend")
    assert_wipe_safe_redis_url(redis_url)
    import redis as redis_lib

    client = redis_lib.Redis.from_url(redis_url)
    for key in client.scan_iter(f"{_PREFIX}*"):
        client.delete(key)
    yield client
    for key in client.scan_iter(f"{_PREFIX}*"):
        client.delete(key)
    client.close()


def _budget(client, limit, *, now):
    return DailyBudget(
        client, prefix=_PREFIX, daily_limit=limit, now_fn=lambda: now
    )


def test_budget_reserve_lua_runs_and_enforces_the_cap(redis_client):
    now = datetime.now(timezone.utc)
    budget = _budget(redis_client, 10, now=now)

    assert budget.try_consume(6) is True
    assert budget.consumed() == 6
    # Overshoot must roll the increment back, not leave the counter past the cap.
    assert budget.try_consume(6) is False
    assert budget.consumed() == 6
    assert budget.try_consume(4) is True
    assert budget.consumed() == 10


def test_budget_reserve_lua_rolls_a_stale_window(redis_client):
    opened = datetime.now(timezone.utc) - timedelta(hours=25)
    assert _budget(redis_client, 10, now=opened).try_consume(10) is True

    later = datetime.now(timezone.utc)
    rolled = _budget(redis_client, 10, now=later)
    assert rolled.try_consume(4) is True
    assert rolled.consumed() == 4  # fresh window, not 14


def test_budget_reserve_lua_leaves_no_phantom_window_on_refusal(redis_client):
    """A refusal that opened the window must delete it, not park a 24h wait."""
    now = datetime.now(timezone.utc)
    budget = _budget(redis_client, 5, now=now)

    assert budget.try_consume(9) is False
    assert redis_client.exists(f"{_PREFIX}:budget") == 0


def test_lease_lua_renews_and_releases_only_for_the_owner(redis_client):
    owner = BackfillLease(redis_client, prefix=_PREFIX, ttl_seconds=300)
    intruder = BackfillLease(redis_client, prefix=_PREFIX, ttl_seconds=300)

    assert owner.acquire() is True
    assert intruder.acquire() is False  # SET NX EX is what makes this exclusive

    # The CAS scripts key on the owner token, not on mere presence.
    assert intruder.renew() is False
    assert intruder.release() is False
    assert owner.is_held_by_self() is True

    assert owner.renew() is True
    assert redis_client.ttl(owner.key) > 0

    assert owner.release() is True
    assert redis_client.exists(owner.key) == 0
    # Releasing a lease that is already gone is a no-op, never an error.
    assert owner.release() is False


def test_lease_renew_refusal_decodes_as_false_against_real_redis(redis_client):
    """Guards the reply-decoding trap: ``bool(b"0")`` is ``True``."""
    lease = BackfillLease(redis_client, prefix=_PREFIX, ttl_seconds=300)

    assert lease.renew() is False  # never acquired — must not read as owned


def test_settle_lua_never_opens_a_window(redis_client):
    """A reconciliation must not restart the 24h clock.

    ``settle`` is the one budget write allowed to push the counter past the cap,
    so letting it also *create* a window would give a run a fresh day whose
    count starts at whatever its last rows overspent.
    """
    now = datetime.now(timezone.utc)

    assert _budget(redis_client, 10, now=now).settle(4) is False
    assert redis_client.exists(f"{_PREFIX}:budget") == 0


def test_settle_lua_never_rolls_an_expired_window(redis_client):
    opened = datetime.now(timezone.utc) - timedelta(hours=25)
    assert _budget(redis_client, 100, now=opened).try_consume(10) is True

    later = datetime.now(timezone.utc)
    assert _budget(redis_client, 100, now=later).settle(5) is False
    # The stale window is left exactly as it was — no roll, no new start stamp.
    assert int(redis_client.hget(f"{_PREFIX}:budget", "count")) == 10


def test_settle_lua_adjusts_the_live_window_and_floors_at_zero(redis_client):
    now = datetime.now(timezone.utc)
    budget = _budget(redis_client, 100, now=now)
    assert budget.try_consume(9) is True

    assert budget.settle(12) is True
    assert budget.consumed() == 21
    assert budget.settle(-99) is True
    assert budget.consumed() == 0  # a refund never drives the counter negative


def test_a_recorded_overshoot_blocks_the_next_reservation(redis_client):
    """The point of the whole story: an overshoot must bind, not be hidden."""
    now = datetime.now(timezone.utc)
    budget = _budget(redis_client, 10, now=now)
    assert budget.try_consume(3) is True

    assert budget.settle(18) is True  # the row really sent 21, not 3
    assert budget.consumed() == 21
    assert budget.remaining() == 0
    assert budget.try_consume(3) is False


def test_concurrent_settles_lose_no_update(redis_client):
    """Reconciliation is a read-modify-write per row; only the Lua makes it safe."""
    import threading

    now = datetime.now(timezone.utc)
    budget = _budget(redis_client, 10_000, now=now)
    assert budget.try_consume(1) is True  # open the window the settles land in

    def _worker():
        settler = _budget(redis_client, 10_000, now=now)
        for _ in range(25):
            assert settler.settle(2) is True

    threads = [threading.Thread(target=_worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert budget.consumed() == 1 + 4 * 25 * 2


def test_concurrent_reservations_never_overshoot_the_cap(redis_client):
    """AC-1's never-exceed guarantee, asserted under real contention.

    The unit tests reserve single-threaded, so the lost-update window the Lua
    exists to close was never actually raced. Two clients hammering the same
    counter must sum to *at most* the cap, and every ``True`` must be backed by
    a real increment.
    """
    import threading

    now = datetime.now(timezone.utc)
    limit = 50
    granted: list[bool] = []
    lock = threading.Lock()

    def _worker():
        budget = _budget(redis_client, limit, now=now)
        for _ in range(20):
            ok = budget.try_consume(3)
            with lock:
                granted.append(ok)

    threads = [threading.Thread(target=_worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    accepted = sum(1 for ok in granted if ok)
    assert accepted * 3 <= limit
    # The counter agrees with what was handed out — no reservation was wiped by
    # an interleaved window roll.
    assert _budget(redis_client, limit, now=now).consumed() == accepted * 3


def test_never_exceed_holds_against_the_reconciled_quantity(redis_client):
    """The same guarantee, re-derived once settles race the reservations.

    Every granted row reserves its 3-request forecast and then settles the 2
    extra requests it really sent, so the counter is racing two different write
    shapes at once. What must survive: no update is lost (the recorded count is
    exactly what was really spent), no reservation is granted once the *recorded*
    count can no longer fund one, and the counter only ever passes the cap
    through a settle — never through a reservation.
    """
    import threading

    now = datetime.now(timezone.utc)
    limit = 60
    granted: list[bool] = []
    lock = threading.Lock()

    def _worker():
        budget = _budget(redis_client, limit, now=now)
        for _ in range(20):
            ok = budget.try_consume(3)
            if ok:
                assert budget.settle(2) is True  # the row really sent 5
            with lock:
                granted.append(ok)

    threads = [threading.Thread(target=_worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    accepted = sum(1 for ok in granted if ok)
    final = _budget(redis_client, limit, now=now).consumed()
    assert final == accepted * 5  # reserves and settles all landed, none lost
    # The loop really was stopped by the cap rather than by running out of
    # attempts …
    assert accepted < len(granted)
    # … and no reservation was granted once the *recorded* count could no longer
    # fund one: the settles pushed the counter to a point where another 3-request
    # forecast would not fit, and from there every remaining try_consume refused.
    assert final + 3 > limit
    assert _budget(redis_client, limit, now=now).remaining() == 0
