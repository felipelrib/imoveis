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
        base, open_key = keys
        threshold = int(args[0])
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


# ---------------------------------------------------------------------------
# BIN-156: sustained Cloudflare 403 streaks must open the same shared circuit
# ---------------------------------------------------------------------------


def test_redis_cb_sustained_403_reason_opens_breaker():
    """A streak of same-reason (e.g. cloudflare_403) failures trips is_open()."""
    cb, _ = _make_redis_breaker(failure_threshold=5)
    for _ in range(4):
        opened = cb.record_failure(reason="cloudflare_403")
        assert opened is False
    assert not cb.is_open()

    opened = cb.record_failure(reason="cloudflare_403")  # 5th — trip
    assert opened is True
    assert cb.is_open()


def test_redis_cb_403_reason_has_independent_counter_from_default():
    """403 failures and 5xx/429 failures accumulate in separate buckets."""
    cb, _ = _make_redis_breaker(failure_threshold=5)
    cb.record_failure()  # default (5xx/429) reason, count=1
    cb.record_failure()  # count=2
    cb.record_failure(reason="cloudflare_403")  # separate bucket, count=1
    cb.record_failure(reason="cloudflare_403")  # count=2
    assert not cb.is_open()  # neither bucket reached threshold=5 alone


def test_redis_cb_403_reason_supports_independent_threshold_and_cooldown():
    """A reason can use its own threshold/cooldown, distinct from the default."""
    cb, _ = _make_redis_breaker(failure_threshold=5, cooldown_seconds=120)
    cb.record_failure(reason="cloudflare_403", threshold=2, cooldown=30)
    opened = cb.record_failure(reason="cloudflare_403", threshold=2, cooldown=30)
    assert opened is True
    assert cb.is_open()


def test_redis_cb_403_reason_resets_on_success():
    cb, _ = _make_redis_breaker(failure_threshold=3)
    cb.record_failure(reason="cloudflare_403")
    cb.record_failure(reason="cloudflare_403")
    cb.record_success()
    cb.record_failure(reason="cloudflare_403")
    assert not cb.is_open()  # 403 counter was reset by record_success too
