"""Unit tests for the admin backfill control endpoints (v0.13-s1.5).

Thin-glue tier: one happy path and one conflict/error path per endpoint, with
Redis and AppConfig mocked. The control semantics themselves are covered in
``test_backfill_start_request.py`` / ``test_backfill_control.py`` — what is
asserted here is the wiring: the right primitive is called, the right status
code comes back, the mutation is audited, and a Redis failure becomes a generic
500 instead of leaking internals.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from core.backfill_runner import BackfillControl, BackfillLease

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    """Unit runs have no slowapi Redis; the decorator then calls straight through."""
    from infra.limiter import limiter

    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous


class FakeRedis:
    """Dict-backed Redis with ``SET NX EX`` semantics (no ``eval``/``getdel``)."""

    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}

    def get(self, key):
        return self.kv.get(key)

    def set(self, key, val, ex=None, nx=False):
        if nx and key in self.kv:
            return None
        self.kv[key] = str(val)
        return True

    def expire(self, key, ttl):
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


def _cfg():
    return SimpleNamespace(
        backfill=SimpleNamespace(
            redis_prefix="t",
            daily_request_budget=14000,
            requests_per_property=3,
            rpm_limit=30,
            concurrency=1,
            tpm_limit=16000,
            max_attempts=3,
            lease_ttl_seconds=900,
        )
    )


# ---------------------------------------------------------------------------
# GET /admin/backfill/status
# ---------------------------------------------------------------------------


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_status_reports_an_idle_control_plane(mock_cfg, mock_redis, _audit):
    from api.admin import backfill_status

    mock_cfg.return_value = _cfg()
    redis = FakeRedis()
    mock_redis.return_value = redis

    body = backfill_status()

    assert body.state == "idle"
    assert body.active is False
    assert body.runner_present is False
    assert body.lease is None
    assert body.pending_requests == []
    assert body.budget.limit == 14000
    assert body.budget.remaining == 14000
    assert body.pacing.requests_per_property == 3
    # Read-only: the API must never beat the heartbeat migrate-primary.sh reads.
    assert redis.get("t:active") is None


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_status_reports_a_live_run_from_the_lease(mock_cfg, mock_redis, _audit):
    from api.admin import backfill_status

    mock_cfg.return_value = _cfg()
    redis = FakeRedis()
    mock_redis.return_value = redis
    assert BackfillLease(redis, prefix="t", owner="host:4711").acquire()
    BackfillControl(redis, prefix="t").request_pause()

    body = backfill_status()

    # DW-20: no state key (it aged out under a slow row) yet the run is live.
    assert body.state == "idle"
    assert body.active is True
    assert body.runner_present is True
    assert body.lease.owner == "host:4711"
    assert body.pending_requests == ["pause"]


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis", side_effect=RuntimeError("redis://user:pw@host down"))
@patch("api.admin.get_config")
def test_status_maps_a_redis_failure_to_a_generic_500(mock_cfg, _redis, _audit):
    from api.admin import backfill_status

    mock_cfg.return_value = _cfg()

    with pytest.raises(HTTPException) as exc_info:
        backfill_status()

    assert exc_info.value.status_code == 500
    assert "redis://" not in str(exc_info.value.detail)


# ---------------------------------------------------------------------------
# POST /admin/backfill/start
# ---------------------------------------------------------------------------


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_start_records_a_request_and_audits_it(mock_cfg, mock_redis, mock_audit):
    from api.admin import backfill_start

    mock_cfg.return_value = _cfg()
    redis = FakeRedis()
    mock_redis.return_value = redis

    body = backfill_start(request=None)

    assert body.requested is True
    assert body.already_requested is False
    assert body.requested_at
    assert body.runner_present is False  # no supervisor is waiting
    assert json.loads(redis.kv["t:control:start"])["source"] == "admin-api"
    # No runner is spawned and no lease is taken by the API.
    assert redis.get("t:lease") is None
    assert mock_audit.call_args[0][0] == "backfill_start"


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_start_is_refused_with_409_while_a_run_holds_the_lease(
    mock_cfg, mock_redis, mock_audit
):
    from api.admin import backfill_start

    mock_cfg.return_value = _cfg()
    redis = FakeRedis()
    mock_redis.return_value = redis
    assert BackfillLease(redis, prefix="t", owner="host:4711").acquire()

    with pytest.raises(HTTPException) as exc_info:
        backfill_start(request=None)

    assert exc_info.value.status_code == 409
    detail = str(exc_info.value.detail)
    assert "host:4711" in detail
    assert "held for" in detail
    # No request written, and the refusal is on the audit trail.
    assert "t:control:start" not in redis.kv
    assert mock_audit.call_args[0][0] == "backfill_start_refused"


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_a_second_start_preserves_the_original_request(mock_cfg, mock_redis, _audit):
    from api.admin import backfill_start

    mock_cfg.return_value = _cfg()
    mock_redis.return_value = FakeRedis()

    first = backfill_start(request=None)
    second = backfill_start(request=None)

    assert second.already_requested is True
    assert second.requested_at == first.requested_at


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_start_reports_the_stale_requests_it_discards(mock_cfg, mock_redis, mock_audit):
    from api.admin import backfill_start

    mock_cfg.return_value = _cfg()
    redis = FakeRedis()
    mock_redis.return_value = redis
    control = BackfillControl(redis, prefix="t")
    control.request_pause()
    control.request_stop()

    body = backfill_start(request=None)

    assert body.discarded_requests == ["pause", "stop"]
    assert control.is_paused() is False
    assert control.should_stop() is False
    assert mock_audit.call_args[0][1]["discarded_requests"] == ["pause", "stop"]


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_start_reports_a_waiting_supervisor_as_a_runner_present(
    mock_cfg, mock_redis, _audit
):
    from api.admin import backfill_start

    mock_cfg.return_value = _cfg()
    redis = FakeRedis()
    redis.set("t:supervisor:active", "1")
    mock_redis.return_value = redis

    assert backfill_start(request=None).runner_present is True


# ---------------------------------------------------------------------------
# POST /admin/backfill/pause and /resume
# ---------------------------------------------------------------------------


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_pause_sets_the_level_and_returns_the_refreshed_status(
    mock_cfg, mock_redis, mock_audit
):
    from api.admin import backfill_pause

    mock_cfg.return_value = _cfg()
    redis = FakeRedis()
    mock_redis.return_value = redis

    body = backfill_pause(request=None)

    assert body.action == "pause"
    assert body.status.pending_requests == ["pause"]
    assert redis.get("t:control:pause")
    assert mock_audit.call_args[0][0] == "backfill_pause"


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis", side_effect=RuntimeError("redis down"))
@patch("api.admin.get_config")
def test_pause_maps_a_redis_failure_to_a_generic_500(mock_cfg, _redis, _audit):
    from api.admin import backfill_pause

    mock_cfg.return_value = _cfg()

    with pytest.raises(HTTPException) as exc_info:
        backfill_pause(request=None)

    assert exc_info.value.status_code == 500
    assert "redis down" not in str(exc_info.value.detail)


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_resume_clears_the_pause_and_a_pending_stop(mock_cfg, mock_redis, mock_audit):
    from api.admin import backfill_resume

    mock_cfg.return_value = _cfg()
    redis = FakeRedis()
    mock_redis.return_value = redis
    control = BackfillControl(redis, prefix="t")
    control.request_pause()
    control.request_stop()

    body = backfill_resume(request=None)

    assert body.action == "resume"
    assert body.cleared_stop is True
    assert body.status.pending_requests == []
    assert mock_audit.call_args[0][0] == "backfill_resume"


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis", side_effect=RuntimeError("redis down"))
@patch("api.admin.get_config")
def test_resume_maps_a_redis_failure_to_a_generic_500(mock_cfg, _redis, _audit):
    from api.admin import backfill_resume

    mock_cfg.return_value = _cfg()

    with pytest.raises(HTTPException) as exc_info:
        backfill_resume(request=None)

    assert exc_info.value.status_code == 500
    assert "redis down" not in str(exc_info.value.detail)


# ---------------------------------------------------------------------------
# Start: nothing queued behind a failed response (review patch #5)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@patch("api.admin.log_audit_action", side_effect=RuntimeError("audit exploded"))
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_a_start_that_fails_after_recording_leaves_no_queued_run(
    mock_cfg, mock_redis, _audit
):
    """A 500 must not leave a start request behind: the caller was told the
    start failed, and a supervisor would launch a multi-day cloud run anyway."""
    from api.admin import backfill_start

    mock_cfg.return_value = _cfg()
    redis = FakeRedis()
    mock_redis.return_value = redis

    with pytest.raises(HTTPException) as exc_info:
        backfill_start(request=None)

    assert exc_info.value.status_code == 500
    assert "t:control:start" not in redis.kv


@pytest.mark.unit
@patch("api.admin.log_audit_action", side_effect=RuntimeError("audit exploded"))
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_a_failed_start_does_not_withdraw_an_earlier_operators_request(
    mock_cfg, mock_redis, _audit
):
    """Roll back *our* request, never a request that was already pending."""
    from api.admin import backfill_start

    mock_cfg.return_value = _cfg()
    redis = FakeRedis()
    mock_redis.return_value = redis
    existing = BackfillControl(redis, prefix="t").request_start("cli")

    with pytest.raises(HTTPException):
        backfill_start(request=None)

    still_pending = BackfillControl(redis, prefix="t").start_request()
    assert still_pending is not None
    assert still_pending["requested_at"] == existing["requested_at"]


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_the_start_is_recorded_before_the_stale_levels_are_dropped(
    mock_cfg, mock_redis, _audit
):
    """Ordering: clearing an operator's pause first meant a Redis failure in
    between lost the pause with no start recorded to show for it."""
    from api.admin import backfill_start

    class _OrderedRedis(FakeRedis):
        def __init__(self) -> None:
            super().__init__()
            self.ops: list[str] = []

        def set(self, key, val, ex=None, nx=False):
            self.ops.append(f"set {key}")
            return super().set(key, val, ex=ex, nx=nx)

        def delete(self, key):
            self.ops.append(f"delete {key}")
            return super().delete(key)

    mock_cfg.return_value = _cfg()
    redis = _OrderedRedis()
    mock_redis.return_value = redis
    BackfillControl(redis, prefix="t").request_pause()
    redis.ops.clear()

    backfill_start(request=None)

    assert redis.ops.index("set t:control:start") < redis.ops.index(
        "delete t:control:pause"
    )


# ---------------------------------------------------------------------------
# 409 advice matches the state it refuses (review patch #9)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_409_tells_a_healthy_run_to_be_paused_or_stopped():
    from api.admin import _lease_conflict_detail

    detail = _lease_conflict_detail(
        {"owner": "host:4711", "acquired_at": None, "seconds_since_last_seen": 3.0},
        state="running",
        lease_ttl_seconds=900,
    )

    assert "host:4711" in detail
    assert "held" in detail
    assert "--stop" in detail
    assert "resume" not in detail


@pytest.mark.unit
def test_the_409_on_a_paused_run_points_at_resume_not_pause():
    from api.admin import _lease_conflict_detail

    detail = _lease_conflict_detail(
        {"owner": "host:4711", "acquired_at": None, "seconds_since_last_seen": 3.0},
        state="paused",
        lease_ttl_seconds=900,
    )

    assert "paused" in detail
    assert "POST /admin/backfill/resume" in detail
    assert "Pause it" not in detail
    assert "host:4711" in detail


@pytest.mark.unit
@pytest.mark.parametrize("age", [700.0, 899.0])
def test_the_409_on_a_stale_holder_never_advises_an_action_that_cannot_help(age):
    """A holder that has outlived two renewal intervals may well be dead;
    telling the operator to pause or stop it sends them at nothing."""
    from api.admin import _lease_conflict_detail

    detail = _lease_conflict_detail(
        {"owner": "host:4711", "acquired_at": None, "seconds_since_last_seen": age},
        state="running",
        lease_ttl_seconds=900,
    )

    assert "may be dead" in detail
    assert "expires on its own" in detail
    assert "--stop" not in detail
    assert "host:4711" in detail


@pytest.mark.unit
@pytest.mark.parametrize("age", [310.0, 600.0])
def test_one_dropped_provenance_write_does_not_make_a_live_run_read_as_dead(age):
    """The renewer runs at ``ttl/3`` (300s at the 900s default) and the
    ``last_seen`` write it does is best-effort — it swallows its own failure. So
    a single dropped write ages the stamp to ~two intervals under a perfectly
    healthy run, and a ``ttl/2`` threshold reported that run as probably dead,
    telling the operator to wait out an expiry the live renewer keeps pushing
    out — the same worst-advice failure the unknown-``last_seen`` branch exists
    to avoid, reached through the branch next door."""
    from api.admin import _lease_conflict_detail

    detail = _lease_conflict_detail(
        {"owner": "host:4711", "acquired_at": None, "seconds_since_last_seen": age},
        state="running",
        lease_ttl_seconds=900,
    )

    assert "may be dead" not in detail
    assert "--stop" in detail


@pytest.mark.unit
def test_the_stale_reading_does_not_promise_a_run_is_dead():
    """A stale stamp under a live lease has two readings — a dead process, or a
    live one whose provenance write is failing — and the operator acts
    differently on each. Presenting only the first sent them to wait out an
    expiry that may never come."""
    from api.admin import _lease_conflict_detail

    detail = _lease_conflict_detail(
        {"owner": "host:4711", "acquired_at": None, "seconds_since_last_seen": 800.0},
        state="running",
        lease_ttl_seconds=900,
    )

    assert "failing provenance write" in detail
    assert "Check the host" in detail


@pytest.mark.unit
def test_an_unknown_last_seen_is_not_read_as_a_dead_run():
    """The lease meta write is best-effort and swallows its own failure, so a
    healthy multi-day run can hold the lease with no ``last_seen`` at all.
    Telling its operator to wait out an expiry that keeps being renewed is the
    worst advice this surface can give."""
    from api.admin import _lease_conflict_detail

    detail = _lease_conflict_detail(
        {"owner": "host:4711", "acquired_at": None, "seconds_since_last_seen": None},
        state="running",
        lease_ttl_seconds=900,
    )

    assert "may be dead" not in detail
    assert "--stop" in detail
    assert "host:4711" in detail


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_the_route_refuses_a_paused_run_with_resume_advice(mock_cfg, mock_redis, _audit):
    from api.admin import backfill_start
    from core.backfill_runner import BackfillState

    mock_cfg.return_value = _cfg()
    redis = FakeRedis()
    mock_redis.return_value = redis
    assert BackfillLease(redis, prefix="t", owner="host:4711").acquire()
    BackfillControl(redis, prefix="t").publish_state(BackfillState.PAUSED)

    with pytest.raises(HTTPException) as exc_info:
        backfill_start(request=None)

    assert exc_info.value.status_code == 409
    assert "POST /admin/backfill/resume" in str(exc_info.value.detail)


# ---------------------------------------------------------------------------
# Status: no ledger scan on the polled surface (review patch #7)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_status_never_scans_the_attempt_ledger(mock_cfg, mock_redis, _audit):
    """``quarantined_count`` is O(properties ever attempted); story 1.6 polls
    this endpoint every few seconds and it carries no rate limit."""
    from api.admin import backfill_status

    class _WatchingRedis(FakeRedis):
        def __init__(self) -> None:
            super().__init__()
            self.hgetall_keys: list[str] = []

        def hgetall(self, key):
            self.hgetall_keys.append(key)
            return super().hgetall(key)

    mock_cfg.return_value = _cfg()
    redis = _WatchingRedis()
    mock_redis.return_value = redis
    redis.hset("t:attempts", "p1", 3)

    body = backfill_status()

    assert body.quarantined is None
    assert "t:attempts" not in redis.hgetall_keys


# ---------------------------------------------------------------------------
# Pause/resume: an applied mutation is never reported as a 500 (patch #6)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("action", ["pause", "resume"])
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_a_mutation_that_applied_returns_200_with_a_null_status(
    mock_cfg, mock_redis, _audit, action
):
    """The post-mutation snapshot is ~10 more Redis reads. A blip there used to
    turn an applied pause into "Internal server error", so the operator
    concluded it had not taken."""
    import api.admin as admin

    mock_cfg.return_value = _cfg()
    redis = FakeRedis()
    mock_redis.return_value = redis
    handler = getattr(admin, f"backfill_{action}")

    with patch.object(
        admin, "_backfill_snapshot", side_effect=RuntimeError("redis blipped")
    ):
        body = handler(request=None)

    assert body.action == action
    assert body.status is None
    if action == "pause":
        assert redis.get("t:control:pause")  # the mutation really was applied


@pytest.mark.unit
@pytest.mark.parametrize("action", ["pause", "resume"])
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_an_unreachable_audit_database_does_not_fail_an_applied_mutation(
    mock_cfg, mock_redis, mock_audit, action
):
    """``log_audit_action`` guards only its *commit*: an unreachable database
    raises out of ``SessionLocal()`` itself, and that call sits after the level
    is already set in Redis. Unguarded, a database outage told the operator
    their pause had failed while the runner was quietly halting — the same
    "applied mutation reported as a 500" the snapshot guard exists to prevent,
    one line further down."""
    import api.admin as admin

    mock_cfg.return_value = _cfg()
    redis = FakeRedis()
    mock_redis.return_value = redis
    mock_audit.side_effect = RuntimeError("audit database is down")
    handler = getattr(admin, f"backfill_{action}")

    body = handler(request=None)

    assert body.action == action
    if action == "pause":
        assert redis.get("t:control:pause")
    else:
        assert redis.get("t:control:pause") is None


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_an_unreachable_audit_database_does_not_downgrade_the_409_to_a_500(
    mock_cfg, mock_redis, mock_audit
):
    """The refusal is decided by the lease alone. Auditing it before raising
    meant a database outage swallowed the one response that names the run the
    operator is competing with, and handed them a generic 500 instead."""
    from api.admin import backfill_start

    mock_cfg.return_value = _cfg()
    redis = FakeRedis()
    mock_redis.return_value = redis
    assert BackfillLease(redis, prefix="t", owner="host:4711").acquire()
    mock_audit.side_effect = RuntimeError("audit database is down")

    with pytest.raises(HTTPException) as exc_info:
        backfill_start(request=None)

    assert exc_info.value.status_code == 409
    assert "host:4711" in str(exc_info.value.detail)


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_a_blip_reading_the_state_still_yields_the_409(mock_cfg, mock_redis, _audit):
    """The published state only chooses the refusal's wording; losing that one
    extra read must not cost the caller the conflict itself."""
    import api.admin as admin

    mock_cfg.return_value = _cfg()
    redis = FakeRedis()
    mock_redis.return_value = redis
    assert BackfillLease(redis, prefix="t", owner="host:4711").acquire()

    with patch.object(
        admin.BackfillControl, "state", side_effect=RuntimeError("redis blipped")
    ):
        with pytest.raises(HTTPException) as exc_info:
            admin.backfill_start(request=None)

    assert exc_info.value.status_code == 409
    assert "host:4711" in str(exc_info.value.detail)


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_a_start_that_cannot_be_audited_is_still_rolled_back(
    mock_cfg, mock_redis, mock_audit
):
    """The asymmetry is deliberate: a refusal or an applied pause must reach the
    operator even with no audit trail, but a start queues a multi-day cloud
    spend that AD-6 says must be recorded — so this one stays inside the
    rollback rather than becoming best-effort with the others."""
    from api.admin import backfill_start

    mock_cfg.return_value = _cfg()
    redis = FakeRedis()
    mock_redis.return_value = redis
    mock_audit.side_effect = RuntimeError("audit database is down")

    with pytest.raises(HTTPException) as exc_info:
        backfill_start(request=None)

    assert exc_info.value.status_code == 500
    assert BackfillControl(redis, prefix="t").start_request() is None


# ---------------------------------------------------------------------------
# Pause withdraws a doomed start request (review patch #8)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_pause_cancels_a_pending_start_when_no_run_holds_the_lease(
    mock_cfg, mock_redis, mock_audit
):
    """Start then Pause: the launching run clears pause/stop at start-up, so
    leaving the start queued means the run proceeds unpaused and the operator's
    second command was silently void."""
    from api.admin import backfill_pause

    mock_cfg.return_value = _cfg()
    redis = FakeRedis()
    mock_redis.return_value = redis
    control = BackfillControl(redis, prefix="t")
    control.request_start("admin-api")

    body = backfill_pause(request=None)

    assert body.cleared_start is True
    assert control.start_request() is None
    assert control.is_paused() is True
    assert mock_audit.call_args[0][1]["cleared_start"] is True


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_pause_under_a_live_run_leaves_a_start_request_alone(
    mock_cfg, mock_redis, _audit
):
    """With a run holding the lease the pause is aimed at *that* run; the
    request belongs to the next one and must not be withdrawn."""
    from api.admin import backfill_pause

    mock_cfg.return_value = _cfg()
    redis = FakeRedis()
    mock_redis.return_value = redis
    assert BackfillLease(redis, prefix="t", owner="host:4711").acquire()
    control = BackfillControl(redis, prefix="t")
    control.request_start("admin-api")

    body = backfill_pause(request=None)

    assert body.cleared_start is False
    assert control.start_request() is not None


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_a_pause_that_applied_is_not_a_500_when_cancelling_the_start_fails(
    mock_cfg, mock_redis, _audit
):
    """Everything past ``request_pause`` is bookkeeping on an applied mutation:
    a blip there must not tell the operator their pause failed while it sits
    set in Redis — the single worst thing this surface can get wrong."""
    from api.admin import backfill_pause

    class _ClearStartFails(FakeRedis):
        def delete(self, key):
            if key.endswith(":control:start"):
                raise ConnectionError("Connection reset by peer")
            return super().delete(key)

    mock_cfg.return_value = _cfg()
    redis = _ClearStartFails()
    mock_redis.return_value = redis
    control = BackfillControl(redis, prefix="t")
    control.request_start("admin-api")

    body = backfill_pause(request=None)

    assert body.action == "pause"
    assert control.is_paused() is True
    # Honest about the half that did not happen, without losing the half that did.
    assert body.cleared_start is False


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_pause_does_not_claim_a_cancellation_a_supervisor_beat_it_to(
    mock_cfg, mock_redis, mock_audit
):
    """The supervisor polls every couple of seconds and ``consume_start`` is
    destructive: reporting a cancellation that did not happen is a lie the
    operator would act on."""
    from api.admin import backfill_pause

    mock_cfg.return_value = _cfg()
    redis = FakeRedis()
    mock_redis.return_value = redis
    control = BackfillControl(redis, prefix="t")
    control.request_start("admin-api")

    original_set = redis.set

    def _consumed_by_a_supervisor(key, val, ex=None, nx=False):
        written = original_set(key, val, ex=ex, nx=nx)
        if key.endswith(":control:pause"):
            # The supervisor took the request between the read and the clear.
            assert control.consume_start() is not None
        return written

    redis.set = _consumed_by_a_supervisor

    body = backfill_pause(request=None)

    assert control.is_paused() is True
    assert body.cleared_start is False
    assert mock_audit.call_args[0][1]["cleared_start"] is False


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_pause_with_nothing_queued_reports_no_cancelled_start(
    mock_cfg, mock_redis, _audit
):
    from api.admin import backfill_pause

    mock_cfg.return_value = _cfg()
    mock_redis.return_value = FakeRedis()

    assert backfill_pause(request=None).cleared_start is False


# ---------------------------------------------------------------------------
# Documented contracts (review patches #3, #10, #11)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_pending_request_vocabulary_has_exactly_one_derivation():
    """Three private copies of the same two ``if``s is how the wire contract and
    the CLI drift into disagreeing about what is pending."""
    import api.admin as admin
    from core.backfill_runner import pending_control_requests

    assert admin.pending_control_requests is pending_control_requests
    assert not hasattr(admin, "_pending_control_requests")


@pytest.mark.unit
def test_every_backfill_route_is_behind_the_admin_router_gate():
    """Auth is router-level: no handler may be reachable without it."""
    from api.admin import router

    paths = {
        route.path
        for route in router.routes
        if route.path.startswith("/admin/backfill")
    }
    assert paths == {
        "/admin/backfill/status",
        "/admin/backfill/start",
        "/admin/backfill/pause",
        "/admin/backfill/resume",
    }
    # Named, not merely non-empty: asserting ``router.dependencies`` is truthy
    # keeps passing if the gate is swapped for any other dependency — on the one
    # test whose whole subject is that these four routes cannot be reached
    # without admin credentials.
    from api.auth import verify_admin_access

    gates = {getattr(dep, "dependency", None) for dep in router.dependencies}
    assert verify_admin_access in gates


@pytest.mark.unit
def test_the_primitives_helper_is_the_only_redis_construction_site():
    """AD-13: one control path — no scattered key access in the API layer.

    Parsed, not grepped: a line filter over the source matched on a *comment*,
    so rewording it broke the test and any new comment mentioning both words
    would too. What matters is that no backfill route calls ``get_redis()`` (or
    builds a control primitive) for itself.
    """
    import ast
    import inspect
    from pathlib import Path

    import api.admin as admin

    source = Path(inspect.getsourcefile(admin)).read_text(encoding="utf-8")
    functions = {
        node.name: node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    primitives = {
        "get_redis",
        "BackfillLease",
        "BackfillControl",
        "DailyBudget",
        "Checkpoint",
        "Heartbeat",
        "MigrationGate",
        "AttemptLedger",
    }

    def _calls(node):
        return {
            child.func.id
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        }

    for name in ("backfill_status", "backfill_start", "backfill_pause", "backfill_resume"):
        assert not (_calls(functions[name]) & primitives), name
        assert "_backfill_primitives" in _calls(functions[name]), name

    assert _calls(functions["_backfill_primitives"]) & {"get_redis"}
