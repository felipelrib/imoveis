"""Unit tests for the OLX scraper."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from adapters.scrapers.olx import OLXScraper
from core.exceptions import CircuitBreakerOpenError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_OLX_LISTING = {
    "list_id": "123456789",
    "subject": "Apartamento 2 quartos em Savassi",
    "body": "Apartamento bem localizado com vista panorâmica.",
    "value": 3500.0,
    "location": {
        "lat": -19.9320,
        "lon": -43.9380,
        "neighborhood": "Savassi",
        "neighborhoodName": "Savassi",
        "city": "Belo Horizonte",
        "cityName": "Belo Horizonte",
        "address": "Rua Pernambuco, 500",
    },
    "images": [
        {"src": "https://img.olx.com.br/img1.jpg"},
        {"src": "https://img.olx.com.br/img2.jpg"},
    ],
    "properties": [
        {"label": "Área", "value": "75m²"},
        {"label": "Quartos", "value": "2"},
        {"label": "Banheiros", "value": "1"},
        {"label": "Vagas", "value": "1"},
        {"label": "Condomínio", "value": "650"},
    ],
    "url": "https://www.olx.com.br/imovel/aluguel/apartamentos/mg/belo-horizonte/detalhes/123456789",
}


@pytest.fixture
def scraper():
    config = {
        "rate_limit": 20,
        "jitter_min": 0,
        "jitter_max": 0.1,
        "extra": {"max_pages": 2},
    }
    return OLXScraper("olx", config)


@pytest.fixture
def scraper_no_extra():
    """Config with no jitter_max or extra overrides to test defaults."""
    config = {
        "rate_limit": 20,
    }
    return OLXScraper("olx", config)


# ---------------------------------------------------------------------------
# normalize() tests
# ---------------------------------------------------------------------------


class TestOLXNormalize:
    def test_basic_listing(self, scraper):
        result = scraper.normalize(SAMPLE_OLX_LISTING)

        assert result["platform"] == "olx"
        assert result["platform_id"] == "123456789"
        assert result["title"] == "Apartamento 2 quartos em Savassi"
        assert result["price"] == 4150.0
        assert result["area_m2"] == 75.0
        assert result["bedrooms"] == 2
        assert result["bathrooms"] == 1
        assert result["parking"] == 1
        assert result["location"] == {"lat": -19.9320, "lon": -43.9380}
        assert result["address"] is not None
        assert "Savassi" in result["address"]

    def test_listings_array(self, scraper):
        result = scraper.normalize(SAMPLE_OLX_LISTING)
        assert len(result["listings"]) == 1
        listing = result["listings"][0]
        assert listing["platform"] == "olx"
        assert listing["platform_listing_id"] == "123456789"
        assert listing["listing_type"] == "rent"
        assert listing["price"] == 4150.0
        assert listing["currency"] == "BRL"

    def test_fees_bundled_false_for_separate_condo_iptu(self, scraper):
        """BIN-114: OLX never invents a condo+IPTU bundle; flag separate fees."""
        raw = {
            **SAMPLE_OLX_LISTING,
            "properties": [
                *SAMPLE_OLX_LISTING["properties"],
                {"label": "IPTU", "value": "165"},
            ],
        }
        result = scraper.normalize(raw)
        listing = result["listings"][0]
        assert listing["condo_fee"] == pytest.approx(650.0)
        assert listing["iptu"] == pytest.approx(165.0)
        assert listing["raw_json"]["fees_bundled"] is False

    def test_images_extracted(self, scraper):
        result = scraper.normalize(SAMPLE_OLX_LISTING)
        assert len(result["image_urls"]) == 2
        assert "https://img.olx.com.br/img1.jpg" in result["image_urls"]

    def test_neighborhood_in_props_json(self, scraper):
        result = scraper.normalize(SAMPLE_OLX_LISTING)
        assert result["props_json"]["neighborhood"] == "Savassi"

    def test_property_type_from_url_path(self, scraper):
        """OLX persists canonical EN type from category URL (BIN-75)."""
        result = scraper.normalize(SAMPLE_OLX_LISTING)
        assert result["props_json"]["type"] == "apartment"

    def test_property_type_from_window_stamp(self, scraper):
        raw = {
            "list_id": "501",
            "subject": "Imóvel amplo",
            "value": 2000.0,
            "_olx_property_type": "house",
            "url": "https://mg.olx.com.br/belo-horizonte-e-regiao/imoveis/imovel-501",
        }
        result = scraper.normalize(raw)
        assert result["props_json"]["type"] == "house"

    def test_property_type_from_casas_path(self, scraper):
        raw = {
            "list_id": "502",
            "subject": "Linda residência",
            "value": 450000.0,
            "url": "https://www.olx.com.br/imovel/venda/casas/mg/bh/502",
        }
        result = scraper.normalize(raw)
        assert result["props_json"]["type"] == "house"

    def test_missing_listing_id_raises(self, scraper):
        with pytest.raises(ValueError, match="missing id"):
            scraper.normalize({"subject": "test", "value": 1000})

    def test_missing_price_raises(self, scraper):
        raw = {"list_id": "999", "subject": "No price"}
        with pytest.raises(ValueError, match="Could not parse price"):
            scraper.normalize(raw)

    def test_pricing_infos_fallback(self, scraper):
        raw = {
            "list_id": "100",
            "subject": "Casa",
            "pricingInfos": [{"value": 5000.0, "period": "monthly"}],
        }
        result = scraper.normalize(raw)
        assert result["price"] == 5000.0
        assert result["listings"][0]["listing_type"] == "rent"

    def test_string_price_parsing(self, scraper):
        raw = {
            "list_id": "200",
            "subject": "R$ 2.500,00 - Apartamento",
        }
        result = scraper.normalize(raw)
        assert result["price"] == 2500.0

    def test_sale_detection(self, scraper):
        raw = {
            "list_id": "300",
            "subject": "Casa venda",
            "value": 450000.0,
            "url": "https://www.olx.com.br/imovel/venda/apartamentos/mg/bh/300",
        }
        result = scraper.normalize(raw)
        assert result["listings"][0]["listing_type"] == "sale"
        assert result["props_json"]["available_for_sale"] is True
        assert result["props_json"]["available_for_rent"] is False

    def test_no_location_graceful(self, scraper):
        raw = {
            "list_id": "400",
            "subject": "Imóvel",
            "value": 2000.0,
        }
        result = scraper.normalize(raw)
        assert result["location"] is None
        assert result["address"] is None

    def test_properties_parsing_dict_format(self, scraper):
        raw = {
            "list_id": "500",
            "subject": "Casa",
            "value": 3000.0,
            "properties": {
                "Área": "120m²",
                "Quartos": "3",
                "Banheiros": "2",
                "Vagas": "2",
            },
        }
        result = scraper.normalize(raw)
        assert result["area_m2"] == 120.0
        assert result["bedrooms"] == 3
        assert result["bathrooms"] == 2
        assert result["parking"] == 2

    def test_pets_and_furnished(self, scraper):
        raw = {
            "list_id": "600",
            "subject": "Apt",
            "value": 1500.0,
            "properties": [
                {"label": "Aceita animais", "value": "Sim"},
                {"label": "Mobiliado", "value": "Sim"},
            ],
        }
        result = scraper.normalize(raw)
        assert result["listings"][0]["accepts_pets"] is True
        assert result["listings"][0]["is_furnished"] is True

    def test_pets_name_key_and_permitido_value(self, scraper):
        """OLX detail attrs often use ``name`` + ``Permitido`` (BIN-110)."""
        raw = {
            "list_id": "601",
            "subject": "Apt pets",
            "value": 1800.0,
            "properties": [
                {"name": "aceita_animais", "value": "Permitido"},
            ],
        }
        result = scraper.normalize(raw)
        assert result["listings"][0]["accepts_pets"] is True

    def test_pets_dict_properties_format(self, scraper):
        raw = {
            "list_id": "602",
            "subject": "Casa",
            "value": 2200.0,
            "properties": {
                "Aceita pets": "Sim",
                "Quartos": "2",
            },
        }
        result = scraper.normalize(raw)
        assert result["listings"][0]["accepts_pets"] is True

    def test_pets_absent_leaves_accepts_pets_none(self, scraper):
        result = scraper.normalize(SAMPLE_OLX_LISTING)
        assert result["listings"][0]["accepts_pets"] is None

    def test_dual_olx_prices_emits_rent_and_sale(self, scraper):
        """BIN-108: both prices on raw → two property_listings rows."""
        raw = {
            "list_id": "dual-1",
            "subject": "Casa venda ou locação",
            "value": 2500.0,
            "_olx_prices": {"rent": 2500.0, "sale": 450000.0},
            "properties": [
                {"label": "Condomínio", "value": "400"},
                {"label": "IPTU", "value": "100"},
            ],
            "url": "https://mg.olx.com.br/belo-horizonte-e-regiao/imoveis/casa-dual-1",
        }
        result = scraper.normalize(raw)
        types = {row["listing_type"] for row in result["listings"]}
        assert types == {"rent", "sale"}
        assert len(result["listings"]) == 2
        rent = next(r for r in result["listings"] if r["listing_type"] == "rent")
        sale = next(r for r in result["listings"] if r["listing_type"] == "sale")
        assert rent["price"] == 3000.0  # 2500 + condo 400 + iptu 100
        assert rent["base_price"] == 2500.0
        assert sale["price"] == 450000.0
        assert sale["base_price"] is None
        assert result["price"] == 3000.0  # rent preferred for decisioning
        assert result["props_json"]["available_for_rent"] is True
        assert result["props_json"]["available_for_sale"] is True

    def test_dual_pricing_infos_emits_rent_and_sale(self, scraper):
        raw = {
            "list_id": "dual-2",
            "subject": "Apto",
            "pricingInfos": [
                {"value": 3200.0, "period": "monthly"},
                {"value": 520000.0, "period": ""},
            ],
        }
        result = scraper.normalize(raw)
        types = {row["listing_type"] for row in result["listings"]}
        assert types == {"rent", "sale"}
        rent = next(r for r in result["listings"] if r["listing_type"] == "rent")
        sale = next(r for r in result["listings"] if r["listing_type"] == "sale")
        assert rent["price"] == 3200.0
        assert sale["price"] == 520000.0

    def test_single_price_still_one_listing(self, scraper):
        result = scraper.normalize(SAMPLE_OLX_LISTING)
        assert len(result["listings"]) == 1
        assert result["listings"][0]["listing_type"] == "rent"


# ---------------------------------------------------------------------------
# Cross-window dual price merge (BIN-108)
# ---------------------------------------------------------------------------


class TestOLXDualPriceMerge:
    def test_merge_dual_prices_into_kept(self):
        kept = {
            "list_id": "99",
            "priceValue": "2.500",
            "_olx_listing_type": "rent",
        }
        incoming = {
            "list_id": "99",
            "priceValue": "450.000",
            "_olx_listing_type": "sale",
        }
        assert OLXScraper._merge_dual_window_prices(kept, incoming) is True
        assert kept["_olx_prices"] == {"rent": 2500.0, "sale": 450000.0}
        assert "_olx_listing_type" not in kept

    def test_merge_same_type_is_noop(self):
        kept = {
            "list_id": "99",
            "value": 2500.0,
            "_olx_listing_type": "rent",
        }
        incoming = {
            "list_id": "99",
            "value": 2600.0,
            "_olx_listing_type": "rent",
        }
        assert OLXScraper._merge_dual_window_prices(kept, incoming) is False
        assert "_olx_prices" not in kept

    def test_fetch_pages_merges_rent_and_sale_windows(self, scraper):
        scraper._RENT_PATHS = ["aluguel/apartamentos/estado-mg/bh"]
        scraper._SALE_PATHS = ["venda/apartamentos/estado-mg/bh"]
        scraper._price_rent = (500, 5000)
        scraper._price_sale = (80000, 900000)
        scraper._max_pages = 1
        scraper._page_size_hint = 50
        scraper._neighborhoods = []

        def fake_fetch(url, page):
            if "/aluguel/" in url:
                return [{"list_id": "dual", "priceValue": "2.500"}]
            return [{"list_id": "dual", "priceValue": "450.000"}]

        scraper._fetch_page_listings = MagicMock(side_effect=fake_fetch)
        listings = list(scraper.fetch_pages({"scrape_type": "both"}))
        # First yield is rent-only; re-yield after sale window merges dual prices
        # onto the same kept dict (so both list entries share that object).
        assert len(listings) == 2
        assert listings[0] is listings[1]
        assert listings[0]["_olx_prices"] == {"rent": 2500.0, "sale": 450000.0}
        assert "_olx_listing_type" not in listings[0]


# ---------------------------------------------------------------------------
# _extract_listings() tests
# ---------------------------------------------------------------------------


class TestExtractListings:
    def test_extracts_from_page_props_ads(self, scraper):
        data = {
            "props": {
                "pageProps": {
                    "initialState": {
                        "search": {
                            "ads": [SAMPLE_OLX_LISTING],
                        }
                    }
                }
            }
        }
        result = scraper._extract_listings(data)
        assert len(result) == 1
        assert result[0]["list_id"] == "123456789"

    def test_extracts_from_page_props_direct(self, scraper):
        data = {
            "props": {
                "pageProps": {
                    "ads": [SAMPLE_OLX_LISTING],
                }
            }
        }
        result = scraper._extract_listings(data)
        assert len(result) == 1

    def test_empty_state_returns_empty(self, scraper):
        data = {"props": {"pageProps": {}}}
        result = scraper._extract_listings(data)
        assert result == []

    def test_filters_non_dict_items(self, scraper):
        data = {
            "props": {
                "pageProps": {
                    "initialState": {
                        "search": {
                            "ads": [SAMPLE_OLX_LISTING, "not-a-dict", 123],
                        }
                    }
                }
            }
        }
        result = scraper._extract_listings(data)
        assert len(result) == 1

    def test_skips_advertising_slots_without_list_id(self, scraper):
        data = {
            "props": {
                "pageProps": {
                    "ads": [
                        {"advertisingId": "banner-1"},
                        SAMPLE_OLX_LISTING,
                    ]
                }
            }
        }
        result = scraper._extract_listings(data)
        assert len(result) == 1
        assert result[0]["list_id"] == "123456789"


# ---------------------------------------------------------------------------
# Flight / RSC HTML extraction
# ---------------------------------------------------------------------------


SAMPLE_FLIGHT_AD = {
    "listId": 1490781405,
    "subject": "Sobrado para alugar 2 quartos Santos",
    "priceValue": "R$ 5.500",
    "price": "R$ 5.500",
    "url": "https://sp.olx.com.br/baixada-santista/imoveis/sobrado-1490781405",
    "location": "Santos -  SP",
    "locationDetails": {
        "municipality": "Santos",
        "neighbourhood": "Ponta da Praia",
        "uf": "SP",
    },
    "images": [{"original": "https://img.olx.com.br/a.jpg"}],
    "properties": [
        {"name": "size", "value": "120m²", "label": "Área construída"},
        {"name": "rooms", "value": "2", "label": "Quartos"},
        {"name": "bathrooms", "value": "2", "label": "Banheiros"},
        {"name": "garage_spaces", "value": "1", "label": "Vagas na garagem"},
        {"name": "condominio", "value": "R$ 1", "label": "Condomínio"},
        {"name": "iptu", "value": "R$ 1", "label": "IPTU"},
        {
            "name": "real_estate_type",
            "value": "Aluguel - casa em rua pública",
            "label": "Tipo",
        },
    ],
}


class TestFlightAdsExtraction:
    def test_extract_flight_ads_from_next_f_payload(self, scraper):
        ads_json = json.dumps([SAMPLE_FLIGHT_AD, {"advertisingId": "x"}])
        inner = '{"ads":' + ads_json + "}"
        escaped_inner = inner.replace("\\", "\\\\").replace('"', '\\"')
        html = f'<script>self.__next_f.push([1,"{escaped_inner}"])</script>'
        result = scraper._extract_flight_ads(html)
        assert len(result) == 1
        assert result[0]["listId"] == 1490781405

    def test_parse_listings_html_falls_back_to_flight(self, scraper):
        inner = '{"ads":' + json.dumps([SAMPLE_FLIGHT_AD]) + "}"
        escaped_inner = inner.replace("\\", "\\\\").replace('"', '\\"')
        html = f"<html><script>self.__next_f.push([1,\"{escaped_inner}\"])</script></html>"
        result = scraper._parse_listings_html(html, url="https://example.test")
        assert len(result) == 1

    def test_normalize_flight_ad_shape(self, scraper):
        result = scraper.normalize(SAMPLE_FLIGHT_AD)
        assert result["platform_id"] == "1490781405"
        assert result["price"] == 5502.0  # 5500 + condo 1 + iptu 1
        assert result["listings"][0]["base_price"] == 5500.0
        assert result["area_m2"] == 120.0
        assert result["bedrooms"] == 2
        assert result["bathrooms"] == 2
        assert result["parking"] == 1
        assert result["props_json"]["neighborhood"] == "Ponta da Praia"
        assert "Santos" in (result["address"] or "")
        assert result["listings"][0]["listing_type"] == "rent"
        assert result["image_urls"] == ["https://img.olx.com.br/a.jpg"]


class TestDetectListingType:
    def test_rent_from_url(self):
        raw = {"_olx_url": "https://www.olx.com.br/imoveis/aluguel/apartamentos/mg/bh/123"}
        assert OLXScraper._detect_listing_type(raw) == "rent"

    def test_sale_from_url(self):
        raw = {"_olx_url": "https://www.olx.com.br/imoveis/venda/apartamentos/mg/bh/123"}
        assert OLXScraper._detect_listing_type(raw) == "sale"

    def test_stamp_wins_over_categoryless_detail_url_sale(self):
        """Flight/detail URLs often omit /venda/; search-window stamp is ground truth."""
        raw = {
            "url": "https://mg.olx.com.br/belo-horizonte-e-regiao/imoveis/vendo-casa-1520811952",
            "_olx_url": (
                "https://www.olx.com.br/imoveis/venda/casas/estado-mg/"
                "belo-horizonte-e-regiao?ps=100000&pe=500000"
            ),
            "_olx_listing_type": "sale",
        }
        assert OLXScraper._detect_listing_type(raw) == "sale"

    def test_stamp_wins_over_categoryless_detail_url_rent(self):
        raw = {
            "url": "https://mg.olx.com.br/belo-horizonte-e-regiao/imoveis/apto-centro-1490781405",
            "_olx_url": (
                "https://www.olx.com.br/imoveis/aluguel/apartamentos/estado-mg/"
                "belo-horizonte-e-regiao?ps=500&pe=15000"
            ),
            "_olx_listing_type": "rent",
        }
        assert OLXScraper._detect_listing_type(raw) == "rent"

    def test_fallback_to_search_url_when_detail_has_no_category(self):
        raw = {
            "url": "https://mg.olx.com.br/belo-horizonte-e-regiao/imoveis/cobertura-no-itapoa-1517127300",
            "_olx_url": (
                "https://www.olx.com.br/imoveis/venda/apartamentos/estado-mg/"
                "belo-horizonte-e-regiao"
            ),
        }
        assert OLXScraper._detect_listing_type(raw) == "sale"

    def test_venda_nova_zone_slug_alone_is_not_sale(self):
        """Bare 'venda' substring must not match zone slug venda-nova."""
        raw = {
            "url": (
                "https://www.olx.com.br/imoveis/estado-mg/belo-horizonte-e-regiao/"
                "venda-nova/planalto/apartamento-123"
            ),
            "subject": "Apartamento 2 quartos",
            "priceValue": "2500",
        }
        # Category-less zone URL + rent-band price → rent (BIN-81).
        assert OLXScraper._detect_listing_type(raw) == "rent"
        raw["_olx_listing_type"] = "rent"
        assert OLXScraper._detect_listing_type(raw) == "rent"

    def test_venda_nova_in_title_with_rent_price_is_rent(self):
        """Title 'Venda Nova' must not force sale when price is rent-band."""
        raw = {
            "url": (
                "https://mg.olx.com.br/belo-horizonte-e-regiao/imoveis/"
                "casa-de-03-quartos-no-candelaria-venda-nova-belo-horizonte-1520650089"
            ),
            "subject": "Casa de 03 quartos no Candelária - Venda Nova/Belo Horizonte",
            "priceValue": "1.300",
        }
        assert OLXScraper._detect_listing_type(raw) == "rent"

    def test_a_venda_phrase_still_sale(self):
        raw = {
            "subject": "Apartamento à venda no Centro",
            "priceValue": "450.000",
        }
        assert OLXScraper._detect_listing_type(raw) == "sale"

    def test_rent_from_pricing(self):
        raw = {"pricingInfos": [{"period": "monthly"}]}
        assert OLXScraper._detect_listing_type(raw) == "rent"

    def test_sale_from_pricing_empty_period_uses_price_band(self):
        raw = {"pricingInfos": [{"period": "", "price": 450000}]}
        assert OLXScraper._detect_listing_type(raw) == "sale"

    def test_default_sale_mid_band(self):
        raw = {}
        assert OLXScraper._detect_listing_type(raw) == "sale"


# ---------------------------------------------------------------------------
# Registration test
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_olx_registered(self):
        """OLX scraper should be self-registered via the @register decorator."""
        import adapters.scrapers.olx  # noqa: F401  — force registration
        from adapters.scrapers.registry import ScraperRegistry

        assert "olx" in ScraperRegistry._registry


# ---------------------------------------------------------------------------
# Config-driven rate limit / jitter tests
# ---------------------------------------------------------------------------


class TestConfigDrivenParams:
    def test_rate_limit_from_config(self, scraper):
        assert scraper._rate_limit == 20

    def test_jitter_from_config(self, scraper):
        assert scraper._jitter_min == 0
        assert scraper._jitter_max == 0.1

    def test_defaults_when_missing(self, scraper_no_extra):
        assert scraper_no_extra._max_pages == 5  # default
        assert scraper_no_extra._jitter_max == 6  # default from OLXScraper
        assert scraper_no_extra._jitter_min == 2  # default from OLXScraper


@pytest.mark.unit
class TestOLXFetchLifecycle:
    def test_start_creates_http_client_and_circuit_breaker(self, scraper):
        session = MagicMock()
        with patch.object(
            scraper, "create_http_session", return_value=session
        ) as create_session, patch(
            "adapters.scrapers.olx.RedisCircuitBreaker"
        ) as circuit_breaker:
            scraper.start()

        create_session.assert_called_once_with()
        assert scraper.session is session
        session.headers.update.assert_called_once()
        circuit_breaker.assert_called_once_with(
            platform="olx", failure_threshold=5, cooldown_seconds=120
        )

    def test_close_closes_existing_session(self, scraper):
        scraper.session = MagicMock()

        scraper.close()

        scraper.session.close.assert_called_once()

    def test_close_without_session_is_a_noop(self, scraper):
        scraper.close()

    def test_throttled_request_records_success(self, scraper):
        scraper.session = MagicMock()
        scraper._cb = MagicMock()
        scraper._cb.is_open.return_value = False
        response = MagicMock(status_code=200)
        scraper.session.get.return_value = response
        with patch("adapters.scrapers.olx.random.uniform", return_value=0), patch(
            "adapters.scrapers.olx.time.sleep"
        ) as sleep:
            assert scraper._throttled_request("https://example.test") is response

        sleep.assert_called_once_with(0)
        scraper._cb.record_success.assert_called_once()

    def test_throttled_request_records_failure_for_server_and_rate_limit(self, scraper):
        scraper.session = MagicMock()
        scraper._cb = MagicMock()
        scraper._cb.is_open.return_value = False
        scraper.session.get.return_value = MagicMock(status_code=429)
        with patch("adapters.scrapers.olx.random.uniform", return_value=0), patch(
            "adapters.scrapers.olx.time.sleep"
        ):
            scraper._throttled_request("https://example.test")

        scraper._cb.record_failure.assert_called_once()

    def test_throttled_request_rejects_open_circuit(self, scraper):
        scraper._cb = MagicMock()
        scraper._cb.is_open.return_value = True

        with pytest.raises(CircuitBreakerOpenError, match="circuit breaker is open"):
            scraper._throttled_request("https://example.test")

    def test_fetch_page_handles_request_error(self, scraper):
        scraper._throttled_request = MagicMock(side_effect=RuntimeError("network"))

        with patch("adapters.scrapers.olx.logger"):
            assert scraper._fetch_page_listings("https://example.test", 1) == []

    def test_fetch_description_circuit_open_returns_empty(self, scraper):
        scraper._throttled_request = MagicMock(side_effect=CircuitBreakerOpenError("open"))

        with patch("adapters.scrapers.olx.logger"):
            assert scraper.fetch_description("https://example.test") == ""

    def test_fetch_description_unexpected_error_returns_empty(self, scraper):
        scraper._throttled_request = MagicMock(side_effect=RuntimeError("boom"))

        with patch("adapters.scrapers.olx.logger"):
            assert scraper.fetch_description("https://example.test") == ""

    def test_fetch_description_blank_url_returns_empty(self, scraper):
        assert scraper.fetch_description("   ") == ""

    @pytest.mark.parametrize(
        ("status", "html"),
        [
            (500, ""),
            (200, "<html></html>"),
            (200, '<script id="__NEXT_DATA__">not-json</script>'),
        ],
    )
    def test_fetch_page_returns_empty_for_invalid_response(self, scraper, status, html):
        scraper._throttled_request = MagicMock(
            return_value=MagicMock(status_code=status, text=html)
        )

        with patch("adapters.scrapers.olx.logger"):
            assert scraper._fetch_page_listings("https://example.test", 1) == []

    def test_fetch_page_extracts_listings_from_next_data(self, scraper):
        html = (
            '<script id="__NEXT_DATA__">'
            '{"props":{"pageProps":{"initialState":{"search":{"ads":[{"list_id":"1"}]}}}}}'
            "</script>"
        )
        scraper._throttled_request = MagicMock(
            return_value=MagicMock(status_code=200, text=html)
        )

        assert scraper._fetch_page_listings("https://example.test", 1) == [{"list_id": "1"}]

    def test_fetch_page_extracts_listings_from_flight_html(self, scraper):
        ad = {"listId": 42, "subject": "Casa", "priceValue": "R$ 1.000"}
        inner = '{"ads":' + json.dumps([ad]) + "}"
        escaped = inner.replace("\\", "\\\\").replace('"', '\\"')
        html = f'<script>self.__next_f.push([1,"{escaped}"])</script>'
        scraper._throttled_request = MagicMock(
            return_value=MagicMock(status_code=200, text=html)
        )
        result = scraper._fetch_page_listings("https://example.test", 1)
        assert len(result) == 1
        assert result[0]["listId"] == 42

    def test_fetch_pages_obeys_checkpoint_type_and_stops_empty_page(self, scraper):
        scraper._RENT_PATHS = ["aluguel/apartamentos/estado-mg/bh"]
        scraper._SALE_PATHS = ["venda/apartamentos/estado-mg/bh"]
        scraper._price_rent = (500, 15000)
        scraper._max_pages = 3
        scraper._page_size_hint = 50
        scraper._neighborhoods = []
        scraper._fetch_page_listings = MagicMock(
            side_effect=[[{"list_id": "first"}], [], [{"list_id": "unused"}], []]
        )

        listings = list(scraper.fetch_pages({"scrape_type": "rent"}))

        assert len(listings) == 1
        assert listings[0]["list_id"] == "first"
        assert "ps=500" in listings[0]["_olx_url"]
        assert "pe=15000" in listings[0]["_olx_url"]
        assert scraper._fetch_page_listings.call_count == 2

    def test_fetch_pages_uses_both_paths_for_invalid_checkpoint(self, scraper):
        scraper._RENT_PATHS = ["aluguel/apartamentos/estado-mg/bh"]
        scraper._SALE_PATHS = ["venda/apartamentos/estado-mg/bh"]
        scraper._price_rent = (500, 15000)
        scraper._price_sale = (100000, 5000000)
        scraper._max_pages = 1
        scraper._neighborhoods = []
        scraper._fetch_page_listings = MagicMock(return_value=[])

        assert list(scraper.fetch_pages("not-a-checkpoint")) == []
        assert scraper._fetch_page_listings.call_count == 2

    def test_fetch_pages_splits_price_when_saturated(self, scraper):
        scraper._RENT_PATHS = ["aluguel/apartamentos/estado-mg/bh"]
        scraper._SALE_PATHS = []
        scraper._price_rent = (100, 200)
        scraper._max_pages = 1
        scraper._page_size_hint = 2
        scraper._neighborhoods = []

        def fake_fetch(url, page):
            if "ps=100&pe=200" in url:
                return [{"list_id": "a"}, {"list_id": "b"}]
            if "ps=100&pe=150" in url:
                return [{"list_id": "c"}]
            if "ps=151&pe=200" in url:
                return [{"list_id": "d"}]
            return []

        scraper._fetch_page_listings = MagicMock(side_effect=fake_fetch)
        listings = list(scraper.fetch_pages({"scrape_type": "rent"}))
        ids = {item["list_id"] for item in listings}
        assert ids == {"c", "d"}
        assert "a" not in ids  # parent saturated window discarded

    def test_fetch_pages_splits_when_max_pages_partial_last_page(self, scraper):
        """Hitting max_pages with a non-empty partial last page must saturate.

        Regression for the ~200 cliff: last page under page_size_hint used to
        skip price/neighborhood fan-out and yield a truncated city window.
        """
        scraper._RENT_PATHS = ["aluguel/apartamentos/estado-mg/bh"]
        scraper._SALE_PATHS = []
        scraper._price_rent = (100, 200)
        scraper._max_pages = 2
        scraper._page_size_hint = 50
        scraper._neighborhoods = []

        def fake_fetch(url, page):
            if "ps=100&pe=200" in url:
                # Two pages of content; last page well under page_size_hint
                if page == 1:
                    return [{"list_id": f"p1-{i}"} for i in range(50)]
                if page == 2:
                    return [{"list_id": f"p2-{i}"} for i in range(40)]
            if "ps=100&pe=150" in url:
                return [{"list_id": "c"}]
            if "ps=151&pe=200" in url:
                return [{"list_id": "d"}]
            return []

        scraper._fetch_page_listings = MagicMock(side_effect=fake_fetch)
        listings = list(scraper.fetch_pages({"scrape_type": "rent"}))
        ids = {item["list_id"] for item in listings}
        assert ids == {"c", "d"}
        assert not any(x.startswith("p1-") or x.startswith("p2-") for x in ids)

    def test_fetch_pages_fans_out_neighborhoods_on_atomic_saturation(self, scraper):
        scraper._RENT_PATHS = ["aluguel/apartamentos/estado-mg/bh"]
        scraper._SALE_PATHS = []
        scraper._price_rent = (100, 101)  # atomic — cannot bisect
        scraper._max_pages = 1
        scraper._page_size_hint = 2
        scraper._neighborhoods = [
            {"slug": "savassi", "zone": "centro-sul"},
            {"slug": "castelo", "zone": "pampulha"},
        ]

        def fake_fetch(url, page):
            if "/centro-sul/savassi" in url:
                return [{"list_id": "s1"}]
            if "/pampulha/castelo" in url:
                return [{"list_id": "c1"}]
            # City-wide saturated
            if "ps=100&pe=101" in url and "/centro-sul/" not in url and "/pampulha/" not in url:
                return [{"list_id": "city1"}, {"list_id": "city2"}]
            return []

        scraper._fetch_page_listings = MagicMock(side_effect=fake_fetch)
        listings = list(scraper.fetch_pages({"scrape_type": "rent"}))
        ids = {item["list_id"] for item in listings}
        assert ids == {"s1", "c1"}
        urls = [c.args[0] for c in scraper._fetch_page_listings.call_args_list]
        assert any("/centro-sul/savassi" in u for u in urls)
        assert any("/pampulha/castelo" in u for u in urls)

    def test_fetch_pages_dedupes_listing_ids(self, scraper):
        scraper._RENT_PATHS = ["aluguel/apartamentos/estado-mg/bh"]
        scraper._SALE_PATHS = []
        scraper._price_rent = (500, 600)
        scraper._max_pages = 2
        scraper._page_size_hint = 50
        scraper._neighborhoods = []
        scraper._fetch_page_listings = MagicMock(
            side_effect=[
                [{"list_id": "dup"}, {"list_id": "a"}],
                [{"list_id": "dup"}, {"list_id": "b"}],
            ]
        )
        listings = list(scraper.fetch_pages({"scrape_type": "rent"}))
        assert [x["list_id"] for x in listings] == ["dup", "a", "b"]

    def test_build_search_url_includes_price_and_geo(self, scraper):
        url = scraper._build_search_url(
            "aluguel/apartamentos/estado-mg/bh", 2, 1000, 2000, "centro-sul", "savassi"
        )
        assert url == (
            "https://www.olx.com.br/imoveis/aluguel/apartamentos/estado-mg/bh/"
            "centro-sul/savassi?ps=1000&pe=2000&o=2"
        )

    def test_initial_windows_multi_city(self):
        s = OLXScraper(
            "olx",
            {
                "extra": {
                    "max_pages": 2,
                    "cities": [
                        {
                            "region": "estado-mg",
                            "city_slug": "belo-horizonte-e-regiao",
                            "neighborhoods": [
                                {"slug": "savassi", "zone": "centro-sul"},
                            ],
                        },
                        {
                            "region": "estado-sp",
                            "city_slug": "sao-paulo-e-regiao",
                            "neighborhoods": [],
                        },
                        {
                            "region": "estado-sp",
                            "city_slug": "campinas-e-regiao",
                            "neighborhoods": [],
                        },
                    ],
                }
            },
        )
        windows = s._initial_windows({"scrape_type": "rent"})
        paths = [w[0] for w in windows]
        assert any("estado-mg/belo-horizonte-e-regiao" in p for p in paths)
        assert any("estado-sp/sao-paulo-e-regiao" in p for p in paths)
        assert any("estado-sp/campinas-e-regiao" in p for p in paths)
        # 3 cities × 2 rent categories
        assert len(windows) == 6
        bh_apt = "aluguel/apartamentos/estado-mg/belo-horizonte-e-regiao"
        sp_apt = "aluguel/apartamentos/estado-sp/sao-paulo-e-regiao"
        assert s._neighborhoods_for_path(bh_apt) == [
            {"slug": "savassi", "zone": "centro-sul"}
        ]
        assert s._neighborhoods_for_path(sp_apt) == []

    def test_fanout_uses_per_path_neighborhoods_not_global_bh(self):
        s = OLXScraper(
            "olx",
            {
                "extra": {
                    "max_pages": 1,
                    "page_size_hint": 2,
                    "price_rent": [100, 101],
                    "cities": [
                        {
                            "region": "estado-mg",
                            "city_slug": "belo-horizonte-e-regiao",
                            "neighborhoods": [
                                {"slug": "savassi", "zone": "centro-sul"},
                            ],
                        },
                        {
                            "region": "estado-sp",
                            "city_slug": "sao-paulo-e-regiao",
                            "neighborhoods": [],
                        },
                    ],
                }
            },
        )
        s._RENT_PATHS = ["aluguel/apartamentos/estado-sp/sao-paulo-e-regiao"]
        s._SALE_PATHS = []

        def fake_fetch(url, page):
            # SP city-wide saturated; must NOT fan out BH savassi
            if "sao-paulo-e-regiao" in url and "/centro-sul/" not in url:
                return [{"list_id": "sp1"}, {"list_id": "sp2"}]
            return []

        s._fetch_page_listings = MagicMock(side_effect=fake_fetch)
        listings = list(s.fetch_pages({"scrape_type": "rent"}))
        assert {x["list_id"] for x in listings} == {"sp1", "sp2"}
        urls = [c.args[0] for c in s._fetch_page_listings.call_args_list]
        assert not any("/centro-sul/savassi" in u for u in urls)
