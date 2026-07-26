"""Unit tests for listing availability classifiers (BIN-80)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from adapters.scrapers.availability import (
    AvailabilityStatus,
    classify_response,
    deactivate_listing_and_maybe_property,
    parse_olx_availability,
    parse_quintoandar_availability,
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


def test_classify_response_dispatches():
    html = _load("olx_unavailable_410.html")
    result = classify_response(
        "olx",
        status_code=410,
        html=html,
        request_url="https://www.olx.com.br/vi/1",
    )
    assert result.status == AvailabilityStatus.UNAVAILABLE


def test_deactivate_listing_keeps_property_when_sibling_active():
    session = MagicMock()
    # UPDATE listing
    # SELECT property_id
    # SELECT remaining count = 1
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
        MagicMock(),  # UPDATE properties
    ]
    summary = deactivate_listing_and_maybe_property(session, "listing-1")
    assert summary["property_deactivated"] is True
    assert session.execute.call_count == 4
