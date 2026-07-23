"""Unit tests for QuintoAndar fee extraction / normalize."""

from __future__ import annotations

import pytest

from adapters.scrapers.quintoandar import QuintoAndarScraper


@pytest.fixture
def qa_scraper():
    return QuintoAndarScraper(
        "quintoandar",
        {"rate_limit": 30, "extra": {"city_slug": "belo-horizonte-mg-brasil"}},
    )


def _qa_raw(**overrides):
    data = {
        "id": "895549038",
        "type": "Apartamento",
        "neighbourhood": "Alvorada",
        "address": {"address": "Rua Faria Pereira", "city": "Belo Horizonte"},
        "area": 38,
        "bedrooms": 1,
        "bathrooms": 1,
        "parkingSpaces": 0,
        "photos": [],
        "location": {"lat": -19.9, "lon": -43.9},
        "rentPrice": 750,
        "totalCost": 929,
        "salePrice": 0,
    }
    data.update(overrides)
    return data


class TestQuintoAndarFees:
    def test_derives_bundled_fees_from_total_minus_base(self, qa_scraper):
        result = qa_scraper.normalize(_qa_raw())
        rent = next(row for row in result["listings"] if row["listing_type"] == "rent")
        assert rent["price"] == 929
        assert rent["raw_json"]["partial_price"] == 750
        assert rent["condo_fee"] == pytest.approx(179.0)
        assert rent["iptu"] is None
        assert rent["raw_json"]["fees_bundled"] is True

    def test_separate_condo_and_iptu(self, qa_scraper):
        result = qa_scraper.normalize(
            _qa_raw(condoFee=120, iptu=59, condoIptu=None, totalCost=929)
        )
        rent = next(row for row in result["listings"] if row["listing_type"] == "rent")
        assert rent["condo_fee"] == pytest.approx(120.0)
        assert rent["iptu"] == pytest.approx(59.0)
        assert rent["raw_json"].get("fees_bundled") is None

    def test_bundled_condo_iptu_field(self, qa_scraper):
        result = qa_scraper.normalize(
            _qa_raw(condoIptu=179, totalCost=929, rentPrice=750)
        )
        rent = next(row for row in result["listings"] if row["listing_type"] == "rent")
        assert rent["condo_fee"] == pytest.approx(179.0)
        assert rent["iptu"] is None
        assert rent["raw_json"]["fees_bundled"] is True

    def test_unknown_fees_are_none_not_zero(self, qa_scraper):
        result = qa_scraper.normalize(
            _qa_raw(rentPrice=900, totalCost=900, condoFee=None, iptu=None, condoIptu=None)
        )
        rent = next(row for row in result["listings"] if row["listing_type"] == "rent")
        assert rent["condo_fee"] is None
        assert rent["iptu"] is None
        assert rent["price"] == 900

    def test_equal_total_and_base_no_phantom_fees(self, qa_scraper):
        result = qa_scraper.normalize(_qa_raw(rentPrice=900, totalCost=900))
        rent = next(row for row in result["listings"] if row["listing_type"] == "rent")
        assert rent["condo_fee"] is None
        assert rent["iptu"] is None
