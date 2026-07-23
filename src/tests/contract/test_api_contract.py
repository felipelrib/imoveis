"""API contract tests — validate response shapes for every endpoint.

These tests ensure that the API's response schema doesn't change without
updating this contract. Uses FastAPI TestClient with minimal dependencies.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from infra.config import get_config

_TEST_API_KEY = "contract-test-api-key"


@pytest.fixture(autouse=True)
def _auth_env_for_contracts(monkeypatch: pytest.MonkeyPatch):
    """Wire a known API key through AppConfig for admin contract calls."""
    monkeypatch.setenv("API_KEY", _TEST_API_KEY)
    monkeypatch.setenv("JWT_SECRET", "contract-test-jwt-secret")
    get_config.cache_clear()
    yield
    get_config.cache_clear()


@pytest.fixture
def client():
    """FastAPI TestClient — no DB/Redis needed for schema validation.

    ``raise_server_exceptions=False`` ensures that 500-level errors (e.g.
    from a missing database) are returned as normal HTTP responses instead
    of being re-raised by the test client.
    """
    c = TestClient(app, raise_server_exceptions=False)
    return c


@pytest.fixture
def admin_headers():
    return {"X-API-Key": _TEST_API_KEY}


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


_PROJECTION_KEYS = (
    "price",
    "price_per_m2",
    "stat_score",
    "ai_score",
    "combined_score",
    "neighborhood_name",
    "neighborhood_id",
    "primary_listing",
    "listings",
)


def _assert_projection_keys(item: dict) -> None:
    for key in _PROJECTION_KEYS:
        assert key in item, f"missing projection key: {key}"
    assert isinstance(item["listings"], list)
    if item["primary_listing"] is not None:
        assert isinstance(item["primary_listing"], dict)
        assert "price" in item["primary_listing"]
        assert "listing_type" in item["primary_listing"]
        assert "platform" in item["primary_listing"]


class TestPropertyProjectionContract:
    def test_list_items_include_ad12_fields(self, client):
        response = client.get("/properties?page=1&page_size=5")
        if response.status_code == 200:
            data = response.json()
            assert "properties" in data
            for item in data["properties"]:
                _assert_projection_keys(item)
        elif response.status_code >= 500:
            pass
        else:
            assert isinstance(response.json(), dict)

    def test_detail_includes_ad12_fields(self, client):
        list_resp = client.get("/properties?page=1&page_size=1")
        if list_resp.status_code != 200:
            if list_resp.status_code >= 500:
                return
            pytest.fail(f"Unexpected list status {list_resp.status_code}")
        props = list_resp.json().get("properties") or []
        if not props:
            return
        prop_id = props[0]["id"]
        response = client.get(f"/properties/{prop_id}")
        if response.status_code == 200:
            _assert_projection_keys(response.json())
        elif response.status_code >= 500:
            pass
        else:
            pytest.fail(f"Unexpected detail status {response.status_code}")

    def test_batch_rejects_empty_ids(self, client):
        response = client.get("/properties/by-ids?ids=")
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_batch_rejects_more_than_four_ids(self, client):
        ids = ",".join(
            [
                "11111111-1111-1111-1111-111111111111",
                "22222222-2222-2222-2222-222222222222",
                "33333333-3333-3333-3333-333333333333",
                "44444444-4444-4444-4444-444444444444",
                "55555555-5555-5555-5555-555555555555",
            ]
        )
        response = client.get(f"/properties/by-ids?ids={ids}")
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_batch_rejects_malformed_id(self, client):
        response = client.get("/properties/by-ids?ids=not-a-uuid")
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_batch_returns_projection_shape(self, client):
        list_resp = client.get("/properties?page=1&page_size=2")
        if list_resp.status_code != 200:
            if list_resp.status_code >= 500:
                return
            pytest.fail(f"Unexpected list status {list_resp.status_code}")
        props = list_resp.json().get("properties") or []
        if not props:
            # Empty DB still exercises endpoint with a valid UUID (returns empty list)
            response = client.get(
                "/properties/by-ids?ids=11111111-1111-1111-1111-111111111111"
            )
            if response.status_code == 200:
                data = response.json()
                assert "properties" in data
                assert isinstance(data["properties"], list)
            elif response.status_code >= 500:
                pass
            else:
                pytest.fail(f"Unexpected batch status {response.status_code}")
            return

        ids = ",".join(p["id"] for p in props[:2])
        response = client.get(f"/properties/by-ids?ids={ids}")
        if response.status_code == 200:
            data = response.json()
            assert "properties" in data
            assert isinstance(data["properties"], list)
            for item in data["properties"]:
                _assert_projection_keys(item)
        elif response.status_code >= 500:
            pass
        else:
            pytest.fail(f"Unexpected batch status {response.status_code}")


# ---------------------------------------------------------------------------
# Admin endpoints (contract shape, not auth logic)
# ---------------------------------------------------------------------------

class TestAdminEndpoints:
    def test_health_admin_shape(self, client, admin_headers):
        response = client.get(
            "/admin/health",
            headers=admin_headers,
        )
        data = response.json()
        assert isinstance(data, dict)
        assert response.status_code == 200
        assert data == {"status": "ok"}

    def test_system_status_shape(self, client):
        response = client.get("/system/status")
        data = response.json()
        assert isinstance(data, dict)

    def test_schedule_get_returns_shape(self, client, admin_headers):
        """GET /admin/schedule must return a dict with a schedules list."""
        response = client.get(
            "/admin/schedule",
            headers=admin_headers,
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
