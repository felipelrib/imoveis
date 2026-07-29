"""Unit tests for ``RedisAwareScheduler`` (BIN-129).

Regression coverage for a live-production crash: the scheduler used a bare
stdlib ``logging.getLogger`` and then called ``logger.info(...)`` /
``logger.warning(...)`` with structured kwargs (``task=``, ``reason=``,
``override=``). Stdlib ``Logger`` methods do not accept arbitrary kwargs, so
any time an operator set/changed a ``scheduler:interval:<platform>`` Redis
override, Celery Beat raised ``TypeError: Logger._log() got an unexpected
keyword argument`` inside ``apply_entry`` — which was only guarded against
``ValueError``, so it propagated and could crash/spam beat, silently halting
all scheduled scraping/AI jobs.

These tests exercise every branch of the Redis-override path directly
against the real (now structlog-backed) logger calls, so a regression to the
stdlib logger pattern would fail loudly again.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from celery.beat import PersistentScheduler

from adapters.queue.redis_scheduler import RedisAwareScheduler


def _make_scheduler() -> RedisAwareScheduler:
    """Build a RedisAwareScheduler without running Celery's heavyweight init."""
    return object.__new__(RedisAwareScheduler)


def _entry(name: str, run_every_seconds: float = 600.0) -> MagicMock:
    entry = MagicMock()
    entry.name = name
    entry.schedule.run_every.total_seconds.return_value = run_every_seconds
    return entry


@pytest.mark.unit
class TestRedisAwareSchedulerApplyEntry:
    def test_non_scrape_entry_passes_through_without_redis_lookup(self):
        sched = _make_scheduler()
        entry = _entry("evaluate-watchlist-alerts")
        fake_redis = MagicMock()
        with (
            patch("adapters.queue.redis_scheduler.get_redis", return_value=fake_redis),
            patch.object(PersistentScheduler, "apply_entry") as super_apply,
        ):
            sched.apply_entry(entry, producer="prod")
        fake_redis.get.assert_not_called()
        super_apply.assert_called_once_with(entry, producer="prod")

    def test_no_override_present_falls_through(self):
        sched = _make_scheduler()
        entry = _entry("scrape-quintoandar")
        fake_redis = MagicMock()
        fake_redis.get.return_value = None
        with (
            patch("adapters.queue.redis_scheduler.get_redis", return_value=fake_redis),
            patch.object(PersistentScheduler, "apply_entry") as super_apply,
        ):
            sched.apply_entry(entry, producer=None)
        super_apply.assert_called_once_with(entry, producer=None)

    def test_disabled_override_skips_task_without_calling_super(self):
        """An interval override <= 0 means disabled — must return early."""
        sched = _make_scheduler()
        entry = _entry("scrape-quintoandar")
        fake_redis = MagicMock()
        fake_redis.get.return_value = b"0"
        with (
            patch("adapters.queue.redis_scheduler.get_redis", return_value=fake_redis),
            patch.object(PersistentScheduler, "apply_entry") as super_apply,
        ):
            result = sched.apply_entry(entry, producer=None)
        assert result is None
        super_apply.assert_not_called()

    def test_changed_override_reschedules_and_syncs(self):
        """A changed positive override updates run_every and calls _maybe_sync."""
        sched = _make_scheduler()
        sched._maybe_sync = MagicMock()
        entry = _entry("scrape-olx", run_every_seconds=600.0)
        fake_redis = MagicMock()
        fake_redis.get.return_value = b"5"  # 5 minutes = 300s, differs from 600s
        with (
            patch("adapters.queue.redis_scheduler.get_redis", return_value=fake_redis),
            patch.object(PersistentScheduler, "apply_entry") as super_apply,
        ):
            sched.apply_entry(entry, producer=None)
        sched._maybe_sync.assert_called_once()
        assert entry.schedule.run_every.total_seconds() == 300.0
        super_apply.assert_called_once_with(entry, producer=None)

    def test_unchanged_override_does_not_resync(self):
        sched = _make_scheduler()
        sched._maybe_sync = MagicMock()
        entry = _entry("scrape-olx", run_every_seconds=300.0)
        fake_redis = MagicMock()
        fake_redis.get.return_value = b"5"  # 5 minutes = 300s, matches current
        with (
            patch("adapters.queue.redis_scheduler.get_redis", return_value=fake_redis),
            patch.object(PersistentScheduler, "apply_entry") as super_apply,
        ):
            sched.apply_entry(entry, producer=None)
        sched._maybe_sync.assert_not_called()
        super_apply.assert_called_once_with(entry, producer=None)

    def test_invalid_override_logs_warning_and_falls_through_without_raising(self):
        """Regression for BIN-129: this exact path used to raise TypeError from
        the stdlib logger receiving unsupported structured kwargs."""
        sched = _make_scheduler()
        entry = _entry("scrape-zapimoveis")
        fake_redis = MagicMock()
        fake_redis.get.return_value = b"not-a-number"
        with (
            patch("adapters.queue.redis_scheduler.get_redis", return_value=fake_redis),
            patch.object(PersistentScheduler, "apply_entry") as super_apply,
        ):
            # Must not raise TypeError — this is exactly the crash scenario.
            sched.apply_entry(entry, producer=None)
        super_apply.assert_called_once_with(entry, producer=None)

    def test_invalid_override_as_plain_str_also_does_not_raise(self):
        """Redis client config may return str instead of bytes; cover both."""
        sched = _make_scheduler()
        entry = _entry("scrape-quintoandar")
        fake_redis = MagicMock()
        fake_redis.get.return_value = "garbage"
        with (
            patch("adapters.queue.redis_scheduler.get_redis", return_value=fake_redis),
            patch.object(PersistentScheduler, "apply_entry") as super_apply,
        ):
            sched.apply_entry(entry, producer=None)
        super_apply.assert_called_once_with(entry, producer=None)
