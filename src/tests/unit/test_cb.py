"""Unit tests for CircuitBreaker — updated for new platform_name and on_trip callback."""
from __future__ import annotations

import pytest

from adapters.scrapers.circuit_breaker import CircuitBreaker


def test_circuit_starts_closed():
    cb = CircuitBreaker(platform_name="test", failure_threshold=3, cooldown_seconds=60)
    assert not cb.is_open()


def test_circuit_opens_after_threshold():
    cb = CircuitBreaker(platform_name="test", failure_threshold=3, cooldown_seconds=60)
    cb.record_failure()
    cb.record_failure()
    assert not cb.is_open()
    cb.record_failure()  # 3rd failure — trip
    assert cb.is_open()


def test_circuit_resets_on_success():
    cb = CircuitBreaker(platform_name="test", failure_threshold=2, cooldown_seconds=60)
    cb.record_failure()
    cb.record_failure()
    assert cb.is_open()
    cb.record_success()
    assert not cb.is_open()


def test_on_trip_callback_fires():
    fired = []

    def on_trip(platform, failures, cooldown):
        fired.append((platform, failures, cooldown))

    cb = CircuitBreaker(
        platform_name="quintoandar",
        failure_threshold=2,
        cooldown_seconds=300,
        on_trip=on_trip,
    )
    cb.record_failure()
    cb.record_failure()  # trips here

    assert len(fired) == 1
    assert fired[0] == ("quintoandar", 2, 300)


def test_on_trip_callback_not_fired_before_threshold():
    fired = []
    cb = CircuitBreaker(
        platform_name="test",
        failure_threshold=5,
        cooldown_seconds=60,
        on_trip=lambda p, f, c: fired.append(True),
    )
    cb.record_failure()
    cb.record_failure()
    assert len(fired) == 0


def test_time_left_positive_when_open():
    cb = CircuitBreaker(platform_name="test", failure_threshold=1, cooldown_seconds=600)
    cb.record_failure()
    assert cb.time_left() > 0
