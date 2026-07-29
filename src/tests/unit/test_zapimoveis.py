"""Unit tests for ZapImóveis scraper helpers and normalize (BIN-127)."""

from __future__ import annotations

from pathlib import Path

import pytest

from adapters.scrapers.zapimoveis import (
    ZapImoveisScraper,
    extract_zapimoveis_description,
)
from core.entities import PropertyCandidate

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "scrapers"


@pytest.fixture
def zap_scraper():
    return ZapImoveisScraper(
        "zapimoveis",
        {
            "rate_limit": 20,
            "jitter_min": 0,
            "jitter_max": 0.1,
            "extra": {
                "max_pages": 2,
                "city_slug": "mg+belo-horizonte",
                "price_rent": [500, 15000],
                "price_sale": [100000, 5000000],
            },
        },
    )


def test_extract_and_normalize_search_cassette(zap_scraper):
    html = (FIXTURES / "zapimoveis_search.html").read_text(encoding="utf-8")
    listings = zap_scraper.extract_listings(html)
    assert len(listings) == 1
    assert listings[0]["id"] == "2877382105"

    result = zap_scraper.normalize(listings[0])
    PropertyCandidate(**result)
    assert result["platform"] == "zapimoveis"
    assert result["platform_id"] == "2877382105"
    assert result["price"] == 4700.0
    assert result["area_m2"] == 42.0
    assert result["bedrooms"] == 1
    assert result["bathrooms"] == 1
    assert result["parking"] == 1
    assert result["location"] == {"lat": -19.930459, "lon": -43.93796}
    assert "Lourdes" in (result["address"] or "")
    rent = next(row for row in result["listings"] if row["listing_type"] == "rent")
    assert rent["condo_fee"] == pytest.approx(480.0)
    assert rent["iptu"] == pytest.approx(4940.0)
    assert rent["url"].startswith("https://www.zapimoveis.com.br/")
    assert rent["accepts_pets"] is True
    assert result["image_urls"]
    assert "{description}" not in result["image_urls"][0]


def test_normalize_rejects_missing_price(zap_scraper):
    with pytest.raises(ValueError, match="Invalid Zap price"):
        zap_scraper.normalize({"id": "1", "prices": {"rental": None, "sale": None}})


def test_normalize_sale_only(zap_scraper):
    raw = {
        "id": "99",
        "title": "Casa à venda",
        "href": "https://www.zapimoveis.com.br/imovel/venda-casa-id-99/",
        "prices": {
            "rental": None,
            "sale": {"value": 850000, "condominium": None, "iptu": 1200},
        },
        "address": {
            "city": "Belo Horizonte",
            "stateAcronym": "MG",
            "neighborhood": "Savassi",
            "coordinates": {"latitude": -19.9, "longitude": -43.9},
        },
        "amenities": {"usableAreas": [100], "bedrooms": [3], "bathrooms": [2]},
        "medias": {"images": []},
        "unitType": "HOME",
    }
    result = zap_scraper.normalize(raw)
    assert result["price"] == 850000.0
    assert len(result["listings"]) == 1
    assert result["listings"][0]["listing_type"] == "sale"


def test_detail_description_extractable():
    html = (FIXTURES / "zapimoveis_detail.html").read_text(encoding="utf-8")
    text = extract_zapimoveis_description(html)
    assert text
    assert "Liberdade" in text


def test_build_search_url_includes_price_and_page(zap_scraper):
    url = zap_scraper._build_search_url(
        "aluguel", "apartamentos", "mg+belo-horizonte", 500, 2000, 2, None
    )
    assert url.startswith(
        "https://www.zapimoveis.com.br/aluguel/apartamentos/mg+belo-horizonte/"
    )
    assert "precoMinimo=500" in url
    assert "precoMaximo=2000" in url
    assert "pagina=2" in url


def test_price_filter_effective_requires_majority_in_band(zap_scraper):
    in_band = {
        "id": "1",
        "prices": {"rental": {"value": 1000}, "sale": None},
    }
    out_of_band = {
        "id": "2",
        "prices": {"rental": {"value": 9000}, "sale": None},
    }
    assert zap_scraper._price_filter_effective([in_band, in_band], 500, 2000, "rent")
    assert not zap_scraper._price_filter_effective(
        [out_of_band, out_of_band, in_band], 500, 2000, "rent"
    )


def test_registry_resolves_zapimoveis():
    import adapters.scrapers.zapimoveis  # noqa: F401
    from adapters.scrapers.registry import ScraperRegistry

    assert "zapimoveis" in ScraperRegistry.available()
    scraper = ScraperRegistry.get("zapimoveis", {"extra": {}})
    assert isinstance(scraper, ZapImoveisScraper)
