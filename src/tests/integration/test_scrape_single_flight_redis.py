"""The scrape single-flight against a real Redis (Story 1.18).

Every unit test of the single-flight runs on a fake without ``eval``, so
``BackfillLease`` takes its guarded check-then-act path there. Production has
``eval``: renew and release are the Lua compare-and-swap. This file runs that
path, and the ``SCAN`` + hash read of the shutdown release, for real.

Each test uses its own platform name and deletes its own keys.
"""

from __future__ import annotations

import uuid

import pytest

from adapters.queue.scrape_single_flight import (
    ALREADY_QUEUED,
    ALREADY_RUNNING,
    KEY_PREFIX,
    QUEUED,
    QUEUED_TTL_SECONDS,
    RUNNING_TTL_SECONDS,
    ScrapeSingleFlight,
    release_running_leases_of,
)
from tests.env_helpers import get_redis_url
from tests.redis_isolation import assert_wipe_safe_redis_url

pytestmark = pytest.mark.integration

_PLATFORM_PREFIX = "test-s118"


@pytest.fixture
def redis_client():
    redis_url = get_redis_url()
    if not redis_url:
        pytest.skip("REDIS_URL not set — run via scripts/agent/validate.py --tier backend")
    assert_wipe_safe_redis_url(redis_url)
    import redis as redis_lib

    client = redis_lib.Redis.from_url(redis_url)
    for key in client.scan_iter(f"{KEY_PREFIX}:{_PLATFORM_PREFIX}-*"):
        client.delete(key)
    yield client
    for key in client.scan_iter(f"{KEY_PREFIX}:{_PLATFORM_PREFIX}-*"):
        client.delete(key)
    client.close()


@pytest.fixture
def platform():
    """A platform name no other test, and no real scrape, uses."""
    return f"{_PLATFORM_PREFIX}-{uuid.uuid4().hex[:12]}"


def _flight(client, platform, task_id, *, owner=None, monotonic=None):
    return ScrapeSingleFlight(
        client,
        platform=platform,
        scope="default",
        task_id=task_id,
        owner=owner,
        monotonic=monotonic,
    )


def test_a_duplicate_reserve_is_refused_with_the_holder_id(redis_client, platform):
    first = _flight(redis_client, platform, "first")
    assert first.reserve() == (QUEUED, "first")
    assert 0 < redis_client.ttl(first.queued_key) <= QUEUED_TTL_SECONDS

    assert _flight(redis_client, platform, "second").reserve() == (ALREADY_QUEUED, "first")
    assert redis_client.get(first.queued_key) == b"first"


def test_begin_hands_the_reservation_over_to_the_running_lease(redis_client, platform):
    flight = _flight(redis_client, platform, "first")
    flight.reserve()

    assert flight.begin() is True

    assert redis_client.exists(flight.queued_key) == 0
    assert redis_client.get(flight.running_key) == b"first"
    assert 0 < redis_client.ttl(flight.running_key) <= RUNNING_TTL_SECONDS
    assert _flight(redis_client, platform, "tick").reserve() == (ALREADY_RUNNING, "first")


def test_a_second_flight_with_another_id_does_not_begin_and_leaves_the_keys(redis_client, platform):
    first = _flight(redis_client, platform, "first")
    first.reserve()
    first.begin()
    reserved = _flight(redis_client, platform, "reserved")
    redis_client.set(reserved.queued_key, "reserved", ex=QUEUED_TTL_SECONDS)

    duplicate = _flight(redis_client, platform, "duplicate")
    assert duplicate.begin() is False
    assert duplicate.renew() is None
    assert duplicate.finish() is False

    assert redis_client.get(first.running_key) == b"first"
    assert redis_client.get(reserved.queued_key) == b"reserved"  # not the duplicate's to drop


def test_a_redelivery_of_the_same_id_does_not_begin_or_release(redis_client, platform):
    first = _flight(redis_client, platform, "same-id")
    first.begin()
    redelivered = _flight(redis_client, platform, "same-id")
    assert redelivered.begin() is False
    assert redelivered.finish() is False
    assert redis_client.get(first.running_key) == b"same-id"


def test_renew_extends_the_ttl(redis_client, platform):
    clock = {"now": 0.0}
    flight = _flight(redis_client, platform, "first", monotonic=lambda: clock["now"])
    flight.begin()
    redis_client.expire(flight.running_key, 100)
    assert redis_client.ttl(flight.running_key) <= 100

    assert flight.renew() is None  # throttled: under a minute since begin
    assert redis_client.ttl(flight.running_key) <= 100

    clock["now"] = 61.0
    assert flight.renew() is True
    assert redis_client.ttl(flight.running_key) > 100


def test_renew_reports_a_lease_that_was_taken_over(redis_client, platform):
    clock = {"now": 0.0}
    flight = _flight(redis_client, platform, "first", monotonic=lambda: clock["now"])
    flight.begin()
    redis_client.set(flight.running_key, "successor", ex=RUNNING_TTL_SECONDS)

    clock["now"] = 61.0
    assert flight.renew() is False
    assert flight.finish() is False
    assert redis_client.get(flight.running_key) == b"successor"


def test_finish_removes_the_running_key(redis_client, platform):
    flight = _flight(redis_client, platform, "first")
    flight.begin()
    assert flight.finish() is True
    assert redis_client.exists(flight.running_key) == 0
    assert _flight(redis_client, platform, "next").reserve() == (QUEUED, "next")


def test_cancel_reservation_only_for_the_holder(redis_client, platform):
    first = _flight(redis_client, platform, "first")
    first.reserve()
    assert _flight(redis_client, platform, "other").cancel_reservation() is False
    assert redis_client.get(first.queued_key) == b"first"
    assert first.cancel_reservation() is True
    assert redis_client.exists(first.queued_key) == 0


def test_release_running_leases_of_releases_by_owner(redis_client, platform):
    owner = f"celery@{platform}-a"
    other_owner = f"celery@{platform}-b"
    mine = _flight(redis_client, f"{platform}-1", "mine", owner=owner)
    theirs = _flight(redis_client, f"{platform}-2", "theirs", owner=other_owner)
    queued = _flight(redis_client, f"{platform}-3", "queued")
    assert mine.begin() is True
    assert theirs.begin() is True
    assert queued.reserve() == (QUEUED, "queued")

    assert release_running_leases_of(redis_client, owner) == 1

    assert redis_client.exists(mine.running_key) == 0
    assert redis_client.get(theirs.running_key) == b"theirs"
    assert redis_client.get(queued.queued_key) == b"queued"
    assert release_running_leases_of(redis_client, owner) == 0
    # The same task id can run again at once: the redelivery after a restart.
    assert _flight(redis_client, f"{platform}-1", "mine", owner=owner).begin() is True


def test_release_running_leases_of_leaves_a_lease_a_successor_took(redis_client, platform):
    owner = f"celery@{platform}-a"
    flight = _flight(redis_client, platform, "old", owner=owner)
    flight.begin()
    redis_client.set(flight.running_key, "successor", ex=RUNNING_TTL_SECONDS)  # meta still names "old"
    assert release_running_leases_of(redis_client, owner) == 0
    assert redis_client.get(flight.running_key) == b"successor"
