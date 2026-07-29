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
