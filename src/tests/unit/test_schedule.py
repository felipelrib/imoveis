"""Unit tests for the Celery beat schedule builder."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestBuildBeatSchedule:
    """Tests for adapters.queue.celery_app.build_beat_schedule."""

    @patch("adapters.queue.celery_app.get_config")
    @patch("adapters.queue.celery_app.get_redis")
    def test_enabled_platforms_produce_schedule_entries(self, mock_get_redis, mock_get_config):
        """Enabled platforms with interval > 0 produce a schedule entry."""
        from adapters.queue.celery_app import build_beat_schedule

        # Arrange
        cfg = MagicMock()
        cfg.scraping.platforms = {
            "quintoandar": MagicMock(enabled=True, scrape_interval=60),
            "olx": MagicMock(enabled=True, scrape_interval=30),
        }
        mock_get_config.return_value = cfg

        redis_inst = MagicMock()
        redis_inst.get.return_value = None  # no Redis overrides
        mock_get_redis.return_value = redis_inst

        # Act
        schedule = build_beat_schedule()

        # Assert
        assert "scrape-quintoandar" in schedule
        assert "scrape-olx" in schedule
        assert schedule["scrape-quintoandar"]["task"] == "tasks.scrape_listings"
        assert schedule["scrape-quintoandar"]["schedule"] == 60 * 60  # 60 min → 3600 sec
        assert schedule["scrape-quintoandar"]["args"] == ["quintoandar"]
        assert schedule["scrape-olx"]["schedule"] == 30 * 60  # 30 min → 1800 sec

    @patch("adapters.queue.celery_app.get_config")
    @patch("adapters.queue.celery_app.get_redis")
    def test_disabled_platform_excluded(self, mock_get_redis, mock_get_config):
        """Platforms with enabled=False are excluded from the schedule."""
        from adapters.queue.celery_app import build_beat_schedule

        cfg = MagicMock()
        cfg.scraping.platforms = {
            "quintoandar": MagicMock(enabled=False, scrape_interval=60),
            "olx": MagicMock(enabled=True, scrape_interval=30),
        }
        mock_get_config.return_value = cfg

        redis_inst = MagicMock()
        redis_inst.get.return_value = None
        mock_get_redis.return_value = redis_inst

        schedule = build_beat_schedule()

        assert "scrape-quintoandar" not in schedule
        assert "scrape-olx" in schedule

    @patch("adapters.queue.celery_app.get_config")
    @patch("adapters.queue.celery_app.get_redis")
    def test_zero_interval_excluded(self, mock_get_redis, mock_get_config):
        """Platforms with scrape_interval=0 are excluded (manual only)."""
        from adapters.queue.celery_app import build_beat_schedule

        cfg = MagicMock()
        cfg.scraping.platforms = {
            "quintoandar": MagicMock(enabled=True, scrape_interval=0),
        }
        mock_get_config.return_value = cfg

        redis_inst = MagicMock()
        redis_inst.get.return_value = None
        mock_get_redis.return_value = redis_inst

        schedule = build_beat_schedule()

        assert len(schedule) == 0

    @patch("adapters.queue.celery_app.get_config")
    @patch("adapters.queue.celery_app.get_redis")
    def test_redis_override_takes_precedence(self, mock_get_redis, mock_get_config):
        """A Redis override for interval takes precedence over the config value."""
        from adapters.queue.celery_app import build_beat_schedule

        cfg = MagicMock()
        cfg.scraping.platforms = {
            "olx": MagicMock(enabled=True, scrape_interval=60),
        }
        mock_get_config.return_value = cfg

        redis_inst = MagicMock()
        redis_inst.get.return_value = "120"  # Redis says 120 minutes
        mock_get_redis.return_value = redis_inst

        schedule = build_beat_schedule()

        assert schedule["scrape-olx"]["schedule"] == 120 * 60  # 120 min → 7200 sec

    @patch("adapters.queue.celery_app.get_config")
    @patch("adapters.queue.celery_app.get_redis")
    def test_redis_override_to_zero_disables(self, mock_get_redis, mock_get_config):
        """Redis override of '0' disables scheduling for that platform."""
        from adapters.queue.celery_app import build_beat_schedule

        cfg = MagicMock()
        cfg.scraping.platforms = {
            "olx": MagicMock(enabled=True, scrape_interval=60),
        }
        mock_get_config.return_value = cfg

        redis_inst = MagicMock()
        redis_inst.get.return_value = "0"  # disable via Redis
        mock_get_redis.return_value = redis_inst

        schedule = build_beat_schedule()

        assert len(schedule) == 0

    @patch("adapters.queue.celery_app.get_config")
    @patch("adapters.queue.celery_app.get_redis")
    def test_empty_platforms(self, mock_get_redis, mock_get_config):
        """No platforms configured → empty schedule."""
        from adapters.queue.celery_app import build_beat_schedule

        cfg = MagicMock()
        cfg.scraping.platforms = {}
        mock_get_config.return_value = cfg

        redis_inst = MagicMock()
        mock_get_redis.return_value = redis_inst

        schedule = build_beat_schedule()
        assert schedule == {}

    @patch("adapters.queue.celery_app.get_config", side_effect=Exception("config error"))
    @patch("adapters.queue.celery_app.get_redis")
    def test_exception_returns_empty(self, mock_get_redis, mock_get_config):
        """If config/Redis is unavailable, returns empty schedule (no crash)."""
        from adapters.queue.celery_app import build_beat_schedule

        schedule = build_beat_schedule()
        assert schedule == {}