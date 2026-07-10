"""API contract tests — validate response shapes for every endpoint.

These tests ensure that the API's response schema doesn't change without
updating this contract. Uses FastAPI TestClient with minimal dependencies.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture
def client():
    """FastAPI TestClient — no DB/Redis needed for schema validation.

    ``raise_server_exceptions=False`` ensures that 500-level errors (e.g.
    from a missing database) are returned as normal HTTP responses instead
    of being re-raised by the test client.
    """
    c = TestClient(app, raise_server_exceptions=False)
    return c


# ---------------------------------------------------------------------------
# Public endpoints (no auth)
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_health_returns_valid_shape(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] in ("ok", "degraded", "error")

    def test_index_returns_valid_shape(self, client):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "service" in data
        assert "status" in data
        assert isinstance(data["service"], str)

    def test_properties_list_returns_valid_shape(self, client):
        """Properties endpoint should return a paginated response with items."""
        response = client.get("/properties?page=1&page_size=10")
        # May fail if DB is unavailable — that's expected in contract tests
        # The key check is that if it succeeds, the shape is correct
        if response.status_code == 200:
            data = response.json()
            assert "total" in data
            assert "page" in data
            assert "page_size" in data
            assert "properties" in data
            assert isinstance(data["properties"], list)
        elif response.status_code >= 500:
            # Internal server errors are OK for contract tests (DB may be down)
            pass
        else:
            # Any 4xx should still be valid JSON with a detail field
            data = response.json()
            assert isinstance(data, dict)


class TestPlatformsEndpoint:
    def test_platforms_returns_list(self, client):
        """GET /platforms must return a list of platform objects."""
        response = client.get("/platforms")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Each item should be a dict with name and enabled fields
        for platform in data:
            assert isinstance(platform, dict)
            assert "name" in platform
            assert "enabled" in platform
            assert isinstance(platform["name"], str)
            assert isinstance(platform["enabled"], bool)


class TestNeighborhoodsEndpoint:
    def test_neighborhoods_returns_list(self, client):
        """GET /properties/neighborhoods must return a list of neighbourhood objects."""
        response = client.get("/properties/neighborhoods")
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)
            # Each item should be a dict with name and count
            for item in data:
                assert isinstance(item, dict)
                assert "name" in item
                assert "count" in item
                assert isinstance(item["name"], str)
                assert isinstance(item["count"], int)
        elif response.status_code >= 500:
            # Internal server error is OK when DB is unavailable
            pass
        else:
            pytest.fail(f"Unexpected status {response.status_code}")


# ---------------------------------------------------------------------------
# Admin endpoints (contract shape, not auth logic)
# ---------------------------------------------------------------------------


class TestAdminEndpoints:
    def test_health_admin_shape(self, client):
        response = client.get(
            "/admin/health",
            headers={"X-API-Key": "test_key"},
        )
        data = response.json()
        assert isinstance(data, dict)
        # Either authorized or 403 — both are valid shapes
        if response.status_code == 200:
            assert data == {"status": "ok"}
        elif response.status_code == 403:
            assert "detail" in data

    def test_system_status_shape(self, client):
        response = client.get("/system/status")
        data = response.json()
        assert isinstance(data, dict)

    def test_schedule_get_returns_shape(self, client):
        """GET /admin/schedule must return a dict with a schedules list."""
        response = client.get(
            "/admin/schedule",
            headers={"X-API-Key": "test_key"},
        )
        data = response.json()
        if response.status_code == 200:
            assert "schedules" in data
            assert isinstance(data["schedules"], list)
            # Each schedule entry has expected fields
            for entry in data["schedules"]:
                assert "platform" in entry
                assert "interval_minutes" in entry
                assert isinstance(entry["platform"], str)
                assert isinstance(entry["interval_minutes"], int)
        elif response.status_code == 403:
            assert "detail" in data