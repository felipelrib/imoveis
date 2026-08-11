"""Unit tests for the start-request lifecycle and the status snapshot (v0.13-s1.5).

Pure ``src/core`` logic against dict-backed fake Redis clients — no DB, network,
Celery or adapter import. Covers the new ``BackfillControl`` start-request level
key (written by the admin API, consumed by the host-side ``--serve``
supervisor), ``Heartbeat.is_active`` and every row of the story's I/O matrix as
it lands in :func:`build_status_snapshot` — the single aggregator the API and
``--status`` both read, so Redis key layout never leaks into ``src/api``.
"""

from __future__ import annotations

import json

import pytest

from core.backfill_runner import (
    _START_REQUEST_TTL_SECONDS,
    AttemptLedger,
    BackfillControl,
    BackfillLease,
    BackfillState,
    Checkpoint,
    DailyBudget,
    Heartbeat,
    MigrationGate,
    build_status_snapshot,
    pending_control_requests,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeRedis:
    """Dict-backed Redis with ``SET NX EX`` semantics and **no** ``getdel``."""

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


class GetDelRedis(FakeRedis):
    """Fake that also exposes ``getdel`` — the atomic consume branch."""

    def __init__(self) -> None:
        super().__init__()
        self.getdel_calls = 0

    def getdel(self, key):
        self.getdel_calls += 1
        value = self.kv.pop(key, None)
        self.expires.pop(key, None)
        return value


def _control(redis, **kwargs) -> BackfillControl:
    return BackfillControl(redis, prefix="t", **kwargs)


# ---------------------------------------------------------------------------
# Start request lifecycle
# ---------------------------------------------------------------------------


def test_request_start_writes_the_level_key_with_source_and_stamp():
    redis = FakeRedis()
    control = _control(redis)

    result = control.request_start("admin-api")

    assert result["already_requested"] is False
    assert result["source"] == "admin-api"
    assert result["requested_at"]
    stored = json.loads(redis.kv["t:control:start"])
    assert stored["source"] == "admin-api"


def test_the_start_request_expires_in_an_hour_not_the_pause_seven_days():
    """A week-old start firing a multi-day cloud spend unattended is worse than
    a forgotten request dying quietly (see the spec's Design Notes)."""
    redis = FakeRedis()
    control = _control(redis)

    control.request_start("admin-api")
    control.request_pause()

    assert redis.expires["t:control:start"] == _START_REQUEST_TTL_SECONDS
    assert _START_REQUEST_TTL_SECONDS == 3600
    assert redis.expires["t:control:pause"] > _START_REQUEST_TTL_SECONDS


def test_a_second_start_request_preserves_the_original_stamp():
    redis = FakeRedis()
    control = _control(redis)

    first = control.request_start("admin-api")
    second = control.request_start("someone-else")

    assert second["already_requested"] is True
    assert second["requested_at"] == first["requested_at"]
    assert second["source"] == "admin-api"


class _StartRaceRedis(FakeRedis):
    """The exact window ``request_start``'s fallback exists for.

    The ``SET NX`` loses, the key then reads back empty (it expired in the
    window), and a *rival* caller wins the recovery write before we get there.
    """

    _KEY = "t:control:start"

    def __init__(self, rival: str) -> None:
        super().__init__()
        self.kv[self._KEY] = json.dumps({"source": "incumbent", "requested_at": "T0"})
        self._rival = rival
        self._gets = 0
        self.nx_flags: list[bool] = []

    def get(self, key):
        if key == self._KEY:
            self._gets += 1
            if self._gets == 1:
                self.kv.pop(key, None)  # expired between the SET NX and this read
                self.kv[key] = self._rival  # …and a rival wins the recovery write
                return None
        return super().get(key)

    def set(self, key, val, ex=None, nx=False):
        if key == self._KEY:
            self.nx_flags.append(bool(nx))
        return super().set(key, val, ex=ex, nx=nx)


def test_the_start_request_recovery_write_cannot_clobber_a_rivals_stamp():
    """The fallback must keep the guarantee the method exists to make.

    A plain ``SET`` there meant two callers racing through the "expired in the
    window" branch both took the honor-the-caller path and the second overwrote
    the first's ``requested_at`` — the one thing ``SET NX`` was chosen for.
    """
    rival = json.dumps({"source": "rival", "requested_at": "T1"})
    redis = _StartRaceRedis(rival)
    control = _control(redis)

    result = control.request_start("loser")

    assert result["already_requested"] is True
    assert result["source"] == "rival"
    assert result["requested_at"] == "T1"
    assert json.loads(redis.kv["t:control:start"])["source"] == "rival"
    # Every write to the start key competes; none of them overwrite blindly.
    assert redis.nx_flags == [True, True]


def test_a_start_request_that_expired_in_the_window_is_still_honored():
    """The uncontended half of the same branch: nobody else wrote, so the
    caller's request must land rather than being swallowed."""

    class _ExpiringRedis(FakeRedis):
        def __init__(self) -> None:
            super().__init__()
            self.kv["t:control:start"] = json.dumps({"source": "gone", "requested_at": "T0"})
            self._first_get = True

        def get(self, key):
            if key == "t:control:start" and self._first_get:
                self._first_get = False
                self.kv.pop(key, None)
                return None
            return super().get(key)

    redis = _ExpiringRedis()

    result = _control(redis).request_start("admin-api")

    assert result["already_requested"] is False
    assert result["source"] == "admin-api"
    assert json.loads(redis.kv["t:control:start"])["source"] == "admin-api"


def test_start_request_reads_back_none_when_nothing_is_pending():
    assert _control(FakeRedis()).start_request() is None


def test_start_request_tolerates_a_value_it_did_not_write():
    redis = FakeRedis()
    redis.set("t:control:start", "1")

    pending = _control(redis).start_request()

    assert pending == {"source": "unknown", "requested_at": None}


def test_a_foreign_requested_at_is_read_back_as_a_string():
    """``source`` was coerced and ``requested_at`` was not, which undid the
    decode-anything guard one line later: the value is published as
    ``start_requested_at`` on a response model typed ``Optional[str]``, so a
    payload written by anything else (a number, an object) failed response
    validation and turned every status poll into a 500."""
    redis = FakeRedis()
    redis.set("t:control:start", json.dumps({"source": 7, "requested_at": 1754500000}))

    pending = _control(redis).start_request()

    assert pending == {"source": "7", "requested_at": "1754500000"}


def test_consume_start_uses_getdel_when_the_client_has_it():
    redis = GetDelRedis()
    control = _control(redis)
    control.request_start("admin-api")

    consumed = control.consume_start()

    assert consumed["source"] == "admin-api"
    assert redis.getdel_calls == 1
    assert control.start_request() is None


def test_consume_start_falls_back_to_get_then_delete():
    redis = FakeRedis()
    control = _control(redis)
    control.request_start("admin-api")

    consumed = control.consume_start()

    assert consumed["source"] == "admin-api"
    assert "t:control:start" not in redis.kv
    assert control.consume_start() is None


def test_consume_start_returns_none_when_nothing_is_pending():
    assert _control(GetDelRedis()).consume_start() is None
    assert _control(FakeRedis()).consume_start() is None


def test_clear_start_drops_the_request():
    redis = FakeRedis()
    control = _control(redis)
    control.request_start("admin-api")

    assert control.clear_start() is True

    assert control.start_request() is None


def test_clear_start_reports_that_it_removed_nothing():
    """A caller that read the request a moment earlier cannot assume it is
    still there — a supervisor polling every couple of seconds may have
    consumed it — and reporting a cancellation that did not happen is worse
    than reporting none."""
    control = _control(FakeRedis())

    assert control.clear_start() is False


def test_clear_requests_never_eats_the_start_request_that_spawned_the_run():
    """``clear_requests`` means pause+stop only — a run must not discard the
    start request it was launched by (the supervisor consumes that itself)."""
    redis = FakeRedis()
    control = _control(redis)
    control.request_pause()
    control.request_stop()
    control.request_start("admin-api")

    control.clear_requests()

    assert control.is_paused() is False
    assert control.should_stop() is False
    assert control.start_request() is not None


def test_resume_leaves_a_pending_start_request_alone():
    redis = FakeRedis()
    control = _control(redis)
    control.request_start("admin-api")
    control.request_pause()

    control.request_resume()

    assert control.is_paused() is False
    assert control.start_request() is not None


# ---------------------------------------------------------------------------
# Heartbeat.is_active
# ---------------------------------------------------------------------------


def test_heartbeat_is_active_only_between_beat_and_clear():
    redis = FakeRedis()
    heartbeat = Heartbeat(redis, prefix="t")

    assert heartbeat.is_active() is False
    heartbeat.beat()
    assert heartbeat.is_active() is True
    heartbeat.clear()
    assert heartbeat.is_active() is False


# ---------------------------------------------------------------------------
# build_status_snapshot — the I/O matrix
# ---------------------------------------------------------------------------


_PACING = {
    "requests_per_property": 3,
    "rpm_limit": 30,
    "concurrency": 1,
    "tpm_limit": 16000,
}


_UNSET = object()


def _snapshot(
    redis,
    *,
    owner: str = "host:4711",
    daily_limit: int = 14000,
    ledger: object = _UNSET,
    budget: object = None,
) -> dict:
    return build_status_snapshot(
        lease=BackfillLease(redis, prefix="t", owner=owner),
        control=BackfillControl(redis, prefix="t"),
        budget=budget
        if budget is not None
        else DailyBudget(redis, prefix="t", daily_limit=daily_limit),
        checkpoint=Checkpoint(redis, prefix="t"),
        heartbeat=Heartbeat(redis, prefix="t"),
        migration_gate=MigrationGate(redis, prefix="t"),
        ledger=(
            AttemptLedger(redis, prefix="t", max_attempts=3)
            if ledger is _UNSET
            else ledger
        ),
        supervisor_heartbeat=Heartbeat(redis, prefix="t:supervisor"),
        daily_limit=daily_limit,
        pacing=dict(_PACING),
    )


def test_snapshot_with_nothing_running():
    snap = _snapshot(FakeRedis())

    assert snap["state"] == BackfillState.IDLE.value
    assert snap["active"] is False
    assert snap["runner_present"] is False
    assert snap["heartbeat_active"] is False
    assert snap["migration_active"] is False
    assert snap["lease"] is None
    assert snap["pending_requests"] == []
    assert snap["start_requested_at"] is None
    assert snap["budget"] == {
        "limit": 14000,
        "consumed": 0,
        "remaining": 14000,
        "seconds_until_reset": 0.0,
    }
    assert snap["checkpoint"] == {
        "last_property_id": None,
        "last_run_date": None,
        "processed_total": 0,
    }
    assert snap["quarantined"] == 0
    assert snap["pacing"] == _PACING


def test_snapshot_of_a_live_run_reports_the_lease_holder():
    redis = FakeRedis()
    lease = BackfillLease(redis, prefix="t", owner="host:4711")
    assert lease.acquire()
    BackfillControl(redis, prefix="t").publish_state(BackfillState.RUNNING)
    Heartbeat(redis, prefix="t").beat()
    DailyBudget(redis, prefix="t", daily_limit=14000).try_consume(9)
    Checkpoint(redis, prefix="t").advance("prop-1")

    snap = _snapshot(redis)

    assert snap["state"] == "running"
    assert snap["active"] is True
    assert snap["runner_present"] is True
    assert snap["heartbeat_active"] is True
    assert snap["lease"]["owner"] == "host:4711"
    assert snap["lease"]["acquired_at"]
    assert snap["lease"]["last_seen"]
    assert snap["lease"]["seconds_since_last_seen"] >= 0.0
    # The lease token is a control secret: provenance goes on the wire, not it.
    assert "token" not in snap["lease"]
    assert snap["budget"]["consumed"] == 9
    assert snap["budget"]["remaining"] == 13991
    assert snap["budget"]["seconds_until_reset"] > 0
    assert snap["checkpoint"]["last_property_id"] == "prop-1"
    assert snap["checkpoint"]["processed_total"] == 1


def test_a_decayed_state_key_under_a_held_lease_still_reads_active():
    """DW-20: one row slower than the 120s state TTL makes a live run publish
    ``idle``. The lease — not the state key — is the liveness signal."""
    redis = FakeRedis()
    assert BackfillLease(redis, prefix="t", owner="host:4711").acquire()
    # No state key at all: exactly what the TTL expiring leaves behind.

    snap = _snapshot(redis)

    assert snap["state"] == BackfillState.IDLE.value
    assert snap["active"] is True


def test_snapshot_lists_pending_requests_and_the_start_stamp():
    redis = FakeRedis()
    control = BackfillControl(redis, prefix="t")
    control.request_pause()
    requested = control.request_start("admin-api")

    snap = _snapshot(redis)

    assert snap["pending_requests"] == ["pause"]
    assert snap["start_requested_at"] == requested["requested_at"]


def test_snapshot_lists_a_pending_stop_too():
    redis = FakeRedis()
    control = BackfillControl(redis, prefix="t")
    control.request_pause()
    control.request_stop()

    assert _snapshot(redis)["pending_requests"] == ["pause", "stop"]


def test_a_waiting_supervisor_counts_as_a_runner_present_without_a_lease():
    redis = FakeRedis()
    Heartbeat(redis, prefix="t:supervisor").beat()

    snap = _snapshot(redis)

    assert snap["active"] is False
    assert snap["runner_present"] is True


def test_snapshot_reports_a_primary_migration_and_quarantined_rows():
    redis = FakeRedis()
    redis.set("t:migrating", "token-123")
    # Three attempts is the ceiling ``_snapshot``'s ledger is built with, so
    # this row is retired by the same rule the runner applies.
    ledger = AttemptLedger(redis, prefix="t", max_attempts=3)
    for _ in range(3):
        ledger.record_attempt("bad-1")

    snap = _snapshot(redis)

    assert snap["migration_active"] is True
    assert snap["quarantined"] == 1


class _RollingBudget:
    """A live budget: the window rolls between the two reads a snapshot makes.

    ``consumed()`` sees the old window and ``remaining()`` — a *second* full
    read of the same hash — sees the fresh one, so reporting both verbatim puts
    a pair on the wire that cannot both be true.
    """

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self.remaining_calls = 0

    def consumed(self) -> int:
        return 900

    def remaining(self) -> int:
        self.remaining_calls += 1
        return self._limit  # the rolled window hands out a whole day again

    def seconds_until_reset(self) -> float:
        return 60.0


def test_the_budget_pair_is_arithmetically_consistent_not_two_reads():
    redis = FakeRedis()
    budget = _RollingBudget(14000)

    snap = _snapshot(redis, budget=budget)

    assert snap["budget"]["consumed"] == 900
    assert snap["budget"]["remaining"] == 13100
    assert snap["budget"]["consumed"] + snap["budget"]["remaining"] == 14000
    assert budget.remaining_calls == 0, "remaining must be derived, not re-read"


def test_a_budget_consumed_past_its_limit_never_reports_negative_remaining():
    class _Overspent(_RollingBudget):
        def consumed(self) -> int:
            return 14500

    snap = _snapshot(FakeRedis(), budget=_Overspent(14000))

    assert snap["budget"]["remaining"] == 0


class _ExplodingLedger:
    """Stands in for the real ``HGETALL``-over-every-attempted-row scan."""

    def quarantined_count(self) -> int:  # pragma: no cover - must never run
        raise AssertionError("the polled status surface must not scan the ledger")


def test_the_snapshot_skips_the_ledger_scan_when_no_ledger_is_given():
    """``quarantined_count`` is an ``HGETALL`` over one field per property ever
    attempted (~26k on a full pass) plus a sort. The admin endpoint is polled
    every few seconds and carries no rate limit, so it passes ``ledger=None``."""
    snap = _snapshot(FakeRedis(), ledger=None)

    assert snap["quarantined"] is None


def test_the_ledger_argument_is_optional_altogether():
    redis = FakeRedis()

    snap = build_status_snapshot(
        lease=BackfillLease(redis, prefix="t", owner="host:1"),
        control=BackfillControl(redis, prefix="t"),
        budget=DailyBudget(redis, prefix="t", daily_limit=10),
        checkpoint=Checkpoint(redis, prefix="t"),
        heartbeat=Heartbeat(redis, prefix="t"),
        migration_gate=MigrationGate(redis, prefix="t"),
        supervisor_heartbeat=Heartbeat(redis, prefix="t:supervisor"),
        daily_limit=10,
        pacing=dict(_PACING),
    )

    assert snap["quarantined"] is None


def test_a_ledgerless_snapshot_never_calls_the_scan():
    assert _snapshot(FakeRedis(), ledger=None)["quarantined"] is None
    # …and one built with a ledger still counts (the CLI's --status keeps it).
    with pytest.raises(AssertionError):
        _snapshot(FakeRedis(), ledger=_ExplodingLedger())


# ---------------------------------------------------------------------------
# pending_control_requests — one derivation of the vocabulary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pause,stop,expected",
    [
        (False, False, []),
        (True, False, ["pause"]),
        (False, True, ["stop"]),
        (True, True, ["pause", "stop"]),
    ],
)
def test_pending_control_requests_is_the_shared_vocabulary(pause, stop, expected):
    redis = FakeRedis()
    control = _control(redis)
    if pause:
        control.request_pause()
    if stop:
        control.request_stop()

    assert pending_control_requests(control) == expected
    # The snapshot must *be* this helper, not a second copy of the two ifs.
    assert _snapshot(redis)["pending_requests"] == expected


def test_snapshot_never_beats_the_heartbeat_that_blocks_a_migration():
    """The API only reads: a status call that beat ``:active`` would block
    ``migrate-primary.sh`` for the heartbeat TTL."""
    redis = FakeRedis()

    _snapshot(redis)

    assert redis.get("t:active") is None
    assert redis.get("t:supervisor:active") is None
    assert redis.get("t:lease") is None
