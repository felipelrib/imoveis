"""Unit tests for Redis logical-DB isolation helpers (BIN-117)."""

from __future__ import annotations

import pytest

from tests.redis_isolation import (
    DEFAULT_TEST_REDIS_DB_INDEX,
    assert_wipe_safe_redis_url,
    is_wipe_safe_redis_url,
    redis_db_index_from_url,
    with_redis_db,
)


@pytest.mark.unit
class TestRedisIsolation:
    def test_parses_db_index(self):
        assert redis_db_index_from_url("redis://localhost:6379/15") == 15
        assert redis_db_index_from_url("redis://:secret@host:6380/2") == 2

    def test_missing_or_empty_path_is_db_zero(self):
        assert redis_db_index_from_url("redis://localhost:6379") == 0
        assert redis_db_index_from_url("redis://localhost:6379/") == 0

    def test_primary_db_zero_not_wipe_safe(self):
        url = "redis://localhost:6379/0"
        assert is_wipe_safe_redis_url(url, allow_primary_wipe=False) is False
        with pytest.raises(RuntimeError, match="Refusing to flush"):
            assert_wipe_safe_redis_url(url)

    def test_test_db_index_is_wipe_safe(self):
        url = f"redis://localhost:6379/{DEFAULT_TEST_REDIS_DB_INDEX}"
        assert is_wipe_safe_redis_url(url, allow_primary_wipe=False) is True
        assert_wipe_safe_redis_url(url)

    def test_escape_hatch_allows_primary(self):
        url = "redis://localhost:6379/0"
        assert is_wipe_safe_redis_url(url, allow_primary_wipe=True) is True

    def test_missing_url_not_wipe_safe(self):
        assert is_wipe_safe_redis_url(None, allow_primary_wipe=False) is False
        with pytest.raises(RuntimeError, match="Refusing to flush"):
            assert_wipe_safe_redis_url(None)

    def test_with_redis_db_rewrites_path(self):
        assert with_redis_db("redis://localhost:6379/0", 15) == "redis://localhost:6379/15"
        assert (
            with_redis_db("redis://:pw@host:6380/0", 15) == "redis://:pw@host:6380/15"
        )
        assert with_redis_db("redis://localhost:6379", 15) == "redis://localhost:6379/15"
