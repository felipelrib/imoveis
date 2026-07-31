"""Unit tests for the FlareSolverr bypass session (BIN-246)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from adapters.scrapers.base import BaseScraper
from adapters.scrapers.flaresolverr import FlareSolverrError, FlareSolverrSession
from infra.config import CloudflareBypassConfig


def _fake_client(*, json_data=None, raise_http=False):
    client = MagicMock(spec=httpx.Client)
    resp = MagicMock()
    if raise_http:
        resp.raise_for_status.side_effect = httpx.HTTPError("boom")
    else:
        resp.raise_for_status.return_value = None
    resp.json.return_value = json_data or {}
    client.post.return_value = resp
    return client


def _cfg():
    return CloudflareBypassConfig(
        enabled=True, endpoint="http://flaresolverr:8191/v1", max_timeout_ms=1000
    )


def test_get_returns_httpx_response_on_solved_page():
    client = _fake_client(
        json_data={
            "status": "ok",
            "solution": {
                "status": 200,
                "response": "<html>OLX body</html>",
                "url": "https://mg.olx.com.br/x-123",
            },
        }
    )
    session = FlareSolverrSession(_cfg(), client=client)
    resp = session.get("https://www.olx.com.br/x")

    assert isinstance(resp, httpx.Response)
    assert resp.status_code == 200
    assert "OLX body" in resp.text
    # It posted the FlareSolverr command envelope to the configured endpoint.
    args, kwargs = client.post.call_args
    assert args[0] == "http://flaresolverr:8191/v1"
    assert kwargs["json"]["cmd"] == "request.get"
    assert kwargs["json"]["url"] == "https://www.olx.com.br/x"


def test_get_propagates_upstream_403_as_response_not_error():
    """A solved-but-blocked page (403) must surface as a Response so the
    scraper's circuit breaker sees the status — not raise."""
    client = _fake_client(
        json_data={"status": "ok", "solution": {"status": 403, "response": "blocked"}}
    )
    resp = FlareSolverrSession(_cfg(), client=client).get("https://www.olx.com.br/x")
    assert resp.status_code == 403


def test_get_raises_when_service_reports_failure():
    client = _fake_client(json_data={"status": "error", "message": "timeout"})
    with pytest.raises(FlareSolverrError):
        FlareSolverrSession(_cfg(), client=client).get("https://www.olx.com.br/x")


def test_get_raises_on_transport_error():
    client = _fake_client(raise_http=True)
    with pytest.raises(FlareSolverrError):
        FlareSolverrSession(_cfg(), client=client).get("https://www.olx.com.br/x")


def test_headers_update_is_supported():
    """Scrapers call session.headers.update(...) in start(); it must not blow up."""
    session = FlareSolverrSession(_cfg(), client=_fake_client())
    session.headers.update({"User-Agent": "x"})
    assert session.headers["User-Agent"] == "x"


class _Scraper(BaseScraper):
    def fetch_pages(self, checkpoint):
        yield from ()

    async def normalize(self, raw_data):
        return raw_data


def _config_with_bypass(enabled, platforms=("olx",)):
    cfg = MagicMock()
    cfg.scraping.cloudflare_bypass = CloudflareBypassConfig(
        enabled=enabled, platforms=list(platforms)
    )
    return cfg


def test_base_routes_matching_platform_through_flaresolverr():
    scraper = _Scraper("olx", {})
    httpx_client = MagicMock(spec=httpx.Client)
    httpx_client.headers = httpx.Headers({"User-Agent": "orig"})
    httpx_client.imoveis_proxy_summary = {"proxy_mode": "direct"}
    with patch(
        "adapters.scrapers.base.create_scraper_http_client", return_value=httpx_client
    ), patch("adapters.scrapers.base.get_config", return_value=_config_with_bypass(True)):
        session = scraper.create_http_session()

    assert isinstance(session, FlareSolverrSession)
    httpx_client.close.assert_called_once()  # unused direct client released
    assert scraper.proxy_summary["cloudflare_bypass"] is True


def test_base_keeps_httpx_when_platform_not_listed():
    scraper = _Scraper("quintoandar", {})
    httpx_client = MagicMock(spec=httpx.Client)
    httpx_client.imoveis_proxy_summary = {"proxy_mode": "direct"}
    with patch(
        "adapters.scrapers.base.create_scraper_http_client", return_value=httpx_client
    ), patch(
        "adapters.scrapers.base.get_config",
        return_value=_config_with_bypass(True, platforms=("olx",)),
    ):
        session = scraper.create_http_session()

    assert session is httpx_client
    httpx_client.close.assert_not_called()


def test_base_keeps_httpx_when_bypass_disabled():
    scraper = _Scraper("olx", {})
    httpx_client = MagicMock(spec=httpx.Client)
    httpx_client.imoveis_proxy_summary = {}
    with patch(
        "adapters.scrapers.base.create_scraper_http_client", return_value=httpx_client
    ), patch("adapters.scrapers.base.get_config", return_value=_config_with_bypass(False)):
        session = scraper.create_http_session()

    assert session is httpx_client
