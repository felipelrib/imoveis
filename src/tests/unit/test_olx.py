"""Unit tests for the OLX scraper."""

from __future__ import annotations

import pytest

from adapters.scrapers.olx import OLXScraper

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
        assert result["price"] == 3500.0
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
        assert listing["price"] == 3500.0
        assert listing["currency"] == "BRL"

    def test_images_extracted(self, scraper):
        result = scraper.normalize(SAMPLE_OLX_LISTING)
        assert len(result["image_urls"]) == 2
        assert "https://img.olx.com.br/img1.jpg" in result["image_urls"]

    def test_neighborhood_in_props_json(self, scraper):
        result = scraper.normalize(SAMPLE_OLX_LISTING)
        assert result["props_json"]["neighborhood"] == "Savassi"

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


# ---------------------------------------------------------------------------
# _detect_listing_type() tests
# ---------------------------------------------------------------------------


class TestDetectListingType:
    def test_rent_from_url(self):
        raw = {"_olx_url": "https://www.olx.com.br/imovel/aluguel/apartamentos/mg/bh/123"}
        assert OLXScraper._detect_listing_type(raw) == "rent"

    def test_sale_from_url(self):
        raw = {"_olx_url": "https://www.olx.com.br/imovel/venda/apartamentos/mg/bh/123"}
        assert OLXScraper._detect_listing_type(raw) == "sale"

    def test_rent_from_pricing(self):
        raw = {"pricingInfos": [{"period": "monthly"}]}
        assert OLXScraper._detect_listing_type(raw) == "rent"

    def test_sale_from_pricing(self):
        raw = {"pricingInfos": [{"period": ""}]}
        assert OLXScraper._detect_listing_type(raw) == "sale"

    def test_default_rent(self):
        raw = {}
        assert OLXScraper._detect_listing_type(raw) == "rent"


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
