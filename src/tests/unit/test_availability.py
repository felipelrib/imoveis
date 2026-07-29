"""Unit tests for listing availability classifiers and recheck task (BIN-80)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx

from adapters.scrapers.availability import (
    AvailabilityResult,
    AvailabilityStatus,
    check_listing,
    classify_response,
    deactivate_listing_and_maybe_property,
    parse_olx_availability,
    parse_quintoandar_availability,
    parse_zapimoveis_availability,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "scrapers"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestQuintoAndarAvailability:
    def test_despublicado_rent_is_unavailable(self):
        html = _load("quintoandar_unavailable.html")
        result = parse_quintoandar_availability(
            status_code=404, html=html, listing_type="rent"
        )
        assert result.status == AvailabilityStatus.UNAVAILABLE
        assert "despublicado" in result.reason

    def test_same_page_sale_still_available(self):
        html = _load("quintoandar_unavailable.html")
        result = parse_quintoandar_availability(
            status_code=404, html=html, listing_type="sale"
        )
        assert result.status == AvailabilityStatus.AVAILABLE

    def test_publicado_is_available(self):
        html = _load("quintoandar_available.html")
        result = parse_quintoandar_availability(
            status_code=200, html=html, listing_type="rent"
        )
        assert result.status == AvailabilityStatus.AVAILABLE

    def test_http_403_is_unknown(self):
        result = parse_quintoandar_availability(status_code=403, html="")
        assert result.status == AvailabilityStatus.UNKNOWN

    def test_404_without_next_data_is_unknown(self):
        result = parse_quintoandar_availability(status_code=404, html="<html></html>")
        assert result.status == AvailabilityStatus.UNKNOWN
        assert result.reason == "qa_404_no_next_data"

    def test_ui_indisponivel_fallback(self):
        html = (
            '<html><body><p>Esse imóvel está indisponível :(</p>'
            '<script id="__NEXT_DATA__" type="application/json">'
            '{"props":{"pageProps":{"initialState":{"house":{"houseInfo":{"status":""}}}}}}'
            "</script></body></html>"
        )
        result = parse_quintoandar_availability(
            status_code=200, html=html, listing_type="rent"
        )
        assert result.status == AvailabilityStatus.UNAVAILABLE


class TestOlxAvailability:
    def test_410_page_is_unavailable(self):
        html = _load("olx_unavailable_410.html")
        result = parse_olx_availability(
            status_code=410,
            html=html,
            request_url="https://www.olx.com.br/vi/1000000000",
            final_url="https://www.olx.com.br/vi/1000000000",
        )
        assert result.status == AvailabilityStatus.UNAVAILABLE

    def test_homepage_redirect_is_unavailable(self):
        result = parse_olx_availability(
            status_code=200,
            html="<html><title>OLX</title></html>",
            request_url="https://www.olx.com.br/vi/123456",
            final_url="https://www.olx.com.br/",
        )
        assert result.status == AvailabilityStatus.UNAVAILABLE
        assert "homepage" in result.reason

    def test_cloudflare_403_is_unknown(self):
        result = parse_olx_availability(
            status_code=403,
            html="<title>Attention Required! | Cloudflare</title>",
            request_url="https://www.olx.com.br/vi/1",
            final_url="https://www.olx.com.br/vi/1",
        )
        assert result.status == AvailabilityStatus.UNKNOWN

    def test_live_listing_ok(self):
        result = parse_olx_availability(
            status_code=200,
            html="<html><title>Apartamento 1490781405 | OLX</title></html>",
            request_url="https://mg.olx.com.br/imoveis/x-1490781405.htm",
            final_url="https://mg.olx.com.br/imoveis/x-1490781405.htm",
        )
        assert result.status == AvailabilityStatus.AVAILABLE

    def test_id_lost_in_redirect(self):
        result = parse_olx_availability(
            status_code=200,
            html="<html></html>",
            request_url="https://www.olx.com.br/vi/1490781405",
            final_url="https://www.olx.com.br/imoveis/estado-mg",
        )
        assert result.status == AvailabilityStatus.UNAVAILABLE
        assert "id_lost" in result.reason


def test_classify_response_dispatches():
    html = _load("olx_unavailable_410.html")
    result = classify_response(
        "olx",
        status_code=410,
        html=html,
        request_url="https://www.olx.com.br/vi/1",
    )
    assert result.status == AvailabilityStatus.UNAVAILABLE


def test_classify_unsupported_platform():
    result = classify_response(
        "zap",
        status_code=200,
        html="",
        request_url="https://example.com",
    )
    assert result.status == AvailabilityStatus.UNKNOWN
    assert result.reason == "unsupported_platform:zap"


class TestZapImoveisAvailability:
    def test_instock_detail_is_available(self):
        html = _load("zapimoveis_detail.html")
        result = parse_zapimoveis_availability(
            status_code=200,
            html=html,
            request_url=(
                "https://www.zapimoveis.com.br/imovel/"
                "aluguel-apartamento-lourdes-id-2877382105/"
            ),
        )
        assert result.status == AvailabilityStatus.AVAILABLE

    def test_out_of_stock_is_unavailable(self):
        html = _load("zapimoveis_unavailable.html")
        result = parse_zapimoveis_availability(
            status_code=200,
            html=html,
            request_url="https://www.zapimoveis.com.br/imovel/id-9999999999/",
        )
        assert result.status == AvailabilityStatus.UNAVAILABLE

    def test_http_404_is_unavailable(self):
        result = parse_zapimoveis_availability(
            status_code=404,
            html="",
            request_url="https://www.zapimoveis.com.br/imovel/id-1/",
        )
        assert result.status == AvailabilityStatus.UNAVAILABLE

    def test_cloudflare_403_is_unknown(self):
        result = parse_zapimoveis_availability(
            status_code=403,
            html="Attention Required! | Cloudflare",
            request_url="https://www.zapimoveis.com.br/imovel/id-1/",
        )
        assert result.status == AvailabilityStatus.UNKNOWN

    def test_homepage_redirect_is_unavailable(self):
        result = parse_zapimoveis_availability(
            status_code=200,
            html="<html><title>ZAP Imóveis</title></html>",
            request_url="https://www.zapimoveis.com.br/imovel/id-123456/",
            final_url="https://www.zapimoveis.com.br/",
        )
        assert result.status == AvailabilityStatus.UNAVAILABLE
        assert "homepage" in result.reason

    def test_title_not_found_text_signal_is_unavailable(self):
        html = "<html><head><title>Página não encontrada | ZAP Imóveis</title></head></html>"
        result = parse_zapimoveis_availability(
            status_code=200,
            html=html,
            request_url="https://www.zapimoveis.com.br/imovel/id-123456/",
        )
        assert result.status == AvailabilityStatus.UNAVAILABLE
        assert result.reason == "zap_out_of_stock"

    def test_body_not_found_text_signal_is_unavailable(self):
        html = "<html><body>Este anúncio não está mais disponível</body></html>"
        result = parse_zapimoveis_availability(
            status_code=200,
            html=html,
            request_url="https://www.zapimoveis.com.br/imovel/id-123456/",
        )
        assert result.status == AvailabilityStatus.UNAVAILABLE
        assert result.reason == "zap_out_of_stock"

    def test_id_mismatch_on_non_homepage_redirect_is_unknown(self):
        """Redirect signal only fires for a bare homepage path, not any id mismatch."""
        result = parse_zapimoveis_availability(
            status_code=200,
            html="<html><title>Apartamento</title></html>",
            request_url="https://www.zapimoveis.com.br/imovel/id-123456/",
            final_url="https://www.zapimoveis.com.br/imovel/id-999999-slug/",
        )
        assert result.status == AvailabilityStatus.UNKNOWN
        assert result.reason == "zap_http_200"

    def test_classify_response_dispatches_zapimoveis(self):
        html = _load("zapimoveis_unavailable.html")
        result = classify_response(
            "zapimoveis",
            status_code=200,
            html=html,
            request_url="https://www.zapimoveis.com.br/imovel/id-9999999999/",
        )
        assert result.status == AvailabilityStatus.UNAVAILABLE


def test_deactivate_listing_keeps_property_when_sibling_active():
    session = MagicMock()
    session.execute.side_effect = [
        MagicMock(),
        MagicMock(fetchone=MagicMock(return_value=("prop-1",))),
        MagicMock(scalar=MagicMock(return_value=1)),
    ]
    summary = deactivate_listing_and_maybe_property(session, "listing-1")
    assert summary["property_deactivated"] is False
    assert summary["remaining_active_listings"] == 1
    assert session.execute.call_count == 3


def test_deactivate_listing_deactivates_property_when_none_left():
    session = MagicMock()
    session.execute.side_effect = [
        MagicMock(),
        MagicMock(fetchone=MagicMock(return_value=("prop-1",))),
        MagicMock(scalar=MagicMock(return_value=0)),
        MagicMock(),
    ]
    summary = deactivate_listing_and_maybe_property(session, "listing-1")
    assert summary["property_deactivated"] is True
    assert session.execute.call_count == 4


def test_deactivate_missing_listing_row():
    session = MagicMock()
    session.execute.side_effect = [
        MagicMock(),
        MagicMock(fetchone=MagicMock(return_value=None)),
    ]
    summary = deactivate_listing_and_maybe_property(session, "missing")
    assert summary["property_deactivated"] is False


@patch("adapters.scrapers.availability.get_config")
def test_check_listing_uses_client_response(mock_get_config):
    mock_get_config.return_value = SimpleNamespace(
        scraping=SimpleNamespace(
            user_agent="test-agent",
            availability_recheck=SimpleNamespace(request_timeout_sec=5.0),
        )
    )
    html = _load("quintoandar_unavailable.html")
    response = MagicMock()
    response.status_code = 404
    response.text = html
    response.url = "https://www.quintoandar.com.br/imovel/1"
    client = MagicMock()
    client.get.return_value = response

    result = check_listing(
        "quintoandar",
        "https://www.quintoandar.com.br/imovel/1",
        "rent",
        client=client,
    )
    assert result.status == AvailabilityStatus.UNAVAILABLE
    client.close.assert_not_called()


@patch("adapters.scrapers.availability.get_config")
def test_check_listing_missing_url(mock_get_config):
    result = check_listing("olx", "", client=MagicMock())
    assert result.status == AvailabilityStatus.UNKNOWN
    assert result.reason == "missing_url"


@patch("adapters.scrapers.availability.get_config")
def test_check_listing_timeout(mock_get_config):
    mock_get_config.return_value = SimpleNamespace(
        scraping=SimpleNamespace(
            user_agent="test-agent",
            availability_recheck=SimpleNamespace(request_timeout_sec=5.0),
        )
    )
    client = MagicMock()
    client.get.side_effect = httpx.TimeoutException("slow")
    result = check_listing("olx", "https://www.olx.com.br/vi/1", client=client)
    assert result.status == AvailabilityStatus.UNKNOWN
    assert result.reason == "timeout"


@patch("adapters.queue.tasks.SessionLocal")
@patch("adapters.queue.tasks.get_config")
def test_recheck_task_skips_when_disabled(mock_get_config, mock_session_local):
    from adapters.queue import tasks as tasks_mod

    mock_get_config.return_value = SimpleNamespace(
        scraping=SimpleNamespace(
            availability_recheck=SimpleNamespace(enabled=False),
        )
    )
    result = tasks_mod.recheck_listing_availability.run()
    assert result == {"status": "skipped", "checked": 0}
    mock_session_local.assert_not_called()


@patch("adapters.queue.tasks.SessionLocal")
@patch("adapters.queue.tasks.get_config")
def test_recheck_task_empty_batch(mock_get_config, mock_session_local):
    from adapters.queue import tasks as tasks_mod

    mock_get_config.return_value = SimpleNamespace(
        scraping=SimpleNamespace(
            user_agent="ua",
            availability_recheck=SimpleNamespace(
                enabled=True,
                batch_size=10,
                stale_after_hours=24,
                request_timeout_sec=10.0,
            ),
        )
    )
    session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = session
    session.execute.return_value.fetchall.return_value = []

    result = tasks_mod.recheck_listing_availability.run()
    assert result["status"] == "empty"
    assert result["checked"] == 0


@patch("adapters.scrapers.http_client.create_scraper_http_client")
@patch("adapters.queue.tasks.SessionLocal")
@patch("adapters.queue.tasks.get_config")
def test_recheck_task_processes_mixed_results(
    mock_get_config,
    mock_session_local,
    mock_create_client,
):
    from adapters.queue import tasks as tasks_mod

    mock_get_config.return_value = SimpleNamespace(
        scraping=SimpleNamespace(
            user_agent="ua",
            availability_recheck=SimpleNamespace(
                enabled=True,
                batch_size=50,
                stale_after_hours=24,
                request_timeout_sec=10.0,
            ),
        )
    )
    session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = session
    session.execute.return_value.fetchall.return_value = [
        ("l1", "p1", "quintoandar", "rent", "https://qa/1"),
        ("l2", "p2", "olx", "sale", "https://olx/2"),
        ("l3", "p3", "olx", "rent", "https://olx/3"),
    ]
    mock_create_client.return_value = MagicMock()

    with patch(
        "adapters.scrapers.availability.check_listing",
        side_effect=[
            AvailabilityResult(AvailabilityStatus.UNAVAILABLE, "dead"),
            AvailabilityResult(AvailabilityStatus.AVAILABLE, "ok"),
            AvailabilityResult(AvailabilityStatus.UNKNOWN, "cf"),
        ],
    ) as check:
        with patch(
            "adapters.scrapers.availability.deactivate_listing_and_maybe_property",
            return_value={
                "listing_id": "l1",
                "property_deactivated": True,
                "remaining_active_listings": 0,
            },
        ):
            result = tasks_mod.recheck_listing_availability.run(batch_size=3)

    assert result["status"] == "ok"
    assert result["checked"] == 3
    assert result["unavailable"] == 1
    assert result["available"] == 1
    assert result["unknown"] == 1
    assert result["properties_deactivated"] == 1
    assert check.call_count == 3
    session.commit.assert_called_once()
