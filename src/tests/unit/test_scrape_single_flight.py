"""Scrape single-flight per platform and scope (Story 1.18).

Every row of the spec's single-flight matrix, against an in-memory Redis with
an injectable clock: the publisher side (beat tick, manual trigger), the worker
side (``scrape_listings``), and the lease lifetimes.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from celery.beat import PersistentScheduler
from celery.exceptions import Retry

from adapters.queue import scrape_single_flight as sf
from adapters.queue.redis_scheduler import RedisAwareScheduler
from adapters.queue.scrape_single_flight import (
    ALREADY_QUEUED,
    ALREADY_RUNNING,
    QUEUED,
    QUEUED_TTL_SECONDS,
    RENEW_EVERY_SECONDS,
    RUNNING_TTL_SECONDS,
    ScrapeSingleFlight,
    enqueue_scrape,
    release_running_leases_of,
    scrape_scope,
)
from infra.config import get_config
from tests.fake_queue_redis import FakeQueueRedis, ManualClock

pytestmark = pytest.mark.unit


def _flight(redis, task_id, *, platform="quintoandar", scope="default", clock=None, owner=None):
    kwargs = {"monotonic": clock} if clock is not None else {}
    if owner is not None:
        kwargs["owner"] = owner
    return ScrapeSingleFlight(redis, platform=platform, scope=scope, task_id=task_id, **kwargs)


# ---------------------------------------------------------------------------
# Scope and lifetimes
# ---------------------------------------------------------------------------


def test_scope_is_default_without_a_checkpoint_override():
    assert scrape_scope(None) == "default"
    assert scrape_scope({}) == "default"


def test_scope_of_an_override_is_a_stable_digest():
    one = scrape_scope({"scrape_type": "rent", "page": 2})
    same = scrape_scope({"page": 2, "scrape_type": "rent"})
    other = scrape_scope({"scrape_type": "sale", "page": 2})
    assert one == same
    assert one != other
    assert one != "default"


def test_both_leases_have_a_ttl():
    """Nothing in the single-flight blocks scraping without a time limit."""
    redis = FakeQueueRedis()
    flight = _flight(redis, "t1")
    assert flight.reserve() == (QUEUED, "t1")
    assert redis.ttl(flight.queued_key) == QUEUED_TTL_SECONDS == 3 * 3600
    assert flight.begin() is True
    assert redis.ttl(flight.running_key) == RUNNING_TTL_SECONDS == 2 * 3600
    assert RENEW_EVERY_SECONDS == 60


def test_keys_name_platform_scope_and_state():
    flight = _flight(FakeQueueRedis(), "t1", platform="olx", scope="default")
    assert flight.queued_key == "scrape:single_flight:olx:default:queued:lease"
    assert flight.running_key == "scrape:single_flight:olx:default:running:lease"


def test_different_scopes_of_one_platform_do_not_block_each_other():
    redis = FakeQueueRedis()
    assert _flight(redis, "beat", scope="default").reserve() == (QUEUED, "beat")
    manual = _flight(redis, "manual", scope=scrape_scope({"scrape_type": "rent"}))
    assert manual.reserve() == (QUEUED, "manual")
    assert manual.begin() is True
    assert _flight(redis, "beat", scope="default").begin() is True


def test_different_platforms_do_not_block_each_other():
    redis = FakeQueueRedis()
    assert _flight(redis, "a", platform="olx").reserve() == (QUEUED, "a")
    assert _flight(redis, "b", platform="zapimoveis").reserve() == (QUEUED, "b")


# ---------------------------------------------------------------------------
# Publisher side
# ---------------------------------------------------------------------------


def test_reserve_reports_the_holder_when_queued_or_running():
    redis = FakeQueueRedis()
    first = _flight(redis, "first")
    assert first.reserve() == (QUEUED, "first")
    assert _flight(redis, "second").reserve() == (ALREADY_QUEUED, "first")
    assert first.holder() == {"state": "queued", "task_id": "first"}

    assert first.begin() is True
    assert _flight(redis, "third").reserve() == (ALREADY_RUNNING, "first")
    assert first.holder() == {"state": "running", "task_id": "first"}

    assert first.finish() is True
    assert first.holder() is None
    assert _flight(redis, "fourth").reserve() == (QUEUED, "fourth")


def test_a_refused_reservation_does_not_touch_the_holder():
    redis = FakeQueueRedis()
    first = _flight(redis, "first")
    first.reserve()
    second = _flight(redis, "second")
    second.reserve()
    assert second.cancel_reservation() is False
    assert redis.get(first.queued_key) == b"first"


def test_enqueue_scrape_publishes_with_the_reserved_id():
    redis = FakeQueueRedis()
    task = MagicMock()
    task_id, status = enqueue_scrape(task, "olx", None, redis)
    assert status == QUEUED
    task.apply_async.assert_called_once_with(args=["olx"], task_id=task_id)
    assert redis.get("scrape:single_flight:olx:default:queued:lease") == task_id.encode()


def test_enqueue_scrape_passes_the_checkpoint_and_scopes_by_it():
    redis = FakeQueueRedis()
    task = MagicMock()
    checkpoint = {"scrape_type": "rent"}
    task_id, status = enqueue_scrape(task, "olx", checkpoint, redis)
    assert status == QUEUED
    task.apply_async.assert_called_once_with(args=["olx", checkpoint], task_id=task_id)
    scope = scrape_scope(checkpoint)
    assert redis.get(f"scrape:single_flight:olx:{scope}:queued:lease") == task_id.encode()


def test_enqueue_scrape_does_not_publish_a_duplicate():
    redis = FakeQueueRedis()
    task = MagicMock()
    first_id, _ = enqueue_scrape(task, "olx", None, redis)
    second_id, status = enqueue_scrape(task, "olx", None, redis)
    assert (second_id, status) == (first_id, ALREADY_QUEUED)
    assert task.apply_async.call_count == 1

    _flight(redis, first_id, platform="olx").begin()
    third_id, status = enqueue_scrape(task, "olx", None, redis)
    assert (third_id, status) == (first_id, ALREADY_RUNNING)
    assert task.apply_async.call_count == 1


def test_enqueue_scrape_releases_the_reservation_when_the_publish_raises():
    redis = FakeQueueRedis()
    task = MagicMock()
    task.apply_async.side_effect = ConnectionError("broker down")
    with pytest.raises(ConnectionError):
        enqueue_scrape(task, "olx", None, redis)
    assert redis.get("scrape:single_flight:olx:default:queued:lease") is None
    task.apply_async.side_effect = None
    assert enqueue_scrape(task, "olx", None, redis)[1] == QUEUED


# ---------------------------------------------------------------------------
# Worker side
# ---------------------------------------------------------------------------


def test_begin_hands_the_reservation_over_to_the_running_lease():
    redis = FakeQueueRedis()
    flight = _flight(redis, "t1")
    flight.reserve()
    assert flight.begin() is True
    assert redis.get(flight.queued_key) is None
    assert redis.get(flight.running_key) == b"t1"
    assert flight.finish() is True
    assert redis.get(flight.running_key) is None


def test_begin_without_a_reservation_takes_the_running_lease_itself():
    """A message published before the single-flight existed still runs."""
    redis = FakeQueueRedis()
    legacy = _flight(redis, "legacy")
    assert legacy.begin() is True
    assert redis.get(legacy.running_key) == b"legacy"


def test_a_duplicate_does_not_begin_and_leaves_the_other_runs_leases_alone():
    redis = FakeQueueRedis()
    first = _flight(redis, "first")
    first.reserve()
    first.begin()
    queued_next = _flight(redis, "next")
    assert queued_next.reserve() == (ALREADY_RUNNING, "first")

    duplicate = _flight(redis, "legacy-duplicate")
    assert duplicate.begin() is False
    assert duplicate.renew() is None
    assert duplicate.finish() is False
    assert redis.get(first.running_key) == b"first"
    assert redis.ttl(first.running_key) == RUNNING_TTL_SECONDS


def test_a_redelivery_of_the_same_id_does_not_begin_or_release_the_first_run():
    """Under ``acks_late`` the broker redelivers the same id after the visibility
    timeout: the token matches, the execution is not the owner."""
    redis = FakeQueueRedis()
    first = _flight(redis, "same-id")
    first.begin()
    redelivered = _flight(redis, "same-id")
    assert redelivered.begin() is False
    assert redelivered.finish() is False
    assert redelivered.renew() is None
    assert redis.get(first.running_key) == b"same-id"


def test_a_duplicate_does_not_drop_another_tasks_reservation():
    redis = FakeQueueRedis()
    reserved = _flight(redis, "reserved")
    reserved.reserve()
    legacy = _flight(redis, "legacy")
    assert legacy.begin() is True  # nothing is running: the legacy message runs
    assert redis.get(reserved.queued_key) == b"reserved"


def test_renew_is_throttled_to_once_a_minute():
    wall = ManualClock()
    mono = ManualClock()
    redis = FakeQueueRedis(wall)
    flight = _flight(redis, "t1", clock=mono)
    flight.begin()

    wall.advance(30)
    mono.advance(30)
    assert flight.renew() is None
    assert redis.ttl(flight.running_key) == RUNNING_TTL_SECONDS - 30

    wall.advance(30)
    mono.advance(30)
    assert flight.renew() is True
    assert redis.ttl(flight.running_key) == RUNNING_TTL_SECONDS

    wall.advance(59)
    mono.advance(59)
    assert flight.renew() is None


def test_a_long_run_keeps_its_lease_past_the_ttl_by_renewing():
    wall = ManualClock()
    mono = ManualClock()
    redis = FakeQueueRedis(wall)
    flight = _flight(redis, "long", clock=mono)
    flight.begin()
    for _ in range(4 * 60):  # four hours, one item a minute
        wall.advance(60)
        mono.advance(60)
        assert flight.renew() is True
    assert _flight(redis, "tick").reserve() == (ALREADY_RUNNING, "long")


def test_renew_reports_a_lost_lease_once_and_stops_owning_it():
    wall = ManualClock()
    mono = ManualClock()
    redis = FakeQueueRedis(wall)
    flight = _flight(redis, "stalled", clock=mono)
    flight.begin()

    wall.advance(RUNNING_TTL_SECONDS + 1)  # no item for longer than the TTL
    mono.advance(RUNNING_TTL_SECONDS + 1)
    successor = _flight(redis, "successor")
    assert successor.begin() is True

    assert flight.renew() is False
    mono.advance(RENEW_EVERY_SECONDS)
    assert flight.renew() is None
    assert flight.finish() is False
    assert redis.get(successor.running_key) == b"successor"


def test_a_crashed_run_frees_its_platform_when_the_lease_expires():
    wall = ManualClock()
    redis = FakeQueueRedis(wall)
    crashed = _flight(redis, "crashed")
    crashed.begin()  # process killed: finish() never runs

    wall.advance(RUNNING_TTL_SECONDS - 1)
    assert _flight(redis, "tick-1").reserve() == (ALREADY_RUNNING, "crashed")
    wall.advance(1)
    assert _flight(redis, "tick-2").reserve() == (QUEUED, "tick-2")


def test_a_lost_message_frees_its_platform_when_the_reservation_expires():
    wall = ManualClock()
    redis = FakeQueueRedis(wall)
    _flight(redis, "lost").reserve()  # message never delivered
    wall.advance(QUEUED_TTL_SECONDS - 1)
    assert _flight(redis, "tick-1").reserve() == (ALREADY_QUEUED, "lost")
    wall.advance(1)
    assert _flight(redis, "tick-2").reserve() == (QUEUED, "tick-2")


# ---------------------------------------------------------------------------
# Beat: RedisAwareScheduler.apply_async
# ---------------------------------------------------------------------------


class _Entry:
    def __init__(self, name="scrape-quintoandar", task="tasks.scrape_listings", args=("quintoandar",)):
        self.name = name
        self.task = task
        self.args = list(args)
        self.kwargs = {}
        self.options = {}


def _scheduler():
    sched = object.__new__(RedisAwareScheduler)
    sched.reserve = MagicMock(side_effect=lambda entry: entry)
    return sched


def test_beat_tick_on_a_free_platform_reserves_and_publishes_with_that_id():
    redis = FakeQueueRedis()
    sched = _scheduler()
    entry = _Entry()
    seen = {}

    def publish(self, entry, producer=None, advance=True, **kwargs):
        seen["options"] = dict(entry.options)
        seen["advance"] = advance
        return "async-result"

    with (
        patch("adapters.queue.redis_scheduler.get_redis", return_value=redis),
        patch.object(PersistentScheduler, "apply_async", publish),
    ):
        result = sched.apply_async(entry, producer="prod", advance=False)

    assert result == "async-result"
    task_id = seen["options"]["task_id"]
    assert redis.get("scrape:single_flight:quintoandar:default:queued:lease") == task_id.encode()
    assert seen["advance"] is False
    assert entry.options == {}  # the id does not leak into the next tick
    sched.reserve.assert_not_called()


def test_beat_tick_keeps_the_entrys_own_options_and_restores_them():
    redis = FakeQueueRedis()
    sched = _scheduler()
    entry = _Entry()
    entry.options = {"priority": 3}
    original = entry.options
    seen = {}

    def publish(self, entry, producer=None, advance=True, **kwargs):
        seen["options"] = dict(entry.options)

    with (
        patch("adapters.queue.redis_scheduler.get_redis", return_value=redis),
        patch.object(PersistentScheduler, "apply_async", publish),
    ):
        sched.apply_async(entry, advance=True)

    assert seen["options"]["priority"] == 3
    assert "task_id" in seen["options"]
    assert entry.options is original
    assert original == {"priority": 3}
    sched.reserve.assert_called_once_with(entry)


@pytest.mark.parametrize(
    ("state", "reason"),
    [("queued", "queued"), ("running", "running")],
)
def test_beat_tick_publishes_nothing_while_a_scrape_is_queued_or_running(state, reason):
    redis = FakeQueueRedis()
    holder = _flight(redis, "holder")
    holder.reserve()
    if state == "running":
        holder.begin()
    sched = _scheduler()
    entry = _Entry()

    with (
        patch("adapters.queue.redis_scheduler.get_redis", return_value=redis),
        patch.object(PersistentScheduler, "apply_async") as super_apply,
        patch("adapters.queue.redis_scheduler.logger") as log,
    ):
        result = sched.apply_async(entry, advance=True)

    assert result is None
    super_apply.assert_not_called()
    sched.reserve.assert_called_once_with(entry)  # the entry still advances
    event, fields = log.info.call_args.args[0], log.info.call_args.kwargs
    assert event == "scrape_enqueue_skipped"
    assert fields["reason"] == reason
    assert fields["holder_task_id"] == "holder"
    assert holder.holder() == {"state": state, "task_id": "holder"}


def test_beat_skip_without_advance_leaves_the_entry_to_tick():
    """``tick`` reserves the entry itself and calls with ``advance=False``."""
    redis = FakeQueueRedis()
    _flight(redis, "holder").reserve()
    sched = _scheduler()
    with (
        patch("adapters.queue.redis_scheduler.get_redis", return_value=redis),
        patch.object(PersistentScheduler, "apply_async") as super_apply,
    ):
        assert sched.apply_async(_Entry(), advance=False) is None
    super_apply.assert_not_called()
    sched.reserve.assert_not_called()


def test_beat_releases_the_reservation_when_the_publish_raises():
    redis = FakeQueueRedis()
    sched = _scheduler()
    entry = _Entry()
    entry.options = {"priority": 3}

    with (
        patch("adapters.queue.redis_scheduler.get_redis", return_value=redis),
        patch.object(PersistentScheduler, "apply_async", side_effect=RuntimeError("broker down")),
    ):
        with pytest.raises(RuntimeError):
            sched.apply_async(entry, advance=False)

    assert redis.get("scrape:single_flight:quintoandar:default:queued:lease") is None
    assert entry.options == {"priority": 3}


def test_beat_does_not_single_flight_other_tasks():
    sched = _scheduler()
    entry = _Entry(name="monitor-queues", task="tasks.monitor_queues", args=())
    with (
        patch("adapters.queue.redis_scheduler.get_redis") as get_redis,
        patch.object(PersistentScheduler, "apply_async", return_value="sent") as super_apply,
    ):
        assert sched.apply_async(entry, producer="p", advance=False) == "sent"
    get_redis.assert_not_called()
    super_apply.assert_called_once_with(entry, producer="p", advance=False)


def test_beat_tick_through_celerys_real_apply_async_sends_the_reserved_id():
    """Celery publishes with ``**entry.options``: the id set there is the id sent."""
    redis = FakeQueueRedis()
    sched = _scheduler()
    sched.app = MagicMock()
    task = MagicMock()
    sched.app.tasks.get.return_value = task
    sched._tasks_since_sync = 0
    sched.should_sync = MagicMock(return_value=False)
    entry = _Entry()

    with patch("adapters.queue.redis_scheduler.get_redis", return_value=redis):
        sched.apply_async(entry, producer="prod", advance=False)

    args, kwargs = task.apply_async.call_args.args, task.apply_async.call_args.kwargs
    assert args == (["quintoandar"], {})
    assert kwargs["producer"] == "prod"
    assert redis.get("scrape:single_flight:quintoandar:default:queued:lease") == kwargs["task_id"].encode()


# ---------------------------------------------------------------------------
# Task: scrape_listings
# ---------------------------------------------------------------------------


def _run_scrape(
    redis,
    *,
    request_id=None,
    items=(),
    fail=None,
    clock=None,
    checkpoint=None,
    hostname=None,
    platform="quintoandar",
    session_error=None,
):
    """Run ``scrape_listings`` with every collaborator but Redis stubbed."""
    from adapters.queue import tasks as tasks_mod

    scraper = MagicMock()
    scraper.proxy_summary = {}
    scraper.fetch_pages.return_value = iter(items)
    scraper.__enter__ = MagicMock(return_value=scraper)
    scraper.__exit__ = MagicMock(return_value=False)
    if fail is not None:
        scraper.start.side_effect = fail
    session_cls = MagicMock()
    if session_error is not None:
        session_cls.side_effect = session_error

    def normalize(_scraper, raw, _platform):
        if clock is not None:
            clock.advance(raw)
        return None, "skipped"

    task = tasks_mod.scrape_listings
    patches = [
        patch.object(tasks_mod, "get_config", return_value=get_config()),
        patch.object(tasks_mod, "SessionLocal", session_cls),
        patch.object(tasks_mod, "get_redis", return_value=redis),
        patch.object(tasks_mod, "CheckpointStore"),
        patch.object(tasks_mod, "ScraperRegistry"),
        patch.object(tasks_mod, "_normalize_scrape_item", side_effect=normalize),
        patch.object(tasks_mod, "_record_scrape_run"),
    ]
    if clock is not None:
        patches.append(patch.object(sf, "_default_monotonic", clock))
    started = [p.start() for p in patches]
    started[3].return_value.get.return_value = {}
    started[4].get.return_value = scraper
    if request_id is not None:
        task.push_request(id=request_id, hostname=hostname)
    try:
        args = (platform,) if checkpoint is None else (platform, checkpoint)
        result = task.run(*args)
    finally:
        if request_id is not None:
            task.pop_request()
        for p in reversed(patches):
            p.stop()
    return result, scraper, session_cls, started[4]


QUEUED_KEY = "scrape:single_flight:quintoandar:default:queued:lease"
RUNNING_KEY = "scrape:single_flight:quintoandar:default:running:lease"


def test_task_that_owns_the_reservation_runs_and_releases_both_leases():
    redis = FakeQueueRedis()
    _flight(redis, "task-1").reserve()
    seen = {}

    from adapters.queue import tasks as tasks_mod

    original = tasks_mod._write_scraper_status

    def spy(r, *args, **kwargs):
        seen.setdefault("queued", r.get(QUEUED_KEY))
        seen.setdefault("running", r.get(RUNNING_KEY))
        return original(r, *args, **kwargs)

    with patch.object(tasks_mod, "_write_scraper_status", spy):
        result, scraper, session_cls, _ = _run_scrape(redis, request_id="task-1")

    assert result is None  # the scrape itself returns nothing, as before
    scraper.start.assert_called_once()
    assert seen == {"queued": None, "running": b"task-1"}
    assert redis.get(QUEUED_KEY) is None
    assert redis.get(RUNNING_KEY) is None
    session_cls.return_value.close.assert_called_once()


def test_task_failure_releases_the_running_lease_before_the_retry():
    redis = FakeQueueRedis()
    _flight(redis, "task-1").reserve()
    with pytest.raises(RuntimeError, match="boom"):
        _run_scrape(redis, request_id="task-1", fail=RuntimeError("boom"))
    assert redis.get(RUNNING_KEY) is None
    assert redis.get(QUEUED_KEY) is None
    # The retry (same id, no reservation) and the next tick can both proceed.
    assert _flight(redis, "task-1").begin() is True


def test_task_skips_when_another_execution_is_in_flight():
    redis = FakeQueueRedis()
    other = _flight(redis, "other-run")
    other.begin()
    writes_before = list(redis.writes)

    result, scraper, session_cls, registry = _run_scrape(redis, request_id="legacy-message")

    assert result == {"status": "skipped", "reason": "already_running", "platform": "quintoandar"}
    registry.get.assert_not_called()
    scraper.start.assert_not_called()
    session_cls.assert_not_called()
    assert redis.get(RUNNING_KEY) == b"other-run"
    # Nothing of the other run was renewed, released or overwritten, and the
    # scraper status key the running scrape owns was not deleted.
    touched = [key for _cmd, key in redis.writes[len(writes_before):]]
    assert RUNNING_KEY not in touched
    assert "pipeline:scraper:quintoandar:status" not in touched


def test_task_skips_a_redelivery_of_its_own_id_and_keeps_the_first_runs_lease():
    redis = FakeQueueRedis()
    _flight(redis, "same-id").begin()
    result, scraper, _session_cls, _ = _run_scrape(redis, request_id="same-id")
    assert result["status"] == "skipped"
    scraper.start.assert_not_called()
    assert redis.get(RUNNING_KEY) == b"same-id"


def test_task_without_a_reservation_takes_the_lease_and_runs():
    redis = FakeQueueRedis()
    result, scraper, _session_cls, _ = _run_scrape(redis, request_id="legacy-message")
    assert result is None
    scraper.start.assert_called_once()
    assert redis.get(RUNNING_KEY) is None


def test_task_without_a_request_id_generates_a_token():
    """``.run()`` and eager calls have no request id; the token is never empty."""
    redis = FakeQueueRedis()
    reserved = _flight(redis, "reserved-by-beat")
    reserved.reserve()
    result, scraper, _session_cls, _ = _run_scrape(redis)
    assert result is None
    scraper.start.assert_called_once()
    assert redis.get(QUEUED_KEY) == b"reserved-by-beat"  # not its reservation to drop
    assert redis.get(RUNNING_KEY) is None


def test_paused_scrapers_release_the_own_reservation_then_retry():
    from adapters.queue import tasks as tasks_mod

    redis = FakeQueueRedis()
    redis.set(tasks_mod.REDIS_KEY_SCRAPERS_PAUSED, "1")
    _flight(redis, "task-1").reserve()

    with patch.object(tasks_mod.scrape_listings, "retry", side_effect=Retry("paused")) as retry:
        with pytest.raises(Retry):
            _run_scrape(redis, request_id="task-1")

    retry.assert_called_once()
    assert retry.call_args.kwargs["countdown"] == 120
    assert redis.get(QUEUED_KEY) is None
    assert redis.get(RUNNING_KEY) is None


def test_paused_scrapers_do_not_release_someone_elses_reservation():
    from adapters.queue import tasks as tasks_mod

    redis = FakeQueueRedis()
    redis.set(tasks_mod.REDIS_KEY_SCRAPERS_PAUSED, "1")
    _flight(redis, "reserved").reserve()
    with patch.object(tasks_mod.scrape_listings, "retry", side_effect=Retry("paused")):
        with pytest.raises(Retry):
            _run_scrape(redis, request_id="legacy-message")
    assert redis.get(QUEUED_KEY) == b"reserved"


def test_task_renews_the_running_lease_from_the_item_loop_at_most_once_a_minute():
    clock = ManualClock()
    redis = FakeQueueRedis(clock)
    # Each item takes 25 s and renews before it is handled: 13 items see the
    # clock at 0, 25, ... 300 s -> renewals at 75, 150, 225 and 300 s.
    _run_scrape(redis, request_id="task-1", items=[25] * 13, clock=clock)
    renewals = [cmd for cmd, key in redis.writes if key == RUNNING_KEY and cmd == "expire"]
    assert len(renewals) == 4


def test_task_warns_once_and_continues_when_the_running_lease_is_lost():
    from adapters.queue import tasks as tasks_mod

    clock = ManualClock()
    redis = FakeQueueRedis(clock)
    with patch.object(tasks_mod, "logger") as log:
        result, scraper, _session_cls, _ = _run_scrape(
            redis,
            request_id="task-1",
            items=[RUNNING_TTL_SECONDS + 1, 120, 120, 120],
            clock=clock,
        )
    assert result is None  # the run continued to the end
    lost = [c for c in log.warning.call_args_list if c.args[0] == "scrape_single_flight_lost"]
    assert len(lost) == 1
    completed = [c for c in log.info.call_args_list if c.args[0] == "scrape_completed"]
    assert completed and completed[0].kwargs["skipped"] == 4


def test_task_scopes_by_the_checkpoint_override():
    redis = FakeQueueRedis()
    _flight(redis, "scheduled").begin()  # the default-scope scrape is running
    result, scraper, _session_cls, _ = _run_scrape(
        redis, request_id="manual", checkpoint={"scrape_type": "rent"}
    )
    assert result is None
    scraper.start.assert_called_once()
    assert redis.get(RUNNING_KEY) == b"scheduled"


# ---------------------------------------------------------------------------
# begin(): no moment with neither lease held
# ---------------------------------------------------------------------------


def test_begin_takes_the_running_lease_before_it_drops_the_reservation():
    """A publisher that looks between the two steps must not see the platform free."""
    redis = FakeQueueRedis()
    flight = _flight(redis, "t1")
    flight.reserve()
    held_at_each_write = []
    real_delete = redis.delete

    def delete(*keys):
        held_at_each_write.append(redis.get(RUNNING_KEY))
        return real_delete(*keys)

    redis.delete = delete
    assert flight.begin() is True
    assert held_at_each_write == [b"t1"]  # the queued lease is dropped while running is held
    assert redis.get(QUEUED_KEY) is None


def test_a_duplicate_that_holds_a_reservation_drops_it_when_it_does_not_begin():
    redis = FakeQueueRedis()
    _flight(redis, "running").begin()
    duplicate = _flight(redis, "duplicate")
    redis.set(QUEUED_KEY, "duplicate", ex=QUEUED_TTL_SECONDS)  # its own reservation
    assert duplicate.begin() is False
    assert redis.get(QUEUED_KEY) is None
    assert redis.get(RUNNING_KEY) == b"running"


# ---------------------------------------------------------------------------
# Worker shutdown: release_running_leases_of
# ---------------------------------------------------------------------------


def test_shutdown_release_frees_only_the_given_owners_running_leases():
    redis = FakeQueueRedis()
    mine_a = _flight(redis, "a", platform="quintoandar", owner="celery@scraper-1")
    mine_b = _flight(redis, "b", platform="olx", scope="abc123", owner="celery@scraper-1")
    other = _flight(redis, "c", platform="zapimoveis", owner="celery@scraper-2")
    for flight in (mine_a, mine_b, other):
        assert flight.begin() is True
    queued = _flight(redis, "d", platform="quintoandar", scope="manual")
    queued.reserve()

    assert release_running_leases_of(redis, "celery@scraper-1") == 2

    assert redis.get(mine_a.running_key) is None
    assert redis.get(mine_b.running_key) is None
    assert redis.get(other.running_key) == b"c"
    assert redis.get(queued.queued_key) == b"d"  # a queued lease is never touched
    assert release_running_leases_of(redis, "celery@scraper-1") == 0


def test_shutdown_release_leaves_a_lease_without_provenance_to_its_ttl():
    redis = FakeQueueRedis()
    flight = _flight(redis, "a", owner="celery@scraper-1")
    flight.begin()
    redis.hashes.pop(f"{flight.running_key}:meta")
    assert release_running_leases_of(redis, "celery@scraper-1") == 0
    assert redis.get(flight.running_key) == b"a"


def test_shutdown_release_is_a_token_compare_and_swap_not_a_delete():
    """Stale provenance of this owner must not drop the lease a successor holds."""
    redis = FakeQueueRedis()
    flight = _flight(redis, "old", owner="celery@scraper-1")
    flight.begin()
    redis.set(flight.running_key, "successor", ex=RUNNING_TTL_SECONDS)  # taken over; meta still says "old"
    assert release_running_leases_of(redis, "celery@scraper-1") == 0
    assert redis.get(flight.running_key) == b"successor"


def test_shutdown_release_with_no_owner_releases_nothing():
    redis = FakeQueueRedis()
    flight = _flight(redis, "a")
    flight.begin()
    assert release_running_leases_of(redis, "") == 0
    assert redis.get(flight.running_key) == b"a"


def test_the_task_records_the_worker_node_as_the_running_lease_owner():
    from adapters.queue import tasks as tasks_mod

    redis = FakeQueueRedis()
    seen = {}
    original = tasks_mod._write_scraper_status

    def spy(r, *args, **kwargs):
        seen.setdefault("meta", r.hgetall(f"{RUNNING_KEY}:meta"))
        return original(r, *args, **kwargs)

    with patch.object(tasks_mod, "_write_scraper_status", spy):
        _run_scrape(redis, request_id="task-1", hostname="celery@scraper-1")
    assert seen["meta"]["owner"] == "celery@scraper-1"
    assert seen["meta"]["token"] == "task-1"


def test_a_redelivered_task_runs_after_the_stopped_workers_lease_was_released():
    """restart.sh: the worker is killed mid-scrape and the broker redelivers the same id."""
    redis = FakeQueueRedis()
    killed = _flight(redis, "task-1", owner="celery@scraper-1")
    killed.begin()  # the run that never reaches its ``finally``

    # Without the shutdown release the redelivery is a duplicate of a run that no longer exists.
    result, scraper, _session_cls, _ = _run_scrape(redis, request_id="task-1", hostname="celery@scraper-1")
    assert result["status"] == "skipped"
    scraper.start.assert_not_called()

    assert release_running_leases_of(redis, "celery@scraper-1") == 1
    result, scraper, _session_cls, _ = _run_scrape(redis, request_id="task-1", hostname="celery@scraper-1")
    assert result is None
    scraper.start.assert_called_once()
    assert redis.get(RUNNING_KEY) is None


def test_the_shutdown_handler_releases_this_nodes_leases_and_logs_the_count():
    from adapters.queue import tasks as tasks_mod

    redis = FakeQueueRedis()
    _flight(redis, "a", owner="celery@scraper-1").begin()
    with (
        patch.object(tasks_mod, "get_redis", return_value=redis),
        patch.object(tasks_mod, "_active_scrape_task_ids", return_value={"a"}),
        patch.object(tasks_mod, "logger") as log,
    ):
        tasks_mod.release_scrape_leases_on_shutdown(sender="celery@scraper-1", sig="SIGTERM", how="Warm")
    assert redis.get(RUNNING_KEY) is None
    log.info.assert_called_once_with(
        "scrape_single_flight_released_on_shutdown", worker="celery@scraper-1", released=1
    )


def test_the_shutdown_handler_is_silent_when_it_released_nothing():
    from adapters.queue import tasks as tasks_mod

    with (
        patch.object(tasks_mod, "get_redis", return_value=FakeQueueRedis()),
        patch.object(tasks_mod, "_active_scrape_task_ids", return_value={"gone"}),
        patch.object(tasks_mod, "logger") as log,
    ):
        tasks_mod.release_scrape_leases_on_shutdown(sender="celery@periodic-1")
    log.info.assert_not_called()
    log.error.assert_not_called()


def test_the_shutdown_handler_swallows_a_redis_error():
    from adapters.queue import tasks as tasks_mod

    redis = MagicMock()
    redis.scan_iter.side_effect = ConnectionError("redis down")
    with (
        patch.object(tasks_mod, "get_redis", return_value=redis),
        patch.object(tasks_mod, "_active_scrape_task_ids", return_value={"a"}),
        patch.object(tasks_mod, "logger") as log,
    ):
        tasks_mod.release_scrape_leases_on_shutdown(sender="celery@scraper-1")  # must not raise
    log.error.assert_called_once_with(
        "scrape_single_flight_shutdown_release_failed", error="redis down"
    )


def test_the_shutdown_handler_is_connected_to_celerys_signal():
    from celery.signals import worker_shutting_down

    from adapters.queue import tasks as tasks_mod

    receivers = [ref() if callable(ref) else ref for _key, ref in worker_shutting_down.receivers]
    assert tasks_mod.release_scrape_leases_on_shutdown in receivers


# ---------------------------------------------------------------------------
# Task: Redis errors and early exits
# ---------------------------------------------------------------------------


def test_a_redis_error_while_renewing_does_not_abort_the_scrape():
    from adapters.queue import tasks as tasks_mod

    clock = ManualClock()
    redis = FakeQueueRedis(clock)
    real_expire = redis.expire

    def expire(key, seconds):
        if key == RUNNING_KEY:
            raise ConnectionError("redis blip")
        return real_expire(key, seconds)

    redis.expire = expire
    with patch.object(tasks_mod, "logger") as log:
        result, _scraper, _session_cls, _ = _run_scrape(
            redis, request_id="task-1", items=[70, 70, 70], clock=clock
        )
    assert result is None
    failed = [c for c in log.warning.call_args_list if c.args[0] == "scrape_single_flight_renew_failed"]
    assert failed and failed[0].kwargs == {"error": "redis blip"}
    completed = [c for c in log.info.call_args_list if c.args[0] == "scrape_completed"]
    assert completed and completed[0].kwargs["skipped"] == 3


def test_an_unknown_platform_hands_the_reservation_back_before_it_raises():
    redis = FakeQueueRedis()
    key = "scrape:single_flight:no-such-platform:default:queued:lease"
    _flight(redis, "task-1", platform="no-such-platform").reserve()
    assert redis.get(key) == b"task-1"
    with pytest.raises(ValueError, match="Unknown platform"):
        _run_scrape(redis, request_id="task-1", platform="no-such-platform")
    assert redis.get(key) is None


def test_paused_scrapers_still_retry_when_the_reservation_cannot_be_released():
    from adapters.queue import tasks as tasks_mod

    redis = FakeQueueRedis()
    redis.set(tasks_mod.REDIS_KEY_SCRAPERS_PAUSED, "1")
    _flight(redis, "task-1").reserve()
    real_get = redis.get

    def get(key):
        if key == QUEUED_KEY:
            raise ConnectionError("redis blip")
        return real_get(key)

    redis.get = get
    with (
        patch.object(tasks_mod.scrape_listings, "retry", side_effect=Retry("paused")) as retry,
        patch.object(tasks_mod, "logger") as log,
    ):
        with pytest.raises(Retry):
            _run_scrape(redis, request_id="task-1")
    assert retry.call_args.kwargs["countdown"] == 120
    log.error.assert_called_once_with("scrape_single_flight_release_failed", error="redis blip")


# ---------------------------------------------------------------------------
# Follow-up review (2026-10-08): handover races, Redis errors in begin(), and
# which leases a stopping worker may release
# ---------------------------------------------------------------------------


def test_reserve_looks_at_the_running_lease_again_once_it_holds_the_reservation():
    """A task that begins between the publisher's read and its SET must not get a duplicate queued."""
    redis = FakeQueueRedis()
    starting = _flight(redis, "starting")
    assert starting.reserve() == (QUEUED, "starting")
    publisher = _flight(redis, "publisher")
    real_get = redis.get
    began = []

    def get(key):
        value = real_get(key)
        if key == RUNNING_KEY and not began:
            # The publisher has just read "nothing running"; the reserved task starts now.
            began.append(starting.begin())
        return value

    redis.get = get
    assert publisher.reserve() == (ALREADY_RUNNING, "starting")
    assert began == [True]
    assert real_get(QUEUED_KEY) is None  # the publisher handed its reservation back
    assert real_get(RUNNING_KEY) == b"starting"


def test_begin_owns_the_running_lease_even_when_dropping_the_reservation_raises():
    redis = FakeQueueRedis()
    flight = _flight(redis, "t1")
    flight.reserve()
    real_delete = redis.delete
    calls = []

    def delete(*keys):
        calls.append(keys)
        if len(calls) == 1:
            raise ConnectionError("redis blip")
        return real_delete(*keys)

    redis.delete = delete
    with pytest.raises(ConnectionError):
        flight.begin()
    assert redis.get(RUNNING_KEY) == b"t1"
    assert flight.finish() is True  # the execution can still give the lease back
    assert redis.get(RUNNING_KEY) is None


def test_task_gives_the_running_lease_back_when_begin_fails_halfway():
    """Otherwise the autoretry (same id) is skipped as a duplicate of itself for two hours."""
    redis = FakeQueueRedis()
    _flight(redis, "task-1").reserve()
    real_delete = redis.delete
    calls = []

    def delete(*keys):
        calls.append(keys)
        if len(calls) == 1:
            raise ConnectionError("redis blip")
        return real_delete(*keys)

    redis.delete = delete
    with pytest.raises(ConnectionError, match="redis blip"):
        _run_scrape(redis, request_id="task-1")
    assert redis.get(RUNNING_KEY) is None
    redis.delete = real_delete
    result, scraper, _session_cls, _ = _run_scrape(redis, request_id="task-1")  # the retry
    assert result is None
    scraper.start.assert_called_once()
    assert redis.get(QUEUED_KEY) is None


def test_task_releases_the_running_lease_when_the_database_session_cannot_be_opened():
    redis = FakeQueueRedis()
    _flight(redis, "task-1").reserve()
    with pytest.raises(RuntimeError, match="database down"):
        _run_scrape(redis, request_id="task-1", session_error=RuntimeError("database down"))
    assert redis.get(RUNNING_KEY) is None
    assert redis.get(QUEUED_KEY) is None


def test_shutdown_release_narrowed_to_task_ids_leaves_the_same_nodes_other_leases():
    """Workers started without ``-n`` share one node name: the task id is the identity."""
    redis = FakeQueueRedis()
    mine = _flight(redis, "mine", platform="quintoandar", owner="celery@host")
    theirs = _flight(redis, "theirs", platform="olx", owner="celery@host")
    assert mine.begin() and theirs.begin()

    assert release_running_leases_of(redis, "celery@host", {"mine"}) == 1

    assert redis.get(mine.running_key) is None
    assert redis.get(theirs.running_key) == b"theirs"


def test_shutdown_release_with_no_task_ids_reads_and_releases_nothing():
    redis = MagicMock()
    assert release_running_leases_of(redis, "celery@host", set()) == 0
    redis.scan_iter.assert_not_called()


def test_the_shutdown_handler_of_a_worker_that_runs_no_scrape_does_not_touch_redis():
    """The periodic and AI workers, and a same-named worker beside the scraper one."""
    from adapters.queue import tasks as tasks_mod

    redis = FakeQueueRedis()
    flight = _flight(redis, "a", owner="celery@host")
    flight.begin()
    with (
        patch.object(tasks_mod, "get_redis") as get_redis,
        patch.object(tasks_mod, "_active_scrape_task_ids", return_value=set()),
    ):
        tasks_mod.release_scrape_leases_on_shutdown(sender="celery@host", sig="SIGTERM", how="Warm")
    get_redis.assert_not_called()
    assert redis.get(flight.running_key) == b"a"


def test_the_shutdown_handler_releases_only_the_scrapes_this_worker_is_executing():
    from adapters.queue import tasks as tasks_mod

    redis = FakeQueueRedis()
    mine = _flight(redis, "mine", platform="quintoandar", owner="celery@host")
    theirs = _flight(redis, "theirs", platform="olx", owner="celery@host")
    assert mine.begin() and theirs.begin()
    with (
        patch.object(tasks_mod, "get_redis", return_value=redis),
        patch.object(tasks_mod, "_active_scrape_task_ids", return_value={"mine"}),
    ):
        tasks_mod.release_scrape_leases_on_shutdown(sender="celery@host")
    assert redis.get(mine.running_key) is None
    assert redis.get(theirs.running_key) == b"theirs"


def test_active_scrape_task_ids_reads_celerys_worker_state():
    from celery.worker import state as worker_state

    from adapters.queue import tasks as tasks_mod

    class _Request:
        def __init__(self, request_id, name):
            self.id = request_id
            self.name = name

    scrape = _Request("scrape-1", "tasks.scrape_listings")
    other = _Request("monitor-1", "tasks.monitor_queues")
    worker_state.active_requests.add(scrape)
    worker_state.active_requests.add(other)
    try:
        assert tasks_mod._active_scrape_task_ids() == {"scrape-1"}
    finally:
        worker_state.active_requests.discard(scrape)
        worker_state.active_requests.discard(other)
    assert tasks_mod._active_scrape_task_ids() == set()
