"""Unit tests that replay committed scraper HTML cassettes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from adapters.scrapers.olx import OLXScraper
from adapters.scrapers.quintoandar import QuintoAndarScraper

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "scrapers"


def _load_next_data(name: str) -> dict:
    html = (FIXTURES / name).read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    assert script is not None and script.string, f"missing __NEXT_DATA__ in {name}"
    return json.loads(script.string)


@pytest.fixture
def qa_scraper():
    return QuintoAndarScraper(
        "quintoandar",
        {"rate_limit": 30, "extra": {"city_slug": "belo-horizonte-mg-brasil"}},
    )


@pytest.fixture
def olx_scraper():
    return OLXScraper("olx", {"rate_limit": 20, "jitter_min": 0, "jitter_max": 0.1})


class TestQuintoAndarCassettes:
    def test_search_cassette_extracts_and_normalizes(self, qa_scraper):
        data = _load_next_data("quintoandar_search.html")
        houses = data["props"]["pageProps"]["initialState"]["houses"]
        valid = {k: v for k, v in houses.items() if isinstance(v, dict)}
        assert "895549038" in valid

        result = qa_scraper.normalize(valid["895549038"])
        assert result["platform"] == "quintoandar"
        assert result["platform_id"] == "895549038"
        assert result["price"] == 929
        assert result["area_m2"] == 38.0
        assert result["bedrooms"] == 1
        assert result["location"] == {"lat": -19.937, "lon": -43.938}
        rent = next(row for row in result["listings"] if row["listing_type"] == "rent")
        assert rent["condo_fee"] == pytest.approx(179.0)
        assert rent["raw_json"]["fees_bundled"] is True

    def test_detail_cassette_prefers_separate_fees(self, qa_scraper):
        data = _load_next_data("quintoandar_detail.html")
        house = data["props"]["pageProps"]["initialState"]["houses"]["895549038"]
        result = qa_scraper.normalize(house)
        rent = next(row for row in result["listings"] if row["listing_type"] == "rent")
        assert rent["condo_fee"] == pytest.approx(120.0)
        assert rent["iptu"] == pytest.approx(59.0)
        assert rent["raw_json"].get("fees_bundled") is None


class TestOLXCassettes:
    def test_search_cassette_extracts_and_normalizes(self, olx_scraper):
        data = _load_next_data("olx_search.html")
        listings = olx_scraper._extract_listings(data)
        assert len(listings) == 1
        assert listings[0]["list_id"] == "123456789"

        result = olx_scraper.normalize(listings[0])
        assert result["platform"] == "olx"
        assert result["platform_id"] == "123456789"
        assert result["title"] == "Apartamento 2 quartos em Savassi"
        # normalize() adds condo fee (650) from properties onto the listing value
        assert result["price"] == 4150.0
        assert result["bedrooms"] == 2
        assert result["area_m2"] == 75.0
        assert result["location"] == {"lat": -19.9320, "lon": -43.9380}

    def test_flight_search_cassette_extracts_and_normalizes(self, olx_scraper):
        """OLX listing pages ship Flight RSC ads (no __NEXT_DATA__)."""
        html = (FIXTURES / "olx_search_flight.html").read_text(encoding="utf-8")
        assert "__NEXT_DATA__" not in html
        listings = olx_scraper._parse_listings_html(html, url="https://example.test/flight")
        assert len(listings) == 1
        assert listings[0]["listId"] == 1490781405

        result = olx_scraper.normalize(listings[0])
        assert result["platform"] == "olx"
        assert result["platform_id"] == "1490781405"
        assert result["title"] == "Apartamento 2 quartos em Savassi"
        assert result["price"] == 4150.0  # 3500 + condo 650
        assert result["bedrooms"] == 2
        assert result["area_m2"] == 75.0
        assert result["parking"] == 1
        assert result["props_json"]["neighborhood"] == "Savassi"
        assert result["listings"][0]["listing_type"] == "rent"
        assert result["image_urls"] == ["https://img.olx.com.br/img1.jpg"]
