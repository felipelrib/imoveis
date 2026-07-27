"""Unit tests for OSRM routing client (BIN-90)."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from adapters.geo.osrm_client import OsrmClient


def _ok_response(duration_sec: float = 600.0, distance_m: float = 4200.0) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "code": "Ok",
        "routes": [{"duration": duration_sec, "distance": distance_m}],
    }
    return response


@pytest.mark.unit
class TestOsrmClient:
    def test_parses_ok_route(self):
        client = MagicMock()
        client.get.return_value = _ok_response(600.0, 4200.0)
        osrm = OsrmClient("http://osrm.local:5000", mode="driving", client=client)
        result = osrm.route(-19.93, -43.95, -19.92, -43.94)
        assert result == pytest.approx((10.0, 4200.0))
        called_url = client.get.call_args.args[0]
        assert "route/v1/driving/" in called_url
        assert "-43.95,-19.93;-43.94,-19.92" in called_url

    def test_empty_base_url_returns_none(self):
        osrm = OsrmClient("", client=MagicMock())
        assert osrm.route(-19.9, -43.9, -19.92, -43.94) is None

    def test_http_error_returns_none(self):
        client = MagicMock()
        client.get.side_effect = httpx.TimeoutException("slow")
        osrm = OsrmClient("http://osrm.local:5000", client=client)
        assert osrm.route(-19.9, -43.9, -19.92, -43.94) is None

    def test_non_ok_code_returns_none(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"code": "NoRoute", "routes": []}
        client = MagicMock()
        client.get.return_value = response
        osrm = OsrmClient("http://osrm.local:5000", client=client)
        assert osrm.route(-19.9, -43.9, -19.92, -43.94) is None

    def test_http_status_error_returns_none(self):
        response = MagicMock()
        response.status_code = 500
        client = MagicMock()
        client.get.return_value = response
        osrm = OsrmClient("http://osrm.local:5000", client=client)
        assert osrm.route(-19.9, -43.9, -19.92, -43.94) is None

    def test_walking_profile(self):
        client = MagicMock()
        client.get.return_value = _ok_response()
        osrm = OsrmClient("http://osrm.local:5000/", mode="walking", client=client)
        osrm.route(-19.9, -43.9, -19.92, -43.94)
        assert "route/v1/walking/" in client.get.call_args.args[0]
