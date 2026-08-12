"""Checkpoint advance semantics under lease loss (v0.13-s3.4, DW-11).

``<prefix>:checkpoint`` is one hash **every** runner writes, and in-flight rows
always drain after a lease loss by design (cancelling mid-enrichment leaves
half-written properties). The unconditional ``hset`` + ``hincrby`` therefore let
a displaced runner stamp its own row id and run date over the successor's marker
and count rows the successor is enriching too — the same overwrite class
v0.13-fu7 closed for the *state* key, deliberately left open on the checkpoint
because that call also records genuinely completed work.

These tests cover both halves of the fix: :meth:`Checkpoint.advance` as an
owner-token compare-and-set (atomic ``eval`` branch and the documented
``eval``-less fallback, decoded replies included), and the real handover through
``run_backfill`` — the owner loses its lease mid-drain, the successor has already
advanced past, and the drained rows must neither rewind the marker nor double
count. The Redis doubles come from :mod:`tests.unit.test_backfill_control`
rather than being re-declared: ``EvalRedis`` is a one-for-one mirror of the
shipped Lua, and two divergent copies would be exactly the drift that lets a
script change pass a green suite.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from types import SimpleNamespace

import pytest

from core.backfill_runner import (
    BackfillLease,
    Checkpoint,
    DailyBudget,
    run_backfill,
)
from tests.unit.test_backfill_control import BytesRedis, EvalRedis, FakeRedis

pytestmark = pytest.mark.unit

_NOW = datetime.fromisoformat("2026-08-12T12:00:00+00:00")
_TODAY = "2026-08-12"

# Every client shape the runner is constructed against: no ``eval`` (the
# documented non-atomic fallback), ``eval`` (what real Redis takes), and a
# bytes-answering client (``get_redis()`` is ``decode_responses=False``).
_CLIENTS = [FakeRedis, EvalRedis, BytesRedis]


class BytesEvalRedis(EvalRedis):
    """Atomic client that answers in raw bytes — ``bool(b"0")`` is ``True``.

    The trap :func:`core.backfill_runner._reply_is_true` exists for: a refused
    CAS coming back as ``b"0"`` must never read as "recorded", or a displaced
    runner believes it still owns the checkpoint.
    """

    def get(self, key):
        raw = FakeRedis.get(self, key)
        return None if raw is None else raw.encode()

    def hgetall(self, key):
        return {k.encode(): v.encode() for k, v in FakeRedis.hgetall(self, key).items()}

    def eval(self, script, numkeys, *keys_and_args):
        return str(super().eval(script, numkeys, *keys_and_args)).encode()


def _checkpoint(redis, *, lease=None):
    return Checkpoint(redis, prefix="t", now_fn=lambda: _NOW, lease=lease)


def _budget(redis, limit=1000):
    return DailyBudget(redis, prefix="t", daily_limit=limit, now_fn=lambda: _NOW)


def _rows(n):
    return [
        (SimpleNamespace(id=f"prop-{i}"), SimpleNamespace(ai_score=None))
        for i in range(n)
    ]


async def _noop_sleep(_):
    return None


def _held_lease(redis, *, owner="me:1"):
    lease = BackfillLease(redis, prefix="t", ttl_seconds=60, owner=owner)
    assert lease.acquire() is True
    return lease


def _steal(redis, token="successor-token"):
    """A successor's lease token replaces ours (ours had lapsed)."""
    redis.kv["t:lease"] = token
    return token


# ---------------------------------------------------------------------------
# Checkpoint.advance — the compare-and-set itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("client_cls", _CLIENTS + [BytesEvalRedis])
def test_advance_without_a_lease_writes_unconditionally(client_cls):
    """``--status``, ``--dry-run`` and every pre-existing test build it this way."""
    r = client_cls()
    cp = _checkpoint(r)

    assert cp.advance("prop-1") is True
    assert cp.advance("prop-2") is True

    loaded = cp.load()
    assert loaded["last_property_id"] == "prop-2"
    assert loaded["last_run_date"] == _TODAY
    assert cp.processed_total() == 2


@pytest.mark.parametrize("client_cls", _CLIENTS + [BytesEvalRedis])
def test_advance_records_the_row_for_the_lease_owner(client_cls):
    r = client_cls()
    lease = _held_lease(r)
    cp = _checkpoint(r, lease=lease)

    assert cp.advance("prop-1") is True

    loaded = cp.load()
    assert loaded["last_property_id"] == "prop-1"
    assert loaded["last_run_date"] == _TODAY
    assert cp.processed_total() == 1


@pytest.mark.parametrize("client_cls", _CLIENTS + [BytesEvalRedis])
def test_advance_is_refused_once_another_runner_holds_the_lease(client_cls):
    r = client_cls()
    lease = _held_lease(r)
    cp = _checkpoint(r, lease=lease)
    _steal(r)

    assert cp.advance("prop-1") is False
    # Nothing written at all — not the id, not the date, not the counter.
    assert r.hashes.get("t:checkpoint", {}) == {}
    assert cp.processed_total() == 0
    # The refusal reads the lease key; it must never write it.
    assert r.kv["t:lease"] == "successor-token"


def test_advance_never_overwrites_the_successors_marker():
    """The DW-11 damage, at the level of the two fields an operator reads."""
    r = EvalRedis()
    displaced = _held_lease(r, owner="loser:1")
    successor = BackfillLease(r, prefix="t", ttl_seconds=60, owner="winner:2")
    _steal(r, successor.token)
    _checkpoint(r, lease=successor).advance("successor-row")

    assert _checkpoint(r, lease=displaced).advance("drained-row") is False

    loaded = _checkpoint(r).load()
    assert loaded["last_property_id"] == "successor-row"  # no rewind
    assert _checkpoint(r).processed_total() == 1  # no double count


def test_advance_takes_the_atomic_eval_branch_when_available():
    r = EvalRedis()
    lease = _held_lease(r)
    before = r.eval_calls

    assert _checkpoint(r, lease=lease).advance("prop-1") is True

    assert r.eval_calls == before + 1  # one script, not a get-then-write


def test_a_lease_less_advance_runs_no_script_at_all():
    r = EvalRedis()

    assert _checkpoint(r).advance("prop-1") is True

    assert r.eval_calls == 0


def test_a_bytes_refusal_never_reads_as_recorded():
    """``bool(b"0")`` is ``True``; only ``_reply_is_true`` gets this right."""
    r = BytesEvalRedis()
    lease = _held_lease(r)
    _steal(r)

    assert _checkpoint(r, lease=lease).advance("prop-1") is False


def test_the_eval_less_path_warns_once_that_it_is_not_atomic(caplog):
    r = FakeRedis()
    assert not hasattr(r, "eval")
    lease = _held_lease(r)
    cp = _checkpoint(r, lease=lease)

    with caplog.at_level(logging.WARNING, logger="core.backfill_runner"):
        assert cp.advance("prop-1") is True
        assert cp.advance("prop-2") is True

    warnings = [
        rec
        for rec in caplog.records
        if rec.getMessage() == "backfill_non_atomic_redis_fallback"
        and getattr(rec, "surface", None) == "checkpoint advance"
    ]
    assert len(warnings) == 1  # latched per object, per surface
    assert cp.processed_total() == 2


# ---------------------------------------------------------------------------
# run_backfill — the real handover
# ---------------------------------------------------------------------------


def _run(rows, *, redis, checkpoint, **kw):
    return asyncio.run(
        asyncio.wait_for(
            run_backfill(
                rows,
                budget=_budget(redis),
                checkpoint=checkpoint,
                requests_per_property=3,
                sleep_fn=_noop_sleep,
                **kw,
            ),
            timeout=5,
        )
    )


def test_a_displaced_runners_drain_neither_rewinds_nor_double_counts():
    """The headline regression (DW-11).

    The owner loses the lease while rows are still in flight, the successor has
    already advanced the shared checkpoint past everything this run is holding,
    and the drain then completes. The marker must still be the successor's and
    the all-time counter must still count each property once — the drained rows
    are reported as ``processed`` + ``unrecorded_completions`` instead.
    """
    r = EvalRedis()
    displaced = _held_lease(r, owner="loser:1")
    successor = BackfillLease(r, prefix="t", ttl_seconds=60, owner="winner:2")
    seen: list[str] = []

    async def enrich(prop):
        seen.append(prop.id)
        if prop.id == "prop-0":
            # Our TTL lapsed, a successor took the lease over and moved the
            # shared checkpoint well past the rows we are still draining.
            _steal(r, successor.token)
            _checkpoint(r, lease=successor).advance("successor-row")

    result = _run(
        _rows(6),
        redis=r,
        checkpoint=_checkpoint(r, lease=displaced),
        enrich_fn=enrich,
        concurrency=3,
        lease=displaced,
    )

    assert result.lease_lost is True
    assert result.stopped is False  # a lost lease is not an operator stop
    assert 0 < len(seen) < 6  # in-flight rows drained; nothing new launched
    assert result.processed == len(seen)  # the work itself is still reported
    # The damage DW-11 describes, asserted first: no rewind, no double count.
    loaded = _checkpoint(r).load()
    assert loaded["last_property_id"] == "successor-row"
    assert loaded["last_run_date"] == _TODAY  # the successor's stamp, not ours
    assert _checkpoint(r).processed_total() == 1
    # The suppressed bookkeeping is reported rather than silently dropped.
    assert result.unrecorded_completions == result.processed
    assert result.to_dict()["unrecorded_completions"] == result.processed
    assert r.kv["t:lease"] == successor.token  # never stolen back


def test_the_cas_refusal_is_itself_a_lease_loss_detector(caplog):
    """No renew has failed yet — the write is what discovers the takeover.

    At the shipped ``lease_ttl_seconds: 900`` the renewer only looks every 300s,
    so an in-process flag alone would leave five minutes of drained rows writing
    on a lease somebody else owns.
    """
    r = EvalRedis()
    lease = _held_lease(r)
    seen: list[str] = []

    async def enrich(prop):
        seen.append(prop.id)
        _steal(r)  # stolen mid-row; nothing has renewed since

    with caplog.at_level(logging.WARNING, logger="core.backfill_runner"):
        result = _run(
            _rows(5),
            redis=r,
            checkpoint=_checkpoint(r, lease=lease),
            enrich_fn=enrich,
            concurrency=1,
            lease=lease,
        )

    assert result.lease_lost is True
    assert result.unrecorded_completions == 1
    assert seen == ["prop-0"]  # the launch loop stopped at its next check
    assert result.processed == 1
    assert _checkpoint(r).processed_total() == 0
    # One line, not one per drained row.
    lost = [r_ for r_ in caplog.records if r_.getMessage() == "backfill_lease_lost"]
    assert len(lost) == 1
    assert "checkpoint" in getattr(lost[0], "reason", "")


def test_rows_finishing_after_an_observed_loss_never_touch_redis():
    """Once the flag is set the advance is skipped, not merely refused."""
    r = FakeRedis()
    lease = _held_lease(r)
    calls: list[str] = []

    class _CountingCheckpoint(Checkpoint):
        def advance(self, property_id):
            calls.append(property_id)
            return super().advance(property_id)

    async def enrich(prop):
        if prop.id == "prop-0":
            _steal(r)

    result = _run(
        _rows(4),
        redis=r,
        checkpoint=_CountingCheckpoint(r, prefix="t", now_fn=lambda: _NOW, lease=lease),
        enrich_fn=enrich,
        concurrency=2,
        lease=lease,
    )

    assert result.lease_lost is True
    assert result.unrecorded_completions == result.processed
    # The first completion asks Redis (and is refused); the rest never do.
    assert calls == ["prop-0"]


def test_a_run_that_keeps_its_lease_records_every_row():
    r = EvalRedis()
    lease = _held_lease(r)

    async def enrich(prop):
        return None

    result = _run(
        _rows(4),
        redis=r,
        checkpoint=_checkpoint(r, lease=lease),
        enrich_fn=enrich,
        lease=lease,
    )

    assert result.lease_lost is False
    assert result.processed == 4
    assert result.unrecorded_completions == 0
    assert _checkpoint(r).processed_total() == 4
    assert _checkpoint(r).load()["last_property_id"] == "prop-3"


def test_a_lease_less_run_records_exactly_as_before():
    r = FakeRedis()

    async def enrich(prop):
        return None

    result = _run(_rows(3), redis=r, checkpoint=_checkpoint(r), enrich_fn=enrich)

    assert result.processed == 3
    assert result.unrecorded_completions == 0
    assert _checkpoint(r).processed_total() == 3


def test_a_checkpoint_double_returning_none_reads_as_recorded():
    """Duck-typed checkpoints in the suite return ``None``.

    Only an explicit ``False`` is a refusal — falsiness would make every one of
    them fabricate a lease loss.
    """
    r = FakeRedis()
    lease = _held_lease(r)
    advanced: list[str] = []

    class _NoneCheckpoint:
        def advance(self, pid):  # exactly the duck-typed signature
            advanced.append(pid)

    async def enrich(prop):
        return None

    result = _run(
        _rows(3),
        redis=r,
        checkpoint=_NoneCheckpoint(),
        enrich_fn=enrich,
        lease=lease,
    )

    assert advanced == ["prop-0", "prop-1", "prop-2"]
    assert result.lease_lost is False
    assert result.unrecorded_completions == 0


def test_a_failing_row_neither_advances_nor_counts_as_unrecorded():
    r = EvalRedis()
    lease = _held_lease(r)

    async def enrich(prop):
        if prop.id == "prop-1":
            raise ValueError("one bad row")

    result = _run(
        _rows(3),
        redis=r,
        checkpoint=_checkpoint(r, lease=lease),
        enrich_fn=enrich,
        lease=lease,
    )

    assert result.processed == 2
    assert result.errors == 1
    assert result.unrecorded_completions == 0
    assert _checkpoint(r).processed_total() == 2


def test_a_redis_error_in_the_advance_still_drains_the_siblings():
    """It runs outside ``_worker``'s ``except``; the gather absorbs it."""
    r = FakeRedis()
    lease = _held_lease(r)
    done: list[str] = []

    class _OneShotCheckpoint(Checkpoint):
        def advance(self, property_id):
            if property_id == "prop-0":
                raise ConnectionError("checkpoint write failed")
            done.append(property_id)
            return True

    async def enrich(prop):
        await asyncio.sleep(0)

    result = _run(
        _rows(3),
        redis=r,
        checkpoint=_OneShotCheckpoint(r, prefix="t", now_fn=lambda: _NOW, lease=lease),
        enrich_fn=enrich,
        concurrency=3,
        lease=lease,
    )

    assert done == ["prop-1", "prop-2"]
    assert result.processed == 3  # the row really was enriched
    assert result.lease_lost is False  # a blip is not a handover
    # The row is enriched and committed but the shared hash never took it, so
    # it belongs in the same count the banner reports — otherwise ``processed``
    # and ``processed_total`` disagree with nothing explaining the gap.
    assert result.unrecorded_completions == 1


def test_a_raising_advance_leaves_the_ai_breaker_reset(caplog):
    """A checkpoint blip must not make a *successful* row look degraded.

    ``_record_completion`` propagates by design, so anything the success branch
    still has to do has to happen ahead of it: with the resets below the write,
    one Redis blip left ``consecutive_degraded`` carrying failures from before a
    good row and walked the AI breaker towards a trip it had no evidence for.
    """
    r = FakeRedis()
    lease = _held_lease(r)

    class _AlwaysRaisingCheckpoint(Checkpoint):
        def advance(self, property_id):
            raise ConnectionError("checkpoint write failed")

    class _Degraded(Exception):
        is_degraded_result = True

    async def enrich(prop):
        # degraded, good, degraded, good, … — never two degraded in a row, so
        # a breaker with a threshold of 2 must never open.
        if prop.id in {"prop-0", "prop-2"}:
            raise _Degraded("fabricated")

    with caplog.at_level(logging.WARNING, logger="core.backfill_runner"):
        result = _run(
            _rows(4),
            redis=r,
            checkpoint=_AlwaysRaisingCheckpoint(
                r, prefix="t", now_fn=lambda: _NOW, lease=lease
            ),
            enrich_fn=enrich,
            concurrency=1,
            max_consecutive_ai_failures=2,
            lease=lease,
        )

    assert result.ai_circuit_open is False
    assert result.processed == 2
    assert result.ai_fallbacks == 2
    assert result.unrecorded_completions == 2


def test_a_lease_held_run_warns_when_its_checkpoint_is_not_gated(caplog):
    """The guarantee lives on the caller's wiring, so an ungated one must say so."""
    r = EvalRedis()
    lease = _held_lease(r)

    async def enrich(prop):
        return None

    with caplog.at_level(logging.WARNING, logger="core.backfill_runner"):
        _run(
            _rows(1),
            redis=r,
            checkpoint=_checkpoint(r),  # no lease wired in — pre-fix behaviour
            enrich_fn=enrich,
            lease=lease,
        )

    ungated = [
        rec for rec in caplog.records if rec.getMessage() == "backfill_checkpoint_ungated"
    ]
    assert len(ungated) == 1
    assert "DW-11" in getattr(ungated[0], "reason", "")


def test_a_correctly_wired_run_and_a_lease_less_one_warn_about_nothing(caplog):
    r = EvalRedis()
    lease = _held_lease(r)

    async def enrich(prop):
        return None

    with caplog.at_level(logging.WARNING, logger="core.backfill_runner"):
        _run(
            _rows(1),
            redis=r,
            checkpoint=_checkpoint(r, lease=lease),
            enrich_fn=enrich,
            lease=lease,
        )
        # No lease at all (``--dry-run`` and the direct core callers): there is
        # no ownership to gate on, so an ungated checkpoint is correct.
        _run(
            _rows(1),
            redis=r,
            checkpoint=_checkpoint(r),
            enrich_fn=enrich,
        )

    assert [
        rec for rec in caplog.records if rec.getMessage() == "backfill_checkpoint_ungated"
    ] == []


def test_rows_recorded_before_the_loss_survive_it(caplog):
    """The mixed case: recorded before the steal, declined after.

    The headline regression steals on the very first row, so a fix that simply
    stopped writing altogether would pass it. Here the owner records two rows,
    *then* loses the lease, and both halves have to be right at once.
    """
    r = EvalRedis()
    lease = _held_lease(r)
    seen: list[str] = []

    async def enrich(prop):
        seen.append(prop.id)
        if prop.id == "prop-2":
            _steal(r)

    with caplog.at_level(logging.WARNING, logger="core.backfill_runner"):
        result = _run(
            _rows(6),
            redis=r,
            checkpoint=_checkpoint(r, lease=lease),
            enrich_fn=enrich,
            concurrency=1,
            lease=lease,
        )

    assert seen == ["prop-0", "prop-1", "prop-2"]
    assert result.processed == 3
    # Two rows recorded under our own lease; the third finished after the steal.
    assert _checkpoint(r).processed_total() == 2
    assert _checkpoint(r).load()["last_property_id"] == "prop-1"
    assert result.unrecorded_completions == 1
    assert result.last_property_id == "prop-2"  # this run's own row, not the marker
    # Reported once, at the end, with the whole count.
    declined = [
        rec
        for rec in caplog.records
        if rec.getMessage() == "backfill_checkpoint_declined"
    ]
    assert len(declined) == 1
    assert getattr(declined[0], "unrecorded_completions", None) == 1


def test_an_unavailable_eval_degrades_to_the_guarded_write(caplog):
    """Scripting refused: still token-guarded, never a raise per finished row."""

    class _NoScriptingRedis(EvalRedis):
        def eval(self, script, numkeys, *keys_and_args):
            raise RuntimeError("ERR unknown command 'EVAL'")

    r = _NoScriptingRedis()
    lease = _held_lease(r)
    cp = _checkpoint(r, lease=lease)

    with caplog.at_level(logging.WARNING, logger="core.backfill_runner"):
        assert cp.advance("prop-0") is True
        assert cp.advance("prop-1") is True
        _steal(r)
        assert cp.advance("prop-2") is False  # the fallback still refuses

    assert cp.processed_total() == 2
    assert cp.load()["last_property_id"] == "prop-1"
    failed = [
        rec
        for rec in caplog.records
        if rec.getMessage() == "backfill_checkpoint_eval_failed"
    ]
    assert len(failed) == 1  # once per checkpoint, not once per row
