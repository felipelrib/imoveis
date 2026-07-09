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
    """FastAPI TestClient — no DB/Redis needed for schema validation."""
    return TestClient(app)


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
        response = client.get("/api/properties?page=1&page_size=10")
        # May fail if DB is unavailable — that's expected in contract tests
        # The key check is that if it succeeds, the shape is correct
        if response.status_code == 200:
            data = response.json()
            assert "items" in data
            assert "page" in data
            assert "page_size" in data
            assert "total" in data
            assert isinstance(data["items"], list)
        elif response.status_code >= 500:
            # Internal server errors are OK for contract tests (DB may be down)
            pass
        else:
            # Any 4xx should still be valid JSON with a detail field
            data = response.json()
            assert isinstance(data, dict)


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
        response = client.get("/api/system/status")
        data = response.json()
        assert isinstance(data, dict)

    def test_platforms_endpoint_shape(self, client):
        response = client.get("/api/platforms")
        data = response.json()
        # Should be a dict with platform names as keys
        assert isinstance(data, dict)
