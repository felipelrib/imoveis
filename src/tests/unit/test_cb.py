"""Unit tests for CircuitBreaker."""
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


def test_circuit_stays_open_during_cooldown():
    cb = CircuitBreaker(platform_name="test", failure_threshold=1, cooldown_seconds=600)
    cb.record_failure()
    assert cb.is_open()


def test_circuit_resets_after_cooldown():
    cb = CircuitBreaker(platform_name="test", failure_threshold=1, cooldown_seconds=0)
    cb.record_failure()
    # With 0-second cooldown, the circuit should reset immediately
    assert not cb.is_open()


def test_failure_count_resets_on_success():
    cb = CircuitBreaker(platform_name="test", failure_threshold=3, cooldown_seconds=60)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    cb.record_failure()
    assert not cb.is_open()  # count was reset