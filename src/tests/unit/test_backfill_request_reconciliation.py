"""The daily budget counts provider requests, not properties (v0.13-s3.3, DW-18).

The launch loop reserves a flat ``requests_per_property`` (3) per row, but one
property is 3 stages × up to 3 JSON attempts × up to 5 HTTP attempts — between 2
and ~45 real requests, and ``429`` is a retried status, so the undercount is
worst exactly when the account is already throttled. These tests cover the two
halves of the fix: :meth:`DailyBudget.settle` (a second atomic step that adjusts
the live window without ever opening or rolling one) and ``run_backfill``'s
after-every-row reconciliation of the aggregate against the client's monotonic
request counter.

The Redis doubles come from :mod:`tests.unit.test_backfill_control` rather than
being re-declared: the ``EvalRedis`` fake is a one-for-one mirror of the shipped
Lua, and two divergent copies of it would be exactly the kind of drift that lets
a script change pass a green suite.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from core.backfill_runner import (
    _BUDGET_SETTLE_LUA,
    Checkpoint,
    DailyBudget,
    run_backfill,
)
from tests.unit.test_backfill_control import EvalRedis, FakeRedis

pytestmark = pytest.mark.unit

_NOW = datetime.fromisoformat("2026-08-12T12:00:00+00:00")

# Every budget case runs against both clients: ``EvalRedis`` takes the atomic
# ``_BUDGET_SETTLE_LUA`` path a real Redis takes, ``FakeRedis`` the documented
# multi-op fallback for clients without ``eval``. They must behave identically.
_BUDGET_CLIENTS = [FakeRedis, EvalRedis]


def _budget(redis, limit, *, now=_NOW):
    return DailyBudget(redis, prefix="t", daily_limit=limit, now_fn=lambda: now)


def _checkpoint(redis):
    return Checkpoint(redis, prefix="t", now_fn=lambda: _NOW)


def _rows(n):
    return [
        (SimpleNamespace(id=f"prop-{i}"), SimpleNamespace(ai_score=None))
        for i in range(n)
    ]


async def _noop_sleep(_):
    return None


class _Counter:
    """Stand-in for ``GeminiClient.request_count``: monotonic, shared, injected.

    The real counter is bumped once per HTTP attempt at the top of the client's
    retry loop, so retries are already inside it — which is why the runner is
    handed the count itself and not a per-row delta.
    """

    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> int:
        return self.value


def _count(redis):
    """The live window's recorded request count (0 when no window exists)."""
    return int(redis.hashes.get("t:budget", {}).get("count", 0) or 0)


def _open_window(redis, *, count, started=_NOW):
    redis.hashes["t:budget"] = {
        "count": str(count),
        "start": started.isoformat(),
        "start_epoch": str(started.timestamp()),
    }


def _run(rows, redis, *, limit=1000, spend=None, **kwargs):
    """Drive ``run_backfill`` with a counter the fake enrichment charges.

    ``spend`` maps a property id to the requests its enrichment "sends" (an
    ``Exception`` value raises instead, after charging that many).
    """
    counter = _Counter()
    spend = spend or {}
    snapshots: list[int] = []

    async def enrich_fn(prop):
        outcome = spend.get(prop.id, 3)
        # An exception stands for a row that failed *before* sending anything —
        # the case whose whole forecast has to come back off.
        if isinstance(outcome, BaseException):
            raise outcome
        counter.value += int(outcome)

    async def _go():
        return await run_backfill(
            rows,
            enrich_fn=kwargs.pop("enrich_fn", enrich_fn),
            budget=_budget(redis, limit),
            checkpoint=_checkpoint(redis),
            requests_per_property=3,
            sleep_fn=_noop_sleep,
            request_counter=kwargs.pop("request_counter", counter),
            on_progress=kwargs.pop(
                "on_progress", lambda _res: snapshots.append(_count(redis))
            ),
            **kwargs,
        )

    result = asyncio.run(_go())
    return result, counter, snapshots


# ---------------------------------------------------------------------------
# DailyBudget.settle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("client_cls", _BUDGET_CLIENTS)
def test_settle_adjusts_the_live_window_in_both_directions(client_cls):
    r = client_cls()
    b = _budget(r, 100)
    assert b.try_consume(9) is True

    assert b.settle(-4) is True
    assert b.consumed() == 5
    assert b.settle(12) is True
    assert b.consumed() == 17


@pytest.mark.parametrize("client_cls", _BUDGET_CLIENTS)
def test_settle_never_opens_a_window(client_cls):
    """Requests belonging to a window that has already reset land nowhere.

    Opening one here would restart the 24h clock from a *reconciliation* rather
    than from a reservation — handing the run a fresh window whose count starts
    at whatever the last rows happened to overspend.
    """
    r = client_cls()
    b = _budget(r, 100)

    assert b.settle(7) is False
    # Key *absent*, not merely empty: an empty hash would still be a window as
    # far as ``exists`` and any future reader are concerned, and asserting
    # ``== {}`` cannot tell the two apart.
    assert "t:budget" not in r.hashes
    assert b.consumed() == 0
    assert b.seconds_until_reset() == 0.0


@pytest.mark.parametrize("client_cls", _BUDGET_CLIENTS)
def test_settle_never_rolls_an_expired_window(client_cls):
    """An expired window is not this run's to charge — and not its to reset."""
    r = client_cls()
    opened = _NOW - timedelta(hours=25)
    _open_window(r, count=40, started=opened)
    b = _budget(r, 100)

    assert b.settle(5) is False
    # Untouched: same count, same (stale) start — no roll, no phantom window.
    assert r.hashes["t:budget"]["count"] == "40"
    assert r.hashes["t:budget"]["start"] == opened.isoformat()


@pytest.mark.parametrize("client_cls", _BUDGET_CLIENTS)
def test_settle_records_an_overshoot_instead_of_capping_it(client_cls):
    """The provider already counted those requests; hiding them re-creates DW-18.

    ``remaining()`` floors at 0 and the next reservation refuses — the two
    defences that already ship — so recording the truth grants nothing.
    """
    r = client_cls()
    b = _budget(r, 10)
    assert b.try_consume(9) is True

    assert b.settle(12) is True  # the row really sent 21, not 9
    assert b.consumed() == 21
    assert b.remaining() == 0
    assert b.try_consume(3) is False


@pytest.mark.parametrize("client_cls", _BUDGET_CLIENTS)
def test_settle_refund_floors_at_zero(client_cls):
    r = client_cls()
    b = _budget(r, 100)
    assert b.try_consume(3) is True

    assert b.settle(-9) is True
    assert b.consumed() == 0
    assert r.hashes["t:budget"]["count"] == "0"  # never negative


def test_settle_of_zero_costs_no_round_trip():
    r = EvalRedis()
    b = _budget(r, 100)
    b.try_consume(3)
    calls = r.eval_calls

    assert b.settle(0) is True
    assert r.eval_calls == calls  # a no-op costs no round trip
    assert b.consumed() == 3


def test_settle_uses_the_atomic_script_when_the_client_has_eval():
    r = EvalRedis()
    b = _budget(r, 100)
    b.try_consume(3)

    assert b.settle(4) is True
    assert r.eval_calls == 2  # reserve + settle, both through Lua


def test_settle_lands_on_a_legacy_hash_without_rolling_it():
    """A window opened by the pre-story runner keeps its count and its clock.

    ``count``'s *unit* did not change — the old writer simply wrote a wrong
    number — so carrying it forward is the conservative direction, and rolling
    it here would be how a run gets a second day's spend.
    """
    r = EvalRedis()
    started = _NOW - timedelta(hours=2)
    # Exactly what the pre-v0.13-s1.3 code wrote: count + ISO start, no epoch.
    r.hashes["t:budget"] = {"count": "300", "start": started.isoformat()}
    b = _budget(r, 14000)

    assert b.settle(18) is True
    assert b.consumed() == 318
    assert r.hashes["t:budget"]["start"] == started.isoformat()
    assert r.hashes["t:budget"]["start_epoch"] == str(started.timestamp())


# ---------------------------------------------------------------------------
# run_backfill reconciliation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("client_cls", _BUDGET_CLIENTS)
def test_a_row_that_sent_less_than_the_forecast_gets_the_difference_back(client_cls):
    r = client_cls()
    result, _, _ = _run(_rows(1), r, spend={"prop-0": 2})

    assert _count(r) == 2
    assert result.requests_consumed == 2
    assert result.requests_reserved == 3  # the forecast stays visible


@pytest.mark.parametrize("client_cls", _BUDGET_CLIENTS)
def test_a_row_that_matched_the_forecast_settles_nothing(client_cls):
    r = client_cls()
    result, _, _ = _run(_rows(1), r, spend={"prop-0": 3})

    assert _count(r) == 3
    assert result.requests_consumed == 3
    if isinstance(r, EvalRedis):
        assert r.eval_calls == 1  # delta 0 → the reserve only, no settle


@pytest.mark.parametrize("client_cls", _BUDGET_CLIENTS)
def test_a_heavy_retry_row_is_charged_what_it_really_sent(client_cls):
    """3 stages × 3 JSON attempts × up to 5 HTTP attempts is not 3 requests."""
    r = client_cls()
    result, _, _ = _run(_rows(1), r, spend={"prop-0": 21})

    assert _count(r) == 21
    assert result.requests_consumed == 21
    assert result.requests_reserved == 3


@pytest.mark.parametrize("client_cls", _BUDGET_CLIENTS)
def test_a_row_that_failed_before_sending_gives_the_forecast_back(client_cls):
    r = client_cls()
    result, _, _ = _run(_rows(1), r, spend={"prop-0": RuntimeError("no photos")})

    assert _count(r) == 0
    assert result.errors == 1  # still an error, exactly as before
    assert result.requests_consumed == 0


@pytest.mark.parametrize("client_cls", _BUDGET_CLIENTS)
def test_the_reconciled_count_is_what_exhausts_the_budget(client_cls):
    """AC-2: a retry storm spends the day early, and the loop notices.

    Under the flat charge the window read 3 while the provider had counted 12,
    so the run kept launching rows against an account it had already exhausted.
    """
    r = client_cls()
    result, _, _ = _run(_rows(4), r, limit=10, spend={"prop-0": 12})

    assert result.processed == 1
    assert result.budget_exhausted is True
    assert _count(r) == 12  # the overshoot is recorded, not hidden
    assert _budget(r, 10).remaining() == 0


def test_rows_still_in_flight_keep_a_forecast_reserved():
    """With ``concurrency > 1`` the charge must never dip below reality.

    One client is shared by every concurrent row and its counter is a single
    monotonic int, so ``after - before`` around one row is somebody else's
    retries as much as this row's. Reconciling the aggregate — while a flat
    forecast is still held for whatever is in flight — is attribution-free and
    exact once the last row drains.
    """
    r = EvalRedis()
    counter = _Counter()

    async def enrich_fn(prop):
        if prop.id == "prop-0":
            counter.value += 5
            return
        # Yield first so prop-0 finishes (and settles) while this row is still
        # in flight — the state the forecast exists to cover.
        for _ in range(3):
            await asyncio.sleep(0)
        counter.value += 4

    snapshots: list[int] = []

    async def _go():
        return await run_backfill(
            _rows(2),
            enrich_fn=enrich_fn,
            budget=_budget(r, 1000),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            concurrency=2,
            sleep_fn=_noop_sleep,
            request_counter=counter,
            on_progress=lambda _res: snapshots.append(_count(r)),
        )

    result = asyncio.run(_go())

    # First settle: 5 observed + one in-flight row's forecast of 3.
    assert snapshots[0] == 8
    # Last settle: nothing in flight, so the charge is exactly what was sent.
    assert snapshots[-1] == 9
    assert _count(r) == 9
    assert result.requests_consumed == 9
    assert result.requests_reserved == 6


@pytest.mark.parametrize("client_cls", _BUDGET_CLIENTS)
def test_a_window_that_rolls_mid_run_carries_its_pending_spend_forward(client_cls):
    """The settle writes nothing, and the spend it could not place is not lost."""
    r = client_cls()
    counter = _Counter()

    async def enrich_fn(prop):
        counter.value += 5
        if prop.id == "prop-0":
            r.hashes.pop("t:budget", None)  # the window resets under the run

    async def _go():
        return await run_backfill(
            _rows(2),
            enrich_fn=enrich_fn,
            budget=_budget(r, 1000),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            sleep_fn=_noop_sleep,
            request_counter=counter,
        )

    result = asyncio.run(_go())

    assert result.processed == 2
    # The refused settle carries its spend forward instead of discarding it:
    # prop-1's reservation opens the fresh window and the next settle charges
    # everything still pending — prop-0's 5 as well as prop-1's own 5.
    #
    # That deliberately over-charges the new window by up to one row's spend.
    # The symmetric mistake is to drop it (the fresh window would show 5, and 5
    # real requests would be charged nowhere), and *under*-charging is the only
    # direction that can push a real account past its RPD — which is the entire
    # subject of this story. Bounded either way: settles run every row, so at
    # most one row's worth plus the in-flight set is ever pending.
    assert _count(r) == 10
    # The run's own total is measured from an anchor that never moves.
    assert result.requests_consumed == 10


def test_a_settle_that_raises_never_aborts_the_row():
    class _BlipRedis(EvalRedis):
        def eval(self, script, numkeys, key, *args):
            if script is _BUDGET_SETTLE_LUA:
                raise RuntimeError("redis blip")
            return super().eval(script, numkeys, key, *args)

    r = _BlipRedis()
    result, _, snapshots = _run(_rows(2), r, spend={"prop-0": 9, "prop-1": 9})

    assert result.processed == 2  # both rows completed
    assert len(snapshots) == 2  # progress ticked for both
    assert _count(r) == 6  # only the flat reservations landed
    # The reported figure degrades to the truth, not to zero: it needs no Redis,
    # so a settle blip must not cost a pass that really sent 18 requests its
    # entire request count — that is DW-18's lie one layer up.
    assert result.requests_consumed == 18
    assert result.requests_reserved == 6


@pytest.mark.parametrize("client_cls", _BUDGET_CLIENTS)
def test_without_a_counter_the_flat_charge_is_unchanged(client_cls):
    """Local backends expose no request counter and must behave as before."""
    r = client_cls()
    result, counter, _ = _run(
        _rows(2), r, spend={"prop-0": 21, "prop-1": 21}, request_counter=None
    )

    assert counter.value == 42  # the requests really happened …
    assert _count(r) == 6  # … and the flat forecast is still all that is charged
    assert result.requests_consumed == 6
    assert result.requests_reserved == 6
    if isinstance(r, EvalRedis):
        assert r.eval_calls == 2  # two reserves, zero settles


def test_a_run_attaching_to_a_legacy_window_does_not_get_a_second_day():
    r = EvalRedis()
    started = _NOW - timedelta(hours=2)
    r.hashes["t:budget"] = {"count": "300", "start": started.isoformat()}

    result, _, _ = _run(_rows(1), r, limit=14000, spend={"prop-0": 21})

    assert _count(r) == 321  # settled on top of the legacy count, no roll
    assert r.hashes["t:budget"]["start"] == started.isoformat()
    assert result.requests_consumed == 21  # the *run's* spend, not the window's


def test_a_dry_run_projects_the_forecast_and_settles_nothing():
    r = EvalRedis()
    counter = _Counter()

    async def enrich_fn(prop):  # pragma: no cover - a dry run must not call it
        raise AssertionError("dry run must not enrich")

    async def _go():
        return await run_backfill(
            _rows(4),
            enrich_fn=enrich_fn,
            budget=_budget(r, 6),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            dry_run=True,
            request_counter=counter,
        )

    result = asyncio.run(_go())

    assert result.would_process == 2  # 6 / 3, on the flat forecast
    assert r.eval_calls == 0
    assert "t:budget" not in r.hashes
