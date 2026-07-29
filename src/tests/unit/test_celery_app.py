"""Unit tests for adapters.queue.celery_app.make_celery (BIN-130).

Regression coverage: Celery's broker_url/result_backend must resolve through
AppConfig (``cfg.redis.url`` — the same path infra.redis_client.get_redis()
uses), never a bare ``os.environ.get("REDIS_URL", ...)``. Otherwise, when
Redis is configured via YAML fields only (no REDIS_URL env var), Celery would
silently point at a different Redis instance than the rest of the app.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.infra.config import load_config

YAML_WITH_CUSTOM_REDIS = """\
database:
  host: localhost
  port: 5432
  name: testdb
  user: testuser
  password: testpass
  pool_size: 5
  max_overflow: 2
redis:
  host: redis-yaml-host
  port: 6390
  db: 3
  password: "yamlsecret"
celery:
  task_serializer: json
  result_serializer: json
  accept_content:
    - json
  timezone: America/Sao_Paulo
  beat_schedule: {}
gpu:
  enabled: true
  semaphore_limit: 1
ai:
  providers:
    ollama:
      base_url: http://localhost:11434
      default_model: llava
      request_timeout: 120
      max_retries: 3
scraping:
  default_delay: 2.0
  user_agent: "test-agent/1.0"
  platforms: {}
features:
  property_enrichment: false
  price_alerts: false
"""


@pytest.mark.unit
class TestMakeCeleryRedisResolution:
    """make_celery() must build broker/backend from AppConfig, not os.environ."""

    @patch("adapters.queue.celery_app.get_redis")
    @patch("adapters.queue.celery_app.get_config")
    def test_broker_and_backend_match_appconfig_redis_url(
        self, mock_get_config, mock_get_redis, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """When only YAML redis fields are set (no REDIS_URL env var), Celery's
        broker_url/result_backend must equal AppConfig's resolved redis.url —
        not the hardcoded ``redis://localhost:6379/0`` default.
        """
        # Guard: prove this test's environment has no REDIS_URL that could
        # mask a regression back to os.environ.get.
        monkeypatch.delenv("REDIS_URL", raising=False)

        cfg_file = tmp_path / "app_config.yaml"
        cfg_file.write_text(YAML_WITH_CUSTOM_REDIS)
        real_cfg = load_config(cfg_file)

        expected_url = "redis://:yamlsecret@redis-yaml-host:6390/3"
        assert real_cfg.redis.url == expected_url  # sanity on the fixture itself

        mock_get_config.return_value = real_cfg
        # build_beat_schedule() also calls get_redis(); stub it out so it
        # doesn't try to hit a real Redis instance.
        redis_inst = MagicMock()
        redis_inst.get.return_value = None
        mock_get_redis.return_value = redis_inst

        from adapters.queue.celery_app import make_celery

        celery_app = make_celery()

        assert celery_app.conf.broker_url == expected_url
        assert celery_app.conf.result_backend == expected_url
        assert celery_app.conf.broker_url != "redis://localhost:6379/0"

    @patch("adapters.queue.celery_app.get_redis")
    @patch("adapters.queue.celery_app.get_config")
    def test_broker_and_backend_use_get_config_not_os_environ(
        self, mock_get_config, mock_get_redis, monkeypatch: pytest.MonkeyPatch
    ):
        """A REDIS_URL env var present in the process must NOT leak into Celery
        unless AppConfig itself resolved it — celery_app must delegate entirely
        to get_config().redis.url instead of reading os.environ directly.
        """
        # A REDIS_URL pointing at a *different* Redis than AppConfig resolved.
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        cfg = MagicMock()
        cfg.redis.url = "redis://:pw@appconfig-host:6400/5"
        mock_get_config.return_value = cfg

        redis_inst = MagicMock()
        redis_inst.get.return_value = None
        mock_get_redis.return_value = redis_inst

        from adapters.queue.celery_app import make_celery

        celery_app = make_celery()

        assert celery_app.conf.broker_url == "redis://:pw@appconfig-host:6400/5"
        assert celery_app.conf.result_backend == "redis://:pw@appconfig-host:6400/5"
