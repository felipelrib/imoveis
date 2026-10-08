"""Helpers to keep flushdb off the Compose Celery Redis DB (BIN-117)."""

from __future__ import annotations

import os
from urllib.parse import urlparse, urlunparse

# Compose API / Celery broker use logical DB 0. Integration flushdb fixtures
# must not target it unless IMOVEIS_ALLOW_PRIMARY_REDIS_WIPE=1 (emergency only).
PRIMARY_REDIS_DB_INDEX = 0
DEFAULT_TEST_REDIS_DB_INDEX = 15


def redis_db_index_from_url(url: str) -> int:
    """Return the Redis logical DB index from a redis:// URL path."""
    parsed = urlparse(url)
    raw = (parsed.path or "").lstrip("/")
    if not raw:
        return 0
    # Drop query fragments if path somehow includes them.
    raw = raw.split("?", 1)[0]
    try:
        return int(raw)
    except ValueError:
        return 0


def with_redis_db(url: str, db: int) -> str:
    """Return *url* with the path rewritten to ``/{db}``."""
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=f"/{int(db)}"))


def is_wipe_safe_redis_url(
    url: str | None,
    *,
    allow_primary_wipe: bool | None = None,
) -> bool:
    """True when flushdb on this URL is allowed."""
    if not url:
        return False
    if allow_primary_wipe is None:
        # Intentional exception (BIN-142): this destructive-action guard reads
        # the env var directly rather than via tests.env_helpers — it is a
        # safety gate, not shared fixture setup, and should stay local/obvious
        # at the call site.
        allow_primary_wipe = os.environ.get("IMOVEIS_ALLOW_PRIMARY_REDIS_WIPE", "") == "1"
    if allow_primary_wipe:
        return True
    return redis_db_index_from_url(url) != PRIMARY_REDIS_DB_INDEX


def assert_wipe_safe_redis_url(url: str | None) -> None:
    """Raise RuntimeError if *url* points at Compose Redis DB 0."""
    if is_wipe_safe_redis_url(url):
        return
    index = redis_db_index_from_url(url) if url else "(missing)"
    raise RuntimeError(
        f"Refusing to flush Redis DB {index!r}: integration tests must use "
        f"logical DB {DEFAULT_TEST_REDIS_DB_INDEX} (set via validate.sh / "
        "REDIS_TEST_DB). Override only with IMOVEIS_ALLOW_PRIMARY_REDIS_WIPE=1."
    )


# ---------------------------------------------------------------------------
# Connection guard (Story 1.18)
# ---------------------------------------------------------------------------
#
# The flushdb guard above protects one destructive call. This one protects
# every other: the config default is ``redis://localhost:6379/0``, which on a
# development host is the primary stack's Redis, and it is the Celery broker as
# well. A test that reaches ``apply_async``, the rate limiter or a lease without
# a mock therefore writes to the primary (2026-10-08: a raw run of the contract
# suite published one real ``tasks.scrape_listings`` message there).
#
# ``install_redis_connection_guard`` is called once from ``tests/conftest.py``.
# From then on redis-py, and so Kombu and the limiter, can only open a
# connection to the Redis named by a wipe-safe ``REDIS_URL`` (logical DB other
# than 0, which is what ``scripts/agent/validate.py`` exports for its ephemeral
# stack). Without one (a raw ``pytest``, or the gate's unit tier) no Redis is
# reachable at all and the attempt fails at once, before a socket is opened.

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})
_GUARD_ATTR = "_imoveis_isolation_guard"


def _normalize_host(host: object) -> str:
    text = str(host or "").strip().lower()
    return "127.0.0.1" if text in _LOOPBACK_HOSTS else text


def isolated_redis_endpoint(url: str | None) -> tuple[str, int, int] | None:
    """``(host, port, db)`` a test session may connect to, or None for "no Redis".

    Only a wipe-safe URL names one: unset, empty, unparseable or logical DB 0
    (without the emergency override) all mean that nothing is reachable.
    """
    if not url or not is_wipe_safe_redis_url(url):
        return None
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        port = parsed.port or 6379
    except ValueError:
        return None
    if parsed.scheme not in ("redis", "rediss") or not host:
        return None
    return _normalize_host(host), int(port), redis_db_index_from_url(url)


def connection_target(connection: object) -> tuple[str, int, int] | None:
    """``(host, port, db)`` of a redis-py connection; None for a unix socket."""
    host = getattr(connection, "host", None)
    if not host:
        return None
    try:
        port = int(getattr(connection, "port", 6379) or 6379)
        db = int(getattr(connection, "db", 0) or 0)
    except (TypeError, ValueError):
        return None
    return _normalize_host(host), port, db


def is_connection_allowed(
    target: tuple[str, int, int] | None,
    allowed: tuple[str, int, int] | None,
) -> bool:
    """True only for the exact isolated endpoint, logical DB included."""
    return allowed is not None and target is not None and target == allowed


def _refusal(connection: object, allowed: tuple[str, int, int] | None) -> str:
    target = connection_target(connection)
    where = "a unix socket" if target is None else f"{target[0]}:{target[1]}/{target[2]}"
    only = (
        "no Redis at all (REDIS_URL is unset or names logical DB 0)"
        if allowed is None
        else f"{allowed[0]}:{allowed[1]}/{allowed[2]}"
    )
    return (
        f"Test session blocked a Redis connection to {where}: it may reach {only}. "
        "Mock the Redis client and the Celery publish in the test, or run it through "
        "scripts/agent/validate.py, which exports the ephemeral test stack's REDIS_URL."
    )


def install_redis_connection_guard(url: str | None = None) -> tuple[str, int, int] | None:
    """Make redis-py refuse every connection but the isolated test endpoint.

    Idempotent. The endpoint is fixed here, at session start: a test that later
    changes ``REDIS_URL`` does not widen what the session may reach. Returns
    the allowed endpoint (None when nothing is reachable).
    """
    import redis.asyncio.connection as redis_async_connection
    import redis.connection as redis_connection
    from redis.exceptions import ConnectionError as RedisConnectionError

    if url is None:
        url = os.environ.get("REDIS_URL")
    allowed = isolated_redis_endpoint(url)

    class RedisIsolationError(RedisConnectionError):
        """Raised instead of opening a socket to a Redis the session may not reach."""

    def check(connection: object) -> None:
        if not is_connection_allowed(connection_target(connection), allowed):
            raise RedisIsolationError(_refusal(connection, allowed))

    # ``connect_check_health`` is the one method every path to a socket goes
    # through (``connect`` and the lazy connect inside ``send_packed_command``),
    # for TCP, TLS and unix-socket connections alike.
    sync_cls = redis_connection.AbstractConnection
    if not getattr(sync_cls.connect_check_health, _GUARD_ATTR, False):
        original_connect = sync_cls.connect_check_health

        def guarded_connect(self, *args, **kwargs):
            if getattr(self, "_sock", None) is None:
                check(self)
            return original_connect(self, *args, **kwargs)

        setattr(guarded_connect, _GUARD_ATTR, True)
        sync_cls.connect_check_health = guarded_connect

    async_cls = redis_async_connection.AbstractConnection
    if not getattr(async_cls.connect_check_health, _GUARD_ATTR, False):
        original_async_connect = async_cls.connect_check_health

        async def guarded_async_connect(self, *args, **kwargs):
            if not self.is_connected:
                check(self)
            return await original_async_connect(self, *args, **kwargs)

        setattr(guarded_async_connect, _GUARD_ATTR, True)
        async_cls.connect_check_health = guarded_async_connect

    return allowed
