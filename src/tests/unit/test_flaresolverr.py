"""Unit tests for the FlareSolverr bypass session (BIN-246)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from adapters.scrapers.base import BaseScraper
from adapters.scrapers.flaresolverr import (
    CloudflareFallbackSession,
    FlareSolverrError,
    FlareSolverrSession,
)
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
    session = FlareSolverrSession(_cfg(), client=client)
    with pytest.raises(FlareSolverrError):
        session.get("https://www.olx.com.br/x")


def test_get_raises_on_transport_error():
    client = _fake_client(raise_http=True)
    session = FlareSolverrSession(_cfg(), client=client)
    with pytest.raises(FlareSolverrError):
        session.get("https://www.olx.com.br/x")


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


def _config_with_bypass(enabled, platforms=("olx",), auto_fallback=True):
    cfg = MagicMock()
    cfg.scraping.cloudflare_bypass = CloudflareBypassConfig(
        enabled=enabled, platforms=list(platforms), auto_fallback=auto_fallback
    )
    return cfg


def _resp(status_code):
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    return r


def test_fallback_passes_direct_response_through_on_non_403():
    direct = MagicMock()
    direct.get.return_value = _resp(200)
    flare = MagicMock()
    sess = CloudflareFallbackSession(direct, _cfg(), flare=flare)
    resp = sess.get("https://www.zapimoveis.com.br/x")
    assert resp.status_code == 200
    flare.get.assert_not_called()  # un-gated request never touches FlareSolverr


def test_fallback_retries_403_through_flaresolverr():
    direct = MagicMock()
    direct.get.return_value = _resp(403)
    flare = MagicMock()
    flare.get.return_value = _resp(200)
    sess = CloudflareFallbackSession(direct, _cfg(), flare=flare)
    resp = sess.get("https://www.zapimoveis.com.br/x")
    assert resp.status_code == 200
    flare.get.assert_called_once()


def test_fallback_is_sticky_after_first_block():
    direct = MagicMock()
    direct.get.return_value = _resp(403)
    flare = MagicMock()
    flare.get.return_value = _resp(200)
    sess = CloudflareFallbackSession(direct, _cfg(), flare=flare)
    sess.get("https://www.zapimoveis.com.br/a")  # first 403 → engages flare
    sess.get("https://www.zapimoveis.com.br/b")  # sticky → straight to flare
    assert direct.get.call_count == 1  # no second wasted direct attempt
    assert flare.get.call_count == 2


def test_fallback_close_closes_both_transports():
    direct = MagicMock()
    flare = MagicMock()
    sess = CloudflareFallbackSession(direct, _cfg(), flare=flare)
    sess.close()
    direct.close.assert_called_once()
    flare.close.assert_called_once()


def test_fallback_lazily_creates_flaresolverr_session_on_block():
    """With no injected flare, the first 403 lazily builds a real
    FlareSolverrSession from the bypass config."""
    direct = MagicMock()
    direct.get.return_value = _resp(403)
    with patch("adapters.scrapers.flaresolverr.FlareSolverrSession") as fake_fs:
        fake_fs.return_value.get.return_value = _resp(200)
        sess = CloudflareFallbackSession(direct, _cfg())  # flare=None
        resp = sess.get("https://www.zapimoveis.com.br/x")
    assert resp.status_code == 200
    fake_fs.assert_called_once()


def test_fallback_degrades_to_original_403_when_sidecar_unavailable():
    """If FlareSolverr is unreachable (no sidecar), a Cloudflare 403 degrades to
    the original response — no new error, no stickiness — so enabling the bypass
    is a no-op wherever the sidecar isn't running (e.g. CI)."""
    direct = MagicMock()
    blocked = _resp(403)
    direct.get.return_value = blocked
    flare = MagicMock()
    flare.get.side_effect = FlareSolverrError("connection refused")
    sess = CloudflareFallbackSession(direct, _cfg(), flare=flare)
    resp = sess.get("https://www.zapimoveis.com.br/x")
    assert resp is blocked  # original 403 returned, not raised
    # Not sticky on failure: next call still tries direct first.
    sess.get("https://www.zapimoveis.com.br/y")
    assert direct.get.call_count == 2


def test_fallback_headers_default_when_direct_has_none():
    direct = MagicMock()
    direct.headers = None
    sess = CloudflareFallbackSession(direct, _cfg())
    assert isinstance(sess.headers, httpx.Headers)


def test_fallback_headers_shared_with_direct_client():
    direct = MagicMock()
    direct.headers = httpx.Headers({"User-Agent": "orig"})
    sess = CloudflareFallbackSession(direct, _cfg())
    sess.headers.update({"User-Agent": "updated"})  # scraper start() does this
    assert direct.headers["User-Agent"] == "updated"


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


def test_base_auto_fallback_wraps_unlisted_platform():
    """BIN-247: an unlisted platform with auto_fallback on gets a fallback
    session (direct-first, FlareSolverr on 403), not the raw client."""
    scraper = _Scraper("zapimoveis", {})
    httpx_client = MagicMock(spec=httpx.Client)
    httpx_client.headers = httpx.Headers({"User-Agent": "orig"})
    httpx_client.imoveis_proxy_summary = {"proxy_mode": "direct"}
    with patch(
        "adapters.scrapers.base.create_scraper_http_client", return_value=httpx_client
    ), patch(
        "adapters.scrapers.base.get_config",
        return_value=_config_with_bypass(True, platforms=("olx",), auto_fallback=True),
    ):
        session = scraper.create_http_session()

    assert isinstance(session, CloudflareFallbackSession)
    httpx_client.close.assert_not_called()  # direct client kept for the fast path
    assert scraper.proxy_summary["cloudflare_autofallback"] is True


def test_base_keeps_httpx_when_unlisted_and_auto_fallback_off():
    scraper = _Scraper("quintoandar", {})
    httpx_client = MagicMock(spec=httpx.Client)
    httpx_client.imoveis_proxy_summary = {"proxy_mode": "direct"}
    with patch(
        "adapters.scrapers.base.create_scraper_http_client", return_value=httpx_client
    ), patch(
        "adapters.scrapers.base.get_config",
        return_value=_config_with_bypass(True, platforms=("olx",), auto_fallback=False),
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
