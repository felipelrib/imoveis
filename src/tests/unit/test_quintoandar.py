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
        with patch("httpx.Client", return_value=fake_client):
            s.start()
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
        assert QuintoAndarScraper._initial_price_windows({"scrape_type": "rent"})[0][0] == "alugar"
        assert QuintoAndarScraper._initial_price_windows({"scrape_type": "sale"})[0][0] == "comprar"
        both = QuintoAndarScraper._initial_price_windows(None)
        assert {w[0] for w in both} == {"alugar", "comprar"}

    def test_split_window(self):
        q: deque = deque()
        houses = {str(i): {} for i in range(12)}
        assert QuintoAndarScraper._split_window(q, "alugar", 100, 200, houses) is True
        assert len(q) == 2
        assert QuintoAndarScraper._split_window(q, "alugar", 100, 100, houses) is False

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
        with patch.object(QuintoAndarScraper, "_initial_price_windows", return_value=[("alugar", 1, 2), ("alugar", 1, 2)]):
            with patch.object(QuintoAndarScraper, "_split_window", return_value=False):
                items = list(s.fetch_pages({"scrape_type": "rent"}))
        assert len(items) == 1
        assert items[0]["price_query_min"] == 1


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
