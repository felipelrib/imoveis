"""Centralized Redis client factory.

All modules that need Redis import from here instead of creating ad-hoc connections.

Usage:
    from infra.redis_client import get_redis
    r = get_redis()
"""

from __future__ import annotations

from typing import Optional

import redis

from infra.config import get_config

_cached_client: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    """Return a shared Redis client using the configured URL."""
    global _cached_client
    if _cached_client is None:
        cfg = get_config()
        _cached_client = redis.Redis.from_url(cfg.redis.url, decode_responses=False)
    return _cached_client


def verify_redis_connection() -> None:
    """Verify Redis connection and log startup error if it fails."""
    try:
        r = get_redis()
        r.ping()
    except Exception as exc:
        from infra.logging import get_logger
        logger = get_logger(__name__)
        logger.error("redis_startup_health_check_failed", error=str(exc))
        raise


def reset_redis() -> None:
    """Close and discard the cached Redis client (useful for testing)."""
    global _cached_client
    if _cached_client is not None:
        try:
            _cached_client.close()
        except Exception:
            pass
        _cached_client = None
