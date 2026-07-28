"""Extra branch coverage for listing description extractors + fetch (BIN-105)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from adapters.scrapers.listing_description import (
    extract_olx_description,
    extract_quintoandar_description,
)
from adapters.scrapers.olx import OLXScraper
from adapters.scrapers.quintoandar import QuintoAndarScraper
from core.exceptions import CircuitBreakerOpenError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "scrapers"


def test_qa_prefers_remarks_over_generated():
    html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"initialState":{"house":{"houseInfo":{'
        '"remarks":"Seller remarks here with enough length.",'
        '"generatedDescription":{"longDescription":"Generated long text here."},'
        '"description":"legacy"'
        '}}}}}}'
        "</script>"
    )
    assert extract_quintoandar_description(html).startswith("Seller remarks")


def test_qa_falls_back_to_generated_string():
    html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"initialState":{"house":{"houseInfo":{'
        '"generatedDescription":"Generated as plain string with enough chars."'
        '}}}}}}'
        "</script>"
    )
    assert "plain string" in extract_quintoandar_description(html)


def test_qa_falls_back_to_houses_map():
    html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"initialState":{"house":{},"houses":{'
        '"1":{"description":"From houses map with enough characters."},'
        '"bad":"skip"'
        '}}}}}'
        "</script>"
    )
    assert "houses map" in extract_quintoandar_description(html)


def test_qa_invalid_next_data_returns_empty():
    html = '<script id="__NEXT_DATA__" type="application/json">{not-json}</script>'
    assert extract_quintoandar_description(html) == ""


def test_olx_from_ad_data_key():
    html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"adData":{"listId":1,'
        '"body":"Body via adData key with enough characters."}}}}'
        "</script>"
    )
    assert "adData" in extract_olx_description(html)


def test_olx_from_nested_walk():
    html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"wrapper":{"listId":99,'
        '"body":"Nested walk body with enough characters here."}}}}'
        "</script>"
    )
    assert "Nested walk" in extract_olx_description(html)


def test_olx_regex_fallback_without_next_data():
    html = '<html>"body":"Regex fallback body text with enough characters."</html>'
    assert "Regex fallback" in extract_olx_description(html)


def test_olx_detail_cassette_still_works():
    html = (FIXTURES / "olx_detail.html").read_text(encoding="utf-8")
    assert "panorâmica" in extract_olx_description(html)


@pytest.fixture
def qa_scraper():
    scraper = QuintoAndarScraper(
        "quintoandar",
        {"rate_limit": 30, "extra": {"city_slug": "belo-horizonte-mg-brasil"}},
    )
    scraper.session = MagicMock()
    scraper._cb = MagicMock()
    scraper._cb.is_open.return_value = False
    return scraper


@pytest.fixture
def olx_scraper():
    scraper = OLXScraper("olx", {"rate_limit": 20, "jitter_min": 0, "jitter_max": 0.01})
    scraper.session = MagicMock()
    scraper._cb = MagicMock()
    scraper._cb.is_open.return_value = False
    return scraper


def test_qa_fetch_description_parses_html(qa_scraper):
    html = (FIXTURES / "quintoandar_detail.html").read_text(encoding="utf-8")
    response = MagicMock(status_code=200, text=html)
    with patch.object(qa_scraper, "_throttled_request", return_value=response):
        text = qa_scraper.fetch_description("https://www.quintoandar.com.br/imovel/1")
    assert "Alvorada" in text


def test_qa_fetch_description_http_error(qa_scraper):
    response = MagicMock(status_code=404, text="")
    with patch.object(qa_scraper, "_throttled_request", return_value=response):
        assert qa_scraper.fetch_description("https://www.quintoandar.com.br/imovel/1") == ""


def test_qa_fetch_description_circuit_open(qa_scraper):
    with patch.object(
        qa_scraper, "_throttled_request", side_effect=CircuitBreakerOpenError("open")
    ):
        assert qa_scraper.fetch_description("https://www.quintoandar.com.br/imovel/1") == ""


def test_qa_fetch_description_blank_url(qa_scraper):
    assert qa_scraper.fetch_description("") == ""


def test_olx_fetch_description_parses_html(olx_scraper):
    html = (FIXTURES / "olx_detail.html").read_text(encoding="utf-8")
    response = MagicMock(status_code=200, text=html)
    with patch.object(olx_scraper, "_throttled_request", return_value=response):
        text = olx_scraper.fetch_description("https://www.olx.com.br/detalhes/1")
    assert "panorâmica" in text


def test_olx_fetch_description_http_error(olx_scraper):
    response = MagicMock(status_code=403, text="blocked")
    with patch.object(olx_scraper, "_throttled_request", return_value=response):
        assert olx_scraper.fetch_description("https://www.olx.com.br/detalhes/1") == ""


def test_olx_fetch_description_circuit_open(olx_scraper):
    with patch.object(
        olx_scraper, "_throttled_request", side_effect=CircuitBreakerOpenError("open")
    ):
        assert olx_scraper.fetch_description("https://www.olx.com.br/detalhes/1") == ""
