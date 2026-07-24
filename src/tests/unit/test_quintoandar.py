"""Unit tests for QuintoAndar scraper fetch/lifecycle helpers."""

from __future__ import annotations

from collections import deque
from unittest.mock import MagicMock, patch

import pytest

from adapters.scrapers.quintoandar import QuintoAndarScraper
from core.exceptions import CircuitBreakerOpenError


def _scraper() -> QuintoAndarScraper:
    return QuintoAndarScraper("quintoandar", {"extra": {"city_slug": "belo-horizonte-mg-brasil"}})


@pytest.mark.unit
class TestQuintoAndarLifecycle:
    def test_start_and_close(self):
        s = _scraper()
        fake_client = MagicMock()
        with patch.object(s, "create_http_session", return_value=fake_client) as create_session:
            s.start()
        create_session.assert_called_once_with()
        assert s.session is fake_client
        fake_client.headers.update.assert_called()
        s.close()
        fake_client.close.assert_called_once()

    def test_throttled_request_open_circuit(self):
        s = _scraper()
        s.session = MagicMock()
        s._cb = MagicMock()
        s._cb.is_open.return_value = True
        with pytest.raises(CircuitBreakerOpenError):
            s._throttled_request("GET", "http://example")

    def test_throttled_request_records_success_and_failure(self):
        s = _scraper()
        s.session = MagicMock()
        s._cb = MagicMock()
        s._cb.is_open.return_value = False
        ok = MagicMock(status_code=200)
        s.session.request.return_value = ok
        with patch("time.sleep"):
            assert s._throttled_request("GET", "http://x") is ok
        s._cb.record_success.assert_called_once()

        bad = MagicMock(status_code=503)
        s.session.request.return_value = bad
        with patch("time.sleep"):
            s._throttled_request("GET", "http://x")
        s._cb.record_failure.assert_called_once()


@pytest.mark.unit
class TestQuintoAndarFetch:
    def test_initial_price_windows(self):
        s = _scraper()
        assert s._initial_price_windows({"scrape_type": "rent"})[0][0] == "alugar"
        assert s._initial_price_windows({"scrape_type": "sale"})[0][0] == "comprar"
        both = s._initial_price_windows(None)
        assert {w[0] for w in both} == {"alugar", "comprar"}
        assert all(w[3] is None for w in both)

    def test_initial_price_windows_from_config(self):
        s = QuintoAndarScraper(
            "quintoandar",
            {
                "extra": {
                    "city_slug": "belo-horizonte-mg-brasil",
                    "price_rent": [100, 200],
                    "price_sale": [1000, 2000],
                }
            },
        )
        rent = s._initial_price_windows({"scrape_type": "rent"})[0]
        assert rent == ("alugar", 100, 200, None)

    def test_split_window(self):
        q: deque = deque()
        houses = {str(i): {} for i in range(12)}
        assert QuintoAndarScraper._split_window(q, "alugar", 100, 200, houses) is True
        assert len(q) == 2
        assert QuintoAndarScraper._split_window(q, "alugar", 100, 100, houses) is False

    def test_window_url_city_and_neighborhood(self):
        s = _scraper()
        city = s._window_url("alugar", 500, 1000, None)
        assert city.endswith("/belo-horizonte-mg-brasil/de-500-a-1000-reais")
        nb = s._window_url("alugar", 500, 1000, "savassi")
        assert "/savassi-belo-horizonte-mg-brasil/de-500-a-1000-reais" in nb

    def test_fetch_window_houses_http_error(self):
        s = _scraper()
        s._throttled_request = MagicMock(return_value=MagicMock(status_code=500, text="err"))
        assert s._fetch_window_houses("http://x", "alugar", 1, 2) == {}

    def test_fetch_window_houses_missing_next_data(self):
        s = _scraper()
        s._throttled_request = MagicMock(return_value=MagicMock(status_code=200, text="<html></html>"))
        assert s._fetch_window_houses("http://x", "alugar", 1, 2) == {}

    def test_fetch_window_houses_parses_houses(self):
        import json

        s = _scraper()
        payload = {
            "props": {"pageProps": {"initialState": {"houses": {"1": {"id": 1}, "2": "skip"}}}}
        }
        html = f'<script id="__NEXT_DATA__">{json.dumps(payload)}</script>'
        s._throttled_request = MagicMock(return_value=MagicMock(status_code=200, text=html))
        houses = s._fetch_window_houses("http://x", "alugar", 1, 2)
        assert houses == {"1": {"id": 1}}

    def test_fetch_pages_yields_and_skips_duplicates(self):
        s = _scraper()
        s._fetch_window_houses = MagicMock(side_effect=[
            {"a": {"id": "a"}},
            {},
        ])
        with patch.object(
            QuintoAndarScraper,
            "_initial_price_windows",
            return_value=[("alugar", 1, 2, None), ("alugar", 1, 2, None)],
        ):
            items = list(s.fetch_pages({"scrape_type": "rent"}))
        assert len(items) == 1
        assert items[0]["price_query_min"] == 1

    def test_fetch_pages_fans_out_neighborhoods_on_atomic_saturation(self):
        s = QuintoAndarScraper(
            "quintoandar",
            {
                "extra": {
                    "city_slug": "belo-horizonte-mg-brasil",
                    "neighborhoods": [{"slug": "savassi"}, {"slug": "lourdes"}],
                }
            },
        )

        def fake_houses(url, action, min_p, max_p):
            if "savassi-" in url:
                return {"1": {"id": "s1"}}
            if "lourdes-" in url:
                return {"2": {"id": "l1"}}
            # City-wide atomic band returns a full page
            return {str(i): {"id": f"c{i}"} for i in range(12)}

        s._fetch_window_houses = MagicMock(side_effect=fake_houses)
        with patch.object(
            QuintoAndarScraper,
            "_initial_price_windows",
            return_value=[("alugar", 100, 100, None)],
        ):
            items = list(s.fetch_pages({"scrape_type": "rent"}))
        ids = {item["id"] for item in items}
        assert ids == {"s1", "l1"}
        urls = [c.args[0] for c in s._fetch_window_houses.call_args_list]
        assert any("savassi-belo-horizonte-mg-brasil" in u for u in urls)
        assert any("lourdes-belo-horizonte-mg-brasil" in u for u in urls)


@pytest.mark.unit
class TestQuintoAndarNormalizeLocation:
    def test_missing_coords_yield_none_location(self):
        s = _scraper()
        raw = {
            "id": 99,
            "rent": 2000,
            "salePrice": 0,
            "condoFee": 0,
            "iptu": 0,
            "area": 50,
            "bedrooms": 2,
            "bathrooms": 1,
            "parkingSpaces": 0,
            "address": {"street": "Rua A", "number": "1"},
            "neighbourhood": "Centro",
            "location": {},
            "photos": [],
        }
        with patch.object(QuintoAndarScraper, "_prices_and_fees", return_value=(2000.0, 0.0, 0.0, 0.0, False, None, 0.0)):
            result = s.normalize(raw)
        assert result["location"] is None

    def test_present_coords(self):
        s = _scraper()
        raw = {
            "id": 99,
            "rent": 2000,
            "salePrice": 0,
            "condoFee": 0,
            "iptu": 0,
            "area": 50,
            "bedrooms": 2,
            "bathrooms": 1,
            "parkingSpaces": 0,
            "address": {"street": "Rua A", "number": "1"},
            "neighbourhood": "Centro",
            "location": {"lat": -19.9, "lng": -43.9},
            "photos": [{"url": "http://img"}],
        }
        with patch.object(QuintoAndarScraper, "_prices_and_fees", return_value=(2000.0, 0.0, 0.0, 0.0, False, None, 0.0)):
            result = s.normalize(raw)
        assert result["location"] == {"lat": -19.9, "lon": -43.9}

    def test_parking_spots_field_preferred(self):
        """Live QuintoAndar search JSON renamed parkingSpaces → parkingSpots."""
        s = _scraper()
        raw = {
            "id": 99,
            "rentPrice": 2000,
            "salePrice": 0,
            "totalCost": 2000,
            "area": 50,
            "bedrooms": 2,
            "bathrooms": 1,
            "parkingSpots": 2,
            "address": {"address": "Rua A", "city": "BH"},
            "neighbourhood": "Centro",
            "photos": [],
        }
        result = s.normalize(raw)
        assert result["parking"] == 2
