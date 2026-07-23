"""Unit tests for infra.redis_client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import infra.redis_client as redis_client


@pytest.fixture(autouse=True)
def _reset_client():
    redis_client.reset_redis()
    yield
    redis_client.reset_redis()


@pytest.mark.unit
class TestRedisClient:
    def test_get_redis_caches_client(self):
        fake = MagicMock()
        with patch("infra.redis_client.redis.Redis.from_url", return_value=fake) as from_url:
            with patch("infra.redis_client.get_config") as get_config:
                get_config.return_value.redis.url = "redis://localhost:6379/0"
                a = redis_client.get_redis()
                b = redis_client.get_redis()
        assert a is b is fake
        from_url.assert_called_once()

    def test_verify_redis_connection_ok(self):
        fake = MagicMock()
        with patch("infra.redis_client.get_redis", return_value=fake):
            redis_client.verify_redis_connection()
        fake.ping.assert_called_once()

    def test_verify_redis_connection_raises(self):
        fake = MagicMock()
        fake.ping.side_effect = RuntimeError("down")
        with patch("infra.redis_client.get_redis", return_value=fake):
            with pytest.raises(RuntimeError, match="down"):
                redis_client.verify_redis_connection()

    def test_reset_closes_and_clears(self):
        fake = MagicMock()
        redis_client._cached_client = fake
        redis_client.reset_redis()
        fake.close.assert_called_once()
        assert redis_client._cached_client is None

    def test_reset_ignores_close_errors(self):
        fake = MagicMock()
        fake.close.side_effect = RuntimeError("close failed")
        redis_client._cached_client = fake
        redis_client.reset_redis()
        assert redis_client._cached_client is None
