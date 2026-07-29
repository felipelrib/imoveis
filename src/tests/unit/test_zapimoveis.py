"""Unit tests for ZapImóveis scraper helpers and normalize (BIN-127)."""

from __future__ import annotations

import collections
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from adapters.scrapers.zapimoveis import (
    ZapImoveisScraper,
    _city_state_from_slug,
    _resolve_image_url,
    extract_zapimoveis_description,
)
from core.entities import PropertyCandidate
from core.exceptions import CircuitBreakerOpenError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "scrapers"

JSONLD_ONLY_SEARCH_HTML = """<!DOCTYPE html><html><head><title>t</title></head><body>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"ItemList",
"numberOfItems":1,"itemListElement":[{"@type":"ListItem","position":1,"item":{
"@type":"Product","@id":"5551234","name":"Apartamento incr\u00edvel",
"url":"https://www.zapimoveis.com.br/imovel/aluguel-apartamento-id-5551234/",
"description":"Otimo apartamento","image":["https://img.example.com/1.jpg",
"https://img.example.com/2.jpg"],"numberOfBedrooms":2,"numberOfBathroomsTotal":1,
"floorSize":{"@type":"QuantitativeValue","value":60},
"address":{"@type":"PostalAddress","addressLocality":"Belo Horizonte",
"addressRegion":"MG","streetAddress":"Rua X"},
"offers":{"@type":"Offer","availability":"https://schema.org/InStock","price":2200,
"priceCurrency":"BRL","potentialAction":{"@type":"RentAction"},
"additionalProperty":{"@type":"PropertyValue","name":"Condominium Fee","value":300}}}}]}
</script>
</body></html>"""


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


def test_normalize_missing_id_raises(zap_scraper):
    with pytest.raises(ValueError, match="missing id"):
        zap_scraper.normalize({"prices": {"rental": {"value": 1000}}})


# ---------------------------------------------------------------------------
# JSON-LD-only fallback (no Flight payload present)
# ---------------------------------------------------------------------------


class TestJsonLdFallback:
    def test_extract_listings_falls_back_to_jsonld_when_no_flight(self, zap_scraper):
        assert "__next_f" not in JSONLD_ONLY_SEARCH_HTML
        listings = zap_scraper.extract_listings(JSONLD_ONLY_SEARCH_HTML)
        assert len(listings) == 1
        raw = listings[0]
        assert raw["id"] == "5551234"
        assert raw["business"] == "RENTAL"

        result = zap_scraper.normalize(raw)
        PropertyCandidate(**result)
        assert result["platform_id"] == "5551234"
        assert result["price"] == 2200.0
        assert result["bedrooms"] == 2
        assert result["bathrooms"] == 1
        assert result["area_m2"] == 60.0
        assert result["image_urls"] == [
            "https://img.example.com/1.jpg",
            "https://img.example.com/2.jpg",
        ]
        rent = next(row for row in result["listings"] if row["listing_type"] == "rent")
        assert rent["condo_fee"] == pytest.approx(300.0)

    def test_extract_description_falls_back_to_jsonld_product(self):
        html = (
            "<html><body>"
            '<script type="application/ld+json">'
            '{"@type":"Product","description":"  Excelente apartamento no centro  "}'
            "</script></body></html>"
        )
        assert extract_zapimoveis_description(html) == "Excelente apartamento no centro"

    def test_extract_description_returns_empty_when_nothing_found(self):
        assert extract_zapimoveis_description("<html></html>") == ""


# ---------------------------------------------------------------------------
# _product_to_raw()
# ---------------------------------------------------------------------------


class TestProductToRaw:
    def test_rent_product_maps_prices_and_amenities(self):
        product = {
            "@id": "111",
            "name": "Apto",
            "url": "https://example.test/imovel/id-111/",
            "description": "desc",
            "image": "https://img.example.com/a.jpg",
            "numberOfBedrooms": 1,
            "numberOfBathroomsTotal": 1,
            "floorSize": {"value": 45},
            "address": {
                "addressLocality": "BH",
                "addressRegion": "MG",
                "streetAddress": "Rua A",
            },
            "offers": {
                "price": 1500,
                "potentialAction": {"@type": "RentAction"},
                "additionalProperty": {"name": "Condominium Fee", "value": 200},
            },
        }
        raw = ZapImoveisScraper._product_to_raw(product)
        assert raw["id"] == "111"
        assert raw["business"] == "RENTAL"
        assert raw["prices"]["rental"]["value"] == 1500
        assert raw["prices"]["rental"]["condominium"] == 200
        assert raw["prices"]["sale"] is None
        assert raw["amenities"]["usableAreas"] == [45]
        assert raw["amenities"]["bedrooms"] == [1]
        assert raw["medias"]["images"] == [{"dangerousSrc": "https://img.example.com/a.jpg"}]

    def test_sale_product_uses_buy_action_and_url_id_fallback(self):
        product = {
            "url": "https://example.test/imovel/venda-casa-id-222222/",
            "offers": {"price": 500000, "potentialAction": {"@type": "BuyAction"}},
        }
        raw = ZapImoveisScraper._product_to_raw(product)
        assert raw["id"] == "222222"
        assert raw["business"] == "SALE"
        assert raw["prices"]["sale"]["value"] == 500000
        assert raw["prices"]["rental"] is None

    def test_product_without_offers_has_no_price(self):
        raw = ZapImoveisScraper._product_to_raw({"@id": "333"})
        assert raw["prices"] == {"rental": None, "sale": None}
        assert raw["business"] == "RENTAL"


# ---------------------------------------------------------------------------
# _merge_dual_window_prices()
# ---------------------------------------------------------------------------


class TestMergeDualWindowPrices:
    def test_merges_rent_and_sale_into_kept(self):
        kept = {
            "id": "1",
            "_zap_listing_type": "rent",
            "prices": {"rental": {"value": 2000}, "sale": None},
        }
        incoming = {
            "id": "1",
            "_zap_listing_type": "sale",
            "prices": {"rental": None, "sale": {"value": 400000}},
        }
        assert ZapImoveisScraper._merge_dual_window_prices(kept, incoming) is True
        assert kept["prices"]["rental"]["value"] == 2000
        assert kept["prices"]["sale"]["value"] == 400000
        assert "_zap_listing_type" not in kept

    def test_same_type_is_noop(self):
        kept = {"_zap_listing_type": "rent", "prices": {"rental": {"value": 2000}}}
        incoming = {"_zap_listing_type": "rent", "prices": {"rental": {"value": 2100}}}
        assert ZapImoveisScraper._merge_dual_window_prices(kept, incoming) is False
        assert kept["prices"] == {"rental": {"value": 2000}}

    def test_missing_stamp_is_noop(self):
        kept = {"prices": {"rental": {"value": 2000}}}
        incoming = {"_zap_listing_type": "sale", "prices": {"sale": {"value": 1}}}
        assert ZapImoveisScraper._merge_dual_window_prices(kept, incoming) is False


# ---------------------------------------------------------------------------
# _city_state_from_slug()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("slug", "expected"),
    [
        ("sp+campinas", ("Campinas", "SP")),
        ("sp+sao-paulo", ("São Paulo", "SP")),
        ("mg+belo-horizonte", ("Belo Horizonte", "MG")),
        ("unknown-slug", ("Belo Horizonte", "MG")),
        ("", ("Belo Horizonte", "MG")),
    ],
)
def test_city_state_from_slug(slug, expected):
    assert _city_state_from_slug(slug) == expected


# ---------------------------------------------------------------------------
# _resolve_image_url()
# ---------------------------------------------------------------------------


def test_resolve_image_url_substitutes_template_tokens():
    src = "https://img.example.com/{width}x{height}/{action}/{description}.jpg"
    assert (
        _resolve_image_url(src)
        == "https://img.example.com/614x297/fit-in/foto.jpg"
    )


def test_resolve_image_url_empty_string_returns_empty():
    assert _resolve_image_url("") == ""


# ---------------------------------------------------------------------------
# cities parsing from extra config
# ---------------------------------------------------------------------------


class TestParseCities:
    def test_multi_city_from_extra(self):
        scraper = ZapImoveisScraper(
            "zapimoveis",
            {
                "extra": {
                    "cities": [
                        {
                            "city_slug": "mg+belo-horizonte",
                            "neighborhoods": [{"slug": "savassi"}],
                        },
                        {"city_slug": "sp+campinas", "neighborhoods": ["centro"]},
                    ]
                }
            },
        )
        assert [c["city_slug"] for c in scraper._cities] == [
            "mg+belo-horizonte",
            "sp+campinas",
        ]
        assert scraper._city_neighborhoods["mg+belo-horizonte"] == ["savassi"]
        assert scraper._city_neighborhoods["sp+campinas"] == ["centro"]

    def test_falls_back_to_single_city_slug(self):
        scraper = ZapImoveisScraper("zapimoveis", {"extra": {"city_slug": "sp+sao-paulo"}})
        assert [c["city_slug"] for c in scraper._cities] == ["sp+sao-paulo"]

    def test_defaults_when_extra_missing(self):
        scraper = ZapImoveisScraper("zapimoveis", {})
        assert [c["city_slug"] for c in scraper._cities] == ["mg+belo-horizonte"]


# ---------------------------------------------------------------------------
# _fetch_window() — mocked HTTP / extract_listings
# ---------------------------------------------------------------------------


class TestFetchWindow:
    def test_collects_single_page_from_cassette(self, zap_scraper):
        zap_scraper._max_pages = 1
        page_html = (FIXTURES / "zapimoveis_search.html").read_text(encoding="utf-8")
        zap_scraper._throttled_request = MagicMock(
            return_value=MagicMock(status_code=200, text=page_html)
        )
        collected, saturated = zap_scraper._fetch_window(
            "aluguel", "apartamentos", 500, 15000, "mg+belo-horizonte", None
        )
        assert len(collected) == 1
        assert collected[0]["_zap_listing_type"] == "rent"
        assert collected[0]["_zap_city_slug"] == "mg+belo-horizonte"
        assert saturated is False

    def test_stops_on_cloudflare_403(self, zap_scraper):
        zap_scraper._throttled_request = MagicMock(
            return_value=MagicMock(status_code=403, text="")
        )
        collected, saturated = zap_scraper._fetch_window(
            "aluguel", "apartamentos", 500, 15000, "mg+belo-horizonte", None
        )
        assert collected == []
        assert saturated is False

    def test_stops_on_circuit_open(self, zap_scraper):
        zap_scraper._throttled_request = MagicMock(
            side_effect=CircuitBreakerOpenError("open")
        )
        collected, saturated = zap_scraper._fetch_window(
            "aluguel", "apartamentos", 500, 15000, "mg+belo-horizonte", None
        )
        assert collected == []
        assert saturated is False

    def test_stops_on_unexpected_error(self, zap_scraper):
        zap_scraper._throttled_request = MagicMock(side_effect=RuntimeError("boom"))
        collected, saturated = zap_scraper._fetch_window(
            "aluguel", "apartamentos", 500, 15000, "mg+belo-horizonte", None
        )
        assert collected == []
        assert saturated is False

    def test_marks_saturated_with_full_pages(self, zap_scraper):
        zap_scraper._max_pages = 2
        zap_scraper._throttled_request = MagicMock(
            return_value=MagicMock(status_code=200, text="x")
        )
        zap_scraper.extract_listings = MagicMock(
            side_effect=[
                [{"id": str(i)} for i in range(10)],
                [{"id": str(i)} for i in range(10, 20)],
            ]
        )
        collected, saturated = zap_scraper._fetch_window(
            "aluguel", "apartamentos", 500, 2000, "mg+belo-horizonte", None
        )
        assert len(collected) == 20
        assert saturated is True


# ---------------------------------------------------------------------------
# _fan_out_saturated_window()
# ---------------------------------------------------------------------------


class TestFanOutSaturatedWindow:
    def test_splits_price_band_when_filter_effective(self, zap_scraper):
        collected = [{"id": "1", "prices": {"rental": {"value": 1000}, "sale": None}}]
        queue: collections.deque = collections.deque()
        result = zap_scraper._fan_out_saturated_window(
            ("aluguel", "apartamentos", 500, 2000, "mg+belo-horizonte", None),
            collected,
            queue,
        )
        assert result is True
        assert len(queue) == 2

    def test_skips_split_when_price_filter_ineffective(self, zap_scraper):
        collected = [{"id": "1", "prices": {"rental": {"value": 9000}, "sale": None}}]
        queue: collections.deque = collections.deque()
        result = zap_scraper._fan_out_saturated_window(
            ("aluguel", "apartamentos", 500, 2000, "mg+belo-horizonte", None),
            collected,
            queue,
        )
        assert result is False
        assert len(queue) == 0

    def test_expands_neighborhoods_when_atomic(self, zap_scraper):
        zap_scraper._city_neighborhoods["mg+belo-horizonte"] = ["savassi", "lourdes"]
        collected = [{"id": "1", "prices": {"rental": {"value": 500}, "sale": None}}]
        queue: collections.deque = collections.deque()
        result = zap_scraper._fan_out_saturated_window(
            ("aluguel", "apartamentos", 500, 500, "mg+belo-horizonte", None),
            collected,
            queue,
        )
        assert result is True
        assert len(queue) == 2

    def test_truncates_when_atomic_and_no_neighborhoods(self, zap_scraper):
        zap_scraper._city_neighborhoods["mg+belo-horizonte"] = []
        collected = [{"id": "1", "prices": {"rental": {"value": 500}, "sale": None}}]
        queue: collections.deque = collections.deque()
        result = zap_scraper._fan_out_saturated_window(
            ("aluguel", "apartamentos", 500, 500, "mg+belo-horizonte", "savassi"),
            collected,
            queue,
        )
        assert result is False
        assert len(queue) == 0


# ---------------------------------------------------------------------------
# Lifecycle: start / close / _throttled_request / fetch_description
# ---------------------------------------------------------------------------


class TestZapFetchLifecycle:
    def test_start_creates_http_session_and_circuit_breaker(self, zap_scraper):
        session = MagicMock()
        with patch.object(
            zap_scraper, "create_http_session", return_value=session
        ) as create_session, patch(
            "adapters.scrapers.zapimoveis.RedisCircuitBreaker"
        ) as circuit_breaker:
            zap_scraper.start()

        create_session.assert_called_once_with()
        assert zap_scraper.session is session
        session.headers.update.assert_called_once()
        circuit_breaker.assert_called_once_with(
            platform="zapimoveis", failure_threshold=5, cooldown_seconds=120
        )

    def test_close_closes_existing_session(self, zap_scraper):
        zap_scraper.session = MagicMock()
        zap_scraper.close()
        zap_scraper.session.close.assert_called_once()

    def test_close_without_session_is_a_noop(self, zap_scraper):
        zap_scraper.close()

    def test_throttled_request_rejects_open_circuit(self, zap_scraper):
        zap_scraper._cb = MagicMock()
        zap_scraper._cb.is_open.return_value = True
        with pytest.raises(CircuitBreakerOpenError, match="circuit breaker is open"):
            zap_scraper._throttled_request("https://example.test")

    def test_throttled_request_records_success(self, zap_scraper):
        zap_scraper.session = MagicMock()
        zap_scraper._cb = MagicMock()
        zap_scraper._cb.is_open.return_value = False
        response = MagicMock(status_code=200)
        zap_scraper.session.get.return_value = response
        with patch("adapters.scrapers.zapimoveis.random.uniform", return_value=0), patch(
            "adapters.scrapers.zapimoveis.time.sleep"
        ) as sleep:
            assert zap_scraper._throttled_request("https://example.test") is response
        sleep.assert_called_once_with(0)
        zap_scraper._cb.record_success.assert_called_once()

    def test_throttled_request_records_failure_for_rate_limit(self, zap_scraper):
        zap_scraper.session = MagicMock()
        zap_scraper._cb = MagicMock()
        zap_scraper._cb.is_open.return_value = False
        zap_scraper.session.get.return_value = MagicMock(status_code=429)
        with patch("adapters.scrapers.zapimoveis.random.uniform", return_value=0), patch(
            "adapters.scrapers.zapimoveis.time.sleep"
        ):
            zap_scraper._throttled_request("https://example.test")
        zap_scraper._cb.record_failure.assert_called_once()

    def test_fetch_description_blank_url_returns_empty(self, zap_scraper):
        assert zap_scraper.fetch_description("   ") == ""

    def test_fetch_description_circuit_open_returns_empty(self, zap_scraper):
        zap_scraper._throttled_request = MagicMock(
            side_effect=CircuitBreakerOpenError("open")
        )
        assert zap_scraper.fetch_description("https://example.test") == ""

    def test_fetch_description_unexpected_error_returns_empty(self, zap_scraper):
        zap_scraper._throttled_request = MagicMock(side_effect=RuntimeError("boom"))
        assert zap_scraper.fetch_description("https://example.test") == ""

    def test_fetch_description_non_200_returns_empty(self, zap_scraper):
        zap_scraper._throttled_request = MagicMock(
            return_value=MagicMock(status_code=404, text="")
        )
        assert zap_scraper.fetch_description("https://example.test") == ""

    def test_fetch_description_extracts_text(self, zap_scraper):
        html = (FIXTURES / "zapimoveis_detail.html").read_text(encoding="utf-8")
        zap_scraper._throttled_request = MagicMock(
            return_value=MagicMock(status_code=200, text=html)
        )
        text = zap_scraper.fetch_description("https://example.test")
        assert "Liberdade" in text

    def test_fetch_description_empty_result_logs_and_returns_empty(self, zap_scraper):
        zap_scraper._throttled_request = MagicMock(
            return_value=MagicMock(status_code=200, text="<html></html>")
        )
        assert zap_scraper.fetch_description("https://example.test") == ""


# ---------------------------------------------------------------------------
# fetch_pages() — end-to-end window queue behavior
# ---------------------------------------------------------------------------


class TestFetchPages:
    def test_fetch_pages_yields_collected_listings(self, zap_scraper):
        zap_scraper._cities = [{"city_slug": "mg+belo-horizonte", "neighborhoods": []}]
        zap_scraper._city_neighborhoods = {"mg+belo-horizonte": []}
        zap_scraper._price_rent = (500, 15000)
        zap_scraper._price_sale = (100000, 5000000)
        zap_scraper._fetch_window = MagicMock(
            return_value=([{"id": "1", "prices": {"rental": {"value": 1000}}}], False)
        )
        listings = list(zap_scraper.fetch_pages({"scrape_type": "rent"}))
        assert len(listings) >= 1
        assert listings[0]["id"] == "1"

    def test_fetch_pages_skips_empty_unsaturated_windows(self, zap_scraper):
        zap_scraper._cities = [{"city_slug": "mg+belo-horizonte", "neighborhoods": []}]
        zap_scraper._city_neighborhoods = {"mg+belo-horizonte": []}
        zap_scraper._fetch_window = MagicMock(return_value=([], False))
        assert list(zap_scraper.fetch_pages({"scrape_type": "rent"})) == []

    def test_fetch_pages_invalid_checkpoint_scrapes_both(self, zap_scraper):
        zap_scraper._cities = [{"city_slug": "mg+belo-horizonte", "neighborhoods": []}]
        zap_scraper._city_neighborhoods = {"mg+belo-horizonte": []}
        zap_scraper._fetch_window = MagicMock(return_value=([], False))
        assert list(zap_scraper.fetch_pages("not-a-checkpoint")) == []
        # 2 businesses x 2 unit types = 4 windows fetched.
        assert zap_scraper._fetch_window.call_count == 4
