"""Unit tests for CircuitBreaker and RedisCircuitBreaker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from adapters.scrapers.redis_circuit_breaker import RedisCircuitBreaker

# ---------------------------------------------------------------------------
# RedisCircuitBreaker tests (unit — Redis is mocked)
# ---------------------------------------------------------------------------


def _make_redis_breaker(failure_threshold=3, cooldown_seconds=60):
    """Build a RedisCircuitBreaker with a dict-backed fake Redis client."""
    store: dict[str, object] = {}

    def fake_exists(key):
        return 1 if key in store else 0

    def fake_delete(*keys):
        for key in keys:
            store.pop(key, None)

    def fake_script(*, keys, args):
        """Mirror RECORD_FAILURE_SCRIPT against the in-memory store."""
        base = keys[0]
        threshold = int(args[0])
        open_key = f"{base}:open"
        fail_key = f"{base}:failures"
        if open_key in store:
            return 0
        count = int(store.get(fail_key, 0)) + 1
        store[fail_key] = count
        if count >= threshold:
            store[open_key] = b"1"
            return 1
        return 0

    mock_redis = MagicMock()
    mock_redis.exists = fake_exists
    mock_redis.delete = fake_delete
    mock_redis.register_script = MagicMock(return_value=fake_script)

    with patch("infra.redis_client.get_redis", return_value=mock_redis):
        cb = RedisCircuitBreaker(
            platform="test_platform",
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
        )
    cb.redis_client = mock_redis
    cb._record_failure_script = fake_script
    return cb, mock_redis


def test_redis_cb_starts_closed():
    cb, _ = _make_redis_breaker()
    assert not cb.is_open()


def test_redis_cb_opens_after_threshold():
    cb, _ = _make_redis_breaker(failure_threshold=3)
    cb.record_failure()
    cb.record_failure()
    assert not cb.is_open()
    cb.record_failure()  # 3rd failure — trip
    assert cb.is_open()


def test_redis_cb_resets_on_success():
    cb, _ = _make_redis_breaker(failure_threshold=2)
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
