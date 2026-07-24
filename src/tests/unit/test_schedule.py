"""Unit tests for the Celery beat schedule builder."""

from __future__ import annotations

from types import SimpleNamespace
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
        cfg.alerts.digest_mode = False
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
        cfg.alerts.digest_mode = False
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
        cfg.alerts.digest_mode = False
        cfg.scraping.platforms = {
            "quintoandar": MagicMock(enabled=True, scrape_interval=0),
        }
        mock_get_config.return_value = cfg

        redis_inst = MagicMock()
        redis_inst.get.return_value = None
        mock_get_redis.return_value = redis_inst

        schedule = build_beat_schedule()

        assert "scrape-quintoandar" not in schedule
        assert "evaluate-watchlist-alerts" in schedule
        assert "monitor-queues" in schedule
        assert "snapshot-pipeline-metrics" in schedule
        assert schedule["snapshot-pipeline-metrics"]["task"] == "tasks.snapshot_pipeline_metrics"
        assert schedule["snapshot-pipeline-metrics"]["schedule"] == 30.0

    @patch("adapters.queue.celery_app.get_config")
    @patch("adapters.queue.celery_app.get_redis")
    def test_redis_override_takes_precedence(self, mock_get_redis, mock_get_config):
        """A Redis override for interval takes precedence over the config value."""
        from adapters.queue.celery_app import build_beat_schedule

        cfg = MagicMock()
        cfg.alerts.digest_mode = False
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
        cfg.alerts.digest_mode = False
        cfg.scraping.platforms = {
            "olx": MagicMock(enabled=True, scrape_interval=60),
        }
        mock_get_config.return_value = cfg

        redis_inst = MagicMock()
        redis_inst.get.return_value = "0"  # disable via Redis
        mock_get_redis.return_value = redis_inst

        schedule = build_beat_schedule()

        assert "scrape-olx" not in schedule
        assert "evaluate-watchlist-alerts" in schedule

    @patch("adapters.queue.celery_app.get_config")
    @patch("adapters.queue.celery_app.get_redis")
    def test_empty_platforms(self, mock_get_redis, mock_get_config):
        """No platforms configured → only always-on maintenance jobs."""
        from adapters.queue.celery_app import build_beat_schedule

        cfg = MagicMock()
        cfg.alerts.digest_mode = False
        cfg.scraping.platforms = {}
        mock_get_config.return_value = cfg

        redis_inst = MagicMock()
        mock_get_redis.return_value = redis_inst

        schedule = build_beat_schedule()
        assert set(schedule) == {
            "evaluate-watchlist-alerts",
            "monitor-queues",
            "snapshot-pipeline-metrics",
        }

    @patch("adapters.queue.celery_app.get_config")
    @patch("adapters.queue.celery_app.get_redis")
    def test_top_deals_enabled_adds_beat_entry(self, mock_get_redis, mock_get_config):
        """alerts.top_deals.enabled schedules send_top_deals_digest (not send_daily_digest)."""
        from adapters.queue.celery_app import build_beat_schedule

        cfg = MagicMock()
        cfg.alerts.digest_mode = False
        cfg.alerts.top_deals = SimpleNamespace(
            enabled=True,
            crontab_hour=9,
            crontab_minute=15,
            crontab_day_of_week="1",
        )
        cfg.scraping.platforms = {}
        mock_get_config.return_value = cfg
        mock_get_redis.return_value = MagicMock()

        schedule = build_beat_schedule()

        assert "send-top-deals-digest" in schedule
        assert schedule["send-top-deals-digest"]["task"] == "tasks.send_top_deals_digest"
        assert "send-daily-digest" not in schedule

    @patch("adapters.queue.celery_app.get_config")
    @patch("adapters.queue.celery_app.get_redis")
    def test_top_deals_disabled_excluded(self, mock_get_redis, mock_get_config):
        from adapters.queue.celery_app import build_beat_schedule

        cfg = MagicMock()
        cfg.alerts.digest_mode = False
        cfg.alerts.top_deals = SimpleNamespace(enabled=False)
        cfg.scraping.platforms = {}
        mock_get_config.return_value = cfg
        mock_get_redis.return_value = MagicMock()

        schedule = build_beat_schedule()
        assert "send-top-deals-digest" not in schedule

    @patch("adapters.queue.celery_app.build_beat_schedule", return_value={"scheduled": {}})
    @patch("adapters.queue.celery_app.Celery")
    def test_make_celery_applies_broker_routes_and_schedule(self, celery_cls, build_schedule, monkeypatch):
        from adapters.queue.celery_app import make_celery

        monkeypatch.setenv("REDIS_URL", "redis://broker:6379/9")
        app = MagicMock()
        celery_cls.return_value = app

        result = make_celery()

        assert result is app
        celery_cls.assert_called_once_with("real_estate_scraper")
        app.conf.update.assert_called_once_with(
            broker_url="redis://broker:6379/9",
            result_backend="redis://broker:6379/9",
            task_serializer="json",
            accept_content=["json"],
            result_serializer="json",
            timezone="UTC",
            enable_utc=True,
            worker_prefetch_multiplier=1,
            task_acks_late=True,
            task_reject_on_worker_lost=True,
            task_track_started=True,
        )
        assert app.conf.task_default_retry_delay == 30
        assert app.conf.task_default_max_retries == 3
        assert app.conf.task_routes["tasks.ai_enrich"] == {"queue": "ai"}
        assert app.conf.beat_schedule == {"scheduled": {}}
        build_schedule.assert_called_once()

    @patch("adapters.queue.celery_app.Celery")
    def test_make_celery_uses_default_redis_url(self, celery_cls, monkeypatch):
        from adapters.queue.celery_app import make_celery

        monkeypatch.delenv("REDIS_URL", raising=False)
        celery_cls.return_value = MagicMock()

        make_celery()

        assert celery_cls.return_value.conf.update.call_args.kwargs["broker_url"] == "redis://localhost:6379/0"


@pytest.mark.unit
class TestTaskSignals:
    def test_failure_handler_logs_task_context(self):
        from adapters.queue.celery_app import handle_task_failure

        sender = MagicMock()
        sender.name = "tasks.scrape"
        with patch("adapters.queue.celery_app.logger") as logger:
            handle_task_failure(
                sender=sender,
                task_id="task-1",
                exception=ValueError("bad listing"),
                traceback="trace",
                args=["olx"],
                kwargs={"force": True},
            )

        logger.error.assert_called_once()
        extra = logger.error.call_args.kwargs["extra"]
        assert extra["task_id"] == "task-1"
        assert extra["task_name"] == "tasks.scrape"
        assert extra["exception"] == "bad listing"
        assert extra["args"] == ["olx"]

    def test_failure_handler_logs_its_own_logging_error(self):
        from adapters.queue.celery_app import handle_task_failure

        with patch("adapters.queue.celery_app.logger") as logger:
            logger.error.side_effect = RuntimeError("logger failed")
            handle_task_failure()

        logger.exception.assert_called_once_with("Error in task failure handler")

    def test_revoked_handler_logs_request_context(self):
        from adapters.queue.celery_app import handle_task_revoked

        sender = MagicMock()
        sender.name = "tasks.ai"
        request = MagicMock(id="task-2")
        with patch("adapters.queue.celery_app.logger") as logger:
            handle_task_revoked(sender=sender, request=request, terminated=True, signum="TERM", expired=False)

        logger.warning.assert_called_once()
        extra = logger.warning.call_args.kwargs["extra"]
        assert extra == {
            "task_id": "task-2",
            "task_name": "tasks.ai",
            "terminated": True,
            "signum": "TERM",
            "expired": False,
        }

    def test_revoked_handler_logs_its_own_logging_error(self):
        from adapters.queue.celery_app import handle_task_revoked

        with patch("adapters.queue.celery_app.logger") as logger:
            logger.warning.side_effect = RuntimeError("logger failed")
            handle_task_revoked()

        logger.exception.assert_called_once_with("Error in task revoked handler")

    @patch("adapters.queue.celery_app.get_config", side_effect=Exception("config error"))
    @patch("adapters.queue.celery_app.get_redis")
    def test_exception_returns_empty(self, mock_get_redis, mock_get_config):
        """If config/Redis is unavailable, keep always-on jobs (no crash)."""
        from adapters.queue.celery_app import build_beat_schedule

        schedule = build_beat_schedule()
        assert set(schedule) == {
            "evaluate-watchlist-alerts",
            "monitor-queues",
            "snapshot-pipeline-metrics",
        }
