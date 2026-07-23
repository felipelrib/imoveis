"""Unit tests for scraper proxy-aware HTTP client (BIN-48 / BIN-49)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from adapters.scrapers.base import BaseScraper
from adapters.scrapers.http_client import (
    create_scraper_http_client,
    proxy_mode_summary,
    redact_proxy_url,
    reset_round_robin,
    resolve_proxy_url,
)
from infra.config import ProxyConfig


@pytest.fixture(autouse=True)
def _reset_rr():
    reset_round_robin()
    yield
    reset_round_robin()


@pytest.mark.unit
class TestResolveProxyUrl:
    def test_disabled_returns_none(self):
        cfg = ProxyConfig(enabled=False, url="http://proxy.example:8080")
        assert resolve_proxy_url(cfg) is None

    def test_single_url_mode(self):
        cfg = ProxyConfig(enabled=True, url="http://proxy.example:8080")
        assert resolve_proxy_url(cfg) == "http://proxy.example:8080"

    def test_enabled_empty_pool_and_url_returns_none(self):
        cfg = ProxyConfig(enabled=True, url=None, pool=[])
        assert resolve_proxy_url(cfg) is None

    def test_round_robin_cycles(self):
        cfg = ProxyConfig(
            enabled=True,
            rotation_strategy="round_robin",
            pool=["http://a.example:1", "http://b.example:2"],
        )
        assert resolve_proxy_url(cfg) == "http://a.example:1"
        assert resolve_proxy_url(cfg) == "http://b.example:2"
        assert resolve_proxy_url(cfg) == "http://a.example:1"

    def test_random_uses_choice(self):
        cfg = ProxyConfig(
            enabled=True,
            rotation_strategy="random",
            pool=["http://a.example:1", "http://b.example:2"],
        )
        with patch(
            "adapters.scrapers.http_client.secrets.choice",
            return_value="http://b.example:2",
        ) as choice:
            assert resolve_proxy_url(cfg) == "http://b.example:2"
        choice.assert_called_once_with(cfg.pool)

    def test_platform_override_wins(self):
        cfg = ProxyConfig(
            enabled=True,
            rotation_strategy="round_robin",
            pool=["http://a.example:1", "http://b.example:2"],
        )
        assert (
            resolve_proxy_url(cfg, platform_override="http://override.example:9")
            == "http://override.example:9"
        )
        # override must not advance round-robin
        assert resolve_proxy_url(cfg) == "http://a.example:1"

    def test_none_override_defers_to_global_pool(self):
        cfg = ProxyConfig(
            enabled=True,
            rotation_strategy="round_robin",
            pool=["http://a.example:1"],
        )
        assert resolve_proxy_url(cfg, platform_override=None) == "http://a.example:1"


@pytest.mark.unit
class TestRedactAndProxyModeSummary:
    def test_redact_strips_userinfo(self):
        assert (
            redact_proxy_url("http://user:secret@proxy.example:8080")
            == "http://proxy.example:8080"
        )

    def test_redact_none(self):
        assert redact_proxy_url(None) is None

    def test_summary_direct_when_disabled(self):
        cfg = ProxyConfig(enabled=False, url="http://user:secret@proxy.example:8080")
        summary = proxy_mode_summary(cfg, selected=None)
        assert summary["proxy_mode"] == "direct"
        assert summary["proxy_enabled"] is False
        assert summary["proxy_host"] is None
        blob = str(summary)
        assert "secret" not in blob
        assert "user" not in blob

    def test_summary_pool_redacts_selected(self):
        cfg = ProxyConfig(
            enabled=True,
            rotation_strategy="round_robin",
            pool=["http://alice:s3cret@a.example:1", "http://bob:t0ken@b.example:2"],
        )
        selected = "http://alice:s3cret@a.example:1"
        summary = proxy_mode_summary(cfg, selected=selected)
        assert summary["proxy_mode"] == "pool"
        assert summary["pool_size"] == 2
        assert summary["proxy_host"] == "http://a.example:1"
        blob = str(summary)
        assert "s3cret" not in blob
        assert "alice" not in blob
        assert "t0ken" not in blob

    def test_summary_single_mode(self):
        cfg = ProxyConfig(enabled=True, url="http://proxy.example:8080")
        summary = proxy_mode_summary(cfg, selected=cfg.url)
        assert summary["proxy_mode"] == "single"
        assert summary["proxy_host"] == "http://proxy.example:8080"

    def test_summary_override_mode(self):
        cfg = ProxyConfig(enabled=False)
        override = "http://op:pw@override.example:9"
        summary = proxy_mode_summary(cfg, platform_override=override, selected=override)
        assert summary["proxy_mode"] == "override"
        assert summary["proxy_host"] == "http://override.example:9"
        assert "pw" not in str(summary)


@pytest.mark.unit
class TestCreateScraperHttpClient:
    def test_passes_resolved_proxy_to_httpx(self):
        cfg = ProxyConfig(enabled=True, url="http://proxy.example:8080")
        fake = MagicMock()
        with patch("adapters.scrapers.http_client.httpx.Client", return_value=fake) as client:
            result = create_scraper_http_client(proxy=cfg)
        client.assert_called_once_with(proxy="http://proxy.example:8080")
        assert result is fake

    def test_loads_get_config_when_proxy_omitted(self):
        fake_cfg = MagicMock()
        fake_cfg.proxy = ProxyConfig(enabled=False)
        fake = MagicMock()
        with patch("adapters.scrapers.http_client.get_config", return_value=fake_cfg), patch(
            "adapters.scrapers.http_client.httpx.Client", return_value=fake
        ) as client:
            create_scraper_http_client()
        client.assert_called_once_with(proxy=None)

    def test_logs_safe_proxy_mode_without_credentials(self):
        cfg = ProxyConfig(enabled=True, url="http://user:hunter2@proxy.example:8080")
        fake = MagicMock()
        with patch("adapters.scrapers.http_client.httpx.Client", return_value=fake), patch(
            "adapters.scrapers.http_client.logger"
        ) as log:
            create_scraper_http_client(proxy=cfg)
        log.info.assert_called_once()
        assert log.info.call_args.args[0] == "scraper_proxy_mode"
        kwargs = log.info.call_args.kwargs
        assert kwargs["proxy_mode"] == "single"
        assert kwargs["proxy_host"] == "http://proxy.example:8080"
        assert "hunter2" not in str(kwargs)
        assert "user" not in str(kwargs)
        assert fake.imoveis_proxy_summary["proxy_mode"] == "single"


@pytest.mark.unit
class TestBaseScraperCreateHttpSession:
    def test_uses_extra_proxy_override(self):
        class _S(BaseScraper):
            def fetch_pages(self, checkpoint):
                yield from ()

            async def normalize(self, raw_data):
                return raw_data

        scraper = _S("test", {"extra": {"proxy": "http://platform.example:1"}})
        fake = MagicMock()
        fake.imoveis_proxy_summary = {
            "proxy_enabled": False,
            "proxy_mode": "override",
            "rotation_strategy": "round_robin",
            "pool_size": 0,
            "proxy_host": "http://platform.example:1",
        }
        with patch(
            "adapters.scrapers.base.create_scraper_http_client", return_value=fake
        ) as factory:
            assert scraper.create_http_session() is fake
        factory.assert_called_once_with(platform_override="http://platform.example:1")
        assert scraper.proxy_summary["proxy_mode"] == "override"

    def test_null_extra_proxy_passes_none_override(self):
        class _S(BaseScraper):
            def fetch_pages(self, checkpoint):
                yield from ()

            async def normalize(self, raw_data):
                return raw_data

        scraper = _S("test", {"extra": {"proxy": None}})
        with patch(
            "adapters.scrapers.base.create_scraper_http_client", return_value=MagicMock()
        ) as factory:
            scraper.create_http_session()
        factory.assert_called_once_with(platform_override=None)
