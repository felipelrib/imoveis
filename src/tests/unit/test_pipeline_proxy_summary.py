"""Unit tests for GET /system/pipeline proxy summary (BIN-124)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.system import _pipeline_proxy_summary
from infra.config import ProxyConfig, get_config


@pytest.fixture(autouse=True)
def _clear_config_cache(monkeypatch: pytest.MonkeyPatch):
    # BIN-150 gated /system/pipeline behind verify_api_key_if_configured; force
    # the anonymous-access branch (no API_KEY configured) so this data-shape
    # test stays independent of ambient env (validate.sh exports a real API_KEY).
    monkeypatch.setenv("API_KEY", "")
    get_config.cache_clear()
    yield
    get_config.cache_clear()


@pytest.mark.unit
def test_pipeline_proxy_summary_direct_when_disabled():
    cfg = MagicMock()
    cfg.proxy = ProxyConfig(enabled=False, url=None, pool=[])
    with patch("api.system.get_config", return_value=cfg):
        summary = _pipeline_proxy_summary()
    assert summary["proxy_enabled"] is False
    assert summary["proxy_mode"] == "direct"
    assert summary["health"] == "direct"
    assert summary["pool_size"] == 0
    assert summary["proxy_host"] is None


@pytest.mark.unit
def test_pipeline_proxy_summary_ok_for_pool():
    cfg = MagicMock()
    cfg.proxy = ProxyConfig(
        enabled=True,
        pool=["http://user:s3cret@proxy-a.example:8080"],
        rotation_strategy="round_robin",
    )
    with patch("api.system.get_config", return_value=cfg):
        summary = _pipeline_proxy_summary()
    assert summary["proxy_enabled"] is True
    assert summary["proxy_mode"] == "pool"
    assert summary["health"] == "ok"
    assert summary["pool_size"] == 1
    assert summary["proxy_host"] == "http://proxy-a.example:8080"
    assert "s3cret" not in str(summary)
    assert "user:" not in str(summary)


@pytest.mark.unit
def test_pipeline_proxy_summary_warn_when_enabled_empty():
    cfg = MagicMock()
    cfg.proxy = ProxyConfig(enabled=True, url=None, pool=[])
    with patch("api.system.get_config", return_value=cfg):
        summary = _pipeline_proxy_summary()
    assert summary["proxy_enabled"] is True
    assert summary["proxy_mode"] == "direct"
    assert summary["health"] == "warn"


@pytest.mark.unit
def test_system_pipeline_includes_safe_proxy_fields():
    redis = MagicMock()
    redis.llen.return_value = 0
    redis.get.return_value = None
    redis.lrange.return_value = []

    cfg = MagicMock()
    cfg.proxy = ProxyConfig(
        enabled=True,
        url="http://op:s3cret@proxy.example:3128",
        pool=[],
    )
    cfg.scraping.platforms = {"olx": MagicMock()}

    with (
        patch("api.system.get_redis", return_value=redis),
        patch("api.system.get_config", return_value=cfg),
    ):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/system/pipeline")

    assert response.status_code == 200
    data = response.json()
    proxy = data["proxy"]
    assert proxy["proxy_mode"] == "single"
    assert proxy["health"] == "ok"
    assert proxy["proxy_host"] == "http://proxy.example:3128"
    raw = response.text
    assert "s3cret" not in raw
    assert "op:" not in raw
