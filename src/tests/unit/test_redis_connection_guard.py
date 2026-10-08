"""The suite cannot reach a Redis or a Celery broker it was not given (Story 1.18).

Regression for 2026-10-08: a raw ``pytest`` of the contract suite published a
real ``tasks.scrape_listings`` message and wrote a lease key to the primary
Redis, because the config default ``redis://localhost:6379/0`` is the primary
broker on a development host. ``tests/conftest.py`` installs the guard tested
here for every session.
"""

from __future__ import annotations

import asyncio

import pytest
import redis
import redis.asyncio
from redis.exceptions import ConnectionError as RedisConnectionError

import tests.conftest as suite_conftest
from tests.redis_isolation import (
    connection_target,
    install_redis_connection_guard,
    is_connection_allowed,
    isolated_redis_endpoint,
)

pytestmark = pytest.mark.unit

PRIMARY_URL = "redis://localhost:6379/0"
BLOCKED = "Test session blocked a Redis connection"


# ---------------------------------------------------------------------------
# Which endpoint a session may reach
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", [None, "", PRIMARY_URL, "redis://localhost:6379", "redis://redis:6379/0"])
def test_no_url_or_logical_db_zero_means_no_redis_is_reachable(url, monkeypatch):
    monkeypatch.delenv("IMOVEIS_ALLOW_PRIMARY_REDIS_WIPE", raising=False)
    assert isolated_redis_endpoint(url) is None


def test_the_gates_url_names_the_one_reachable_endpoint(monkeypatch):
    monkeypatch.delenv("IMOVEIS_ALLOW_PRIMARY_REDIS_WIPE", raising=False)
    assert isolated_redis_endpoint("redis://127.0.0.1:55123/15") == ("127.0.0.1", 55123, 15)
    # localhost and 127.0.0.1 are one host; a password is not part of the endpoint.
    assert isolated_redis_endpoint("redis://:pw@localhost:55123/15") == ("127.0.0.1", 55123, 15)


def test_a_non_redis_url_names_no_endpoint(monkeypatch):
    monkeypatch.delenv("IMOVEIS_ALLOW_PRIMARY_REDIS_WIPE", raising=False)
    assert isolated_redis_endpoint("memory://") is None
    assert isolated_redis_endpoint("unix:///tmp/redis.sock?db=15") is None


def test_only_the_exact_endpoint_is_allowed_logical_db_included():
    allowed = ("127.0.0.1", 55123, 15)
    assert is_connection_allowed(("127.0.0.1", 55123, 15), allowed) is True
    assert is_connection_allowed(("127.0.0.1", 55123, 0), allowed) is False  # the broker DB of that server
    assert is_connection_allowed(("127.0.0.1", 6379, 15), allowed) is False
    assert is_connection_allowed(("redis", 55123, 15), allowed) is False
    assert is_connection_allowed(None, allowed) is False  # a unix socket
    assert is_connection_allowed(("127.0.0.1", 55123, 15), None) is False


def test_connection_target_reads_host_port_and_db():
    connection = redis.Redis.from_url("redis://localhost:6390/7").connection_pool.make_connection()
    assert connection_target(connection) == ("127.0.0.1", 6390, 7)


# ---------------------------------------------------------------------------
# The guard as this session runs it
# ---------------------------------------------------------------------------


def test_the_suite_installed_the_guard_and_this_session_cannot_reach_db_zero():
    endpoint = suite_conftest.ISOLATED_REDIS_ENDPOINT
    assert endpoint is None or endpoint[2] != 0
    # Idempotent: a second install wraps nothing twice and keeps the endpoint.
    assert install_redis_connection_guard() == endpoint


# Read-only commands only below: if the guard were broken, these tests must fail
# without having written anything to whatever listens on the default URL.


def test_the_default_redis_url_is_refused_before_a_socket_is_opened():
    client = redis.Redis.from_url(PRIMARY_URL, socket_connect_timeout=1)
    with pytest.raises(RedisConnectionError, match=BLOCKED):
        client.ping()
    with pytest.raises(RedisConnectionError, match=BLOCKED):
        client.llen("scrapers")


def test_a_pipeline_and_a_pubsub_are_refused_too():
    client = redis.Redis.from_url(PRIMARY_URL, socket_connect_timeout=1)
    with pytest.raises(RedisConnectionError, match=BLOCKED):
        client.pipeline().get("guard-probe").llen("scrapers").execute()
    with pytest.raises(RedisConnectionError, match=BLOCKED):
        client.pubsub().subscribe("guard-probe")


def test_the_async_client_is_refused():
    async def ping():
        client = redis.asyncio.Redis.from_url(PRIMARY_URL, socket_connect_timeout=1)
        try:
            await client.ping()
        finally:
            await client.aclose()

    with pytest.raises(RedisConnectionError, match=BLOCKED):
        asyncio.run(ping())


def test_a_celery_publish_to_the_default_broker_is_refused():
    """What the incident did: ``apply_async`` on an app whose broker is the config default.

    The port is one nothing listens on, so a broken guard fails this test with a
    refused connection instead of publishing anywhere.
    """
    from celery import Celery

    app = Celery("guard-probe", broker="redis://127.0.0.1:1/0")
    app.conf.broker_connection_retry_on_startup = False
    app.conf.broker_transport_options = {"socket_connect_timeout": 1}
    with pytest.raises(Exception) as excinfo:
        app.send_task("tasks.scrape_listings", args=["olx"], retry=False)
    chain = []
    exc: BaseException | None = excinfo.value
    while exc is not None:
        chain.append(str(exc))
        exc = exc.__cause__ or exc.__context__
    assert any(BLOCKED in text for text in chain), chain


def test_the_app_redis_client_is_refused_without_an_isolated_url():
    """``infra.redis_client.get_redis`` is what leases, pacers and the scheduler use."""
    if suite_conftest.ISOLATED_REDIS_ENDPOINT is not None:
        pytest.skip("this session was given an isolated Redis by the gate")
    from infra.redis_client import get_redis

    with pytest.raises(RedisConnectionError, match=BLOCKED):
        get_redis().ping()
