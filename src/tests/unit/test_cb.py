"""Unit tests for CircuitBreaker and RedisCircuitBreaker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from adapters.scrapers.redis_circuit_breaker import RedisCircuitBreaker

# ---------------------------------------------------------------------------
# RedisCircuitBreaker tests (unit — Redis is mocked)
# ---------------------------------------------------------------------------


def _make_redis_breaker(failure_threshold=3, cooldown_seconds=60):
    """Build a RedisCircuitBreaker with a dict-backed fake Redis client."""
    store = {}

    def fake_get(key):
        return store.get(key)

    def fake_setex(key, ttl, value):
        store[key] = value

    mock_redis = MagicMock()
    mock_redis.get = fake_get
    mock_redis.setex = fake_setex

    with patch("infra.redis_client.get_redis", return_value=mock_redis):
        cb = RedisCircuitBreaker(
            platform="test_platform",
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
        )
    cb.redis_client = mock_redis
    return cb, mock_redis


def test_redis_cb_starts_closed():
    cb, _ = _make_redis_breaker()
    assert not cb.is_open()


def test_redis_cb_opens_after_threshold():
    cb, mock_redis = _make_redis_breaker(failure_threshold=3)
    cb.record_failure()
    cb.record_failure()
    assert not cb.is_open()
    cb.record_failure()  # 3rd failure — trip
    assert cb.is_open()


def test_redis_cb_resets_on_success():
    cb, mock_redis = _make_redis_breaker(failure_threshold=2)
    cb.record_failure()
    cb.record_failure()
    assert cb.is_open()
    cb.record_success()
    assert not cb.is_open()


def test_redis_cb_stays_open_during_cooldown():
    cb, _ = _make_redis_breaker(failure_threshold=1, cooldown_seconds=600)
    cb.record_failure()
    assert cb.is_open()


def test_redis_cb_failure_count_resets_on_success():
    cb, _ = _make_redis_breaker(failure_threshold=3, cooldown_seconds=60)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    cb.record_failure()
    assert not cb.is_open()  # count was reset
