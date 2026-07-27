"""Unit tests for POST /admin/neighbourhoods/listing-claims/refresh (BIN-93)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from infra.config import AuthConfig, ListingClaimStatsConfig, get_config


@pytest.fixture(autouse=True)
def _clear_config_cache():
    get_config.cache_clear()
    yield
    get_config.cache_clear()


@pytest.fixture
def client_with_auth(monkeypatch: pytest.MonkeyPatch):
    auth = AuthConfig(
        api_key="test-valid-key",
        jwt_secret="test-jwt-secret",
        principal_id="default",
        admin_user="admin",
        admin_pass="admin",
    )
    cfg = MagicMock()
    cfg.auth = auth
    cfg.neighbourhood_quality.listing_claim_stats = ListingClaimStatsConfig(
        enabled=True
    )
    monkeypatch.setattr("api.auth.get_config", lambda: cfg)
    monkeypatch.setattr("infra.config.get_config", lambda: cfg)
    monkeypatch.setattr("api.admin.get_config", lambda: cfg)
    return TestClient(app, raise_server_exceptions=False), auth, cfg


@pytest.mark.unit
def test_admin_listing_claims_refresh_queues(client_with_auth):
    client, auth, _cfg = client_with_auth
    async_result = MagicMock(id="task-claim-1")
    with (
        patch(
            "adapters.queue.tasks.refresh_listing_claim_stats_task.apply_async",
            return_value=async_result,
        ) as mock_apply,
        patch("api.admin.log_audit_action") as mock_audit,
    ):
        response = client.post(
            "/admin/neighbourhoods/listing-claims/refresh",
            headers={"X-API-Key": auth.api_key},
        )
    assert response.status_code == 200, response.text
    assert response.json() == {"queued": True, "task_id": "task-claim-1"}
    mock_apply.assert_called_once_with(queue="scrapers")
    mock_audit.assert_called_once_with(
        "listing_claim_stats_refresh",
        {"task_id": "task-claim-1"},
    )


@pytest.mark.unit
def test_admin_listing_claims_refresh_disabled(client_with_auth):
    client, auth, cfg = client_with_auth
    cfg.neighbourhood_quality.listing_claim_stats = ListingClaimStatsConfig(
        enabled=False
    )
    response = client.post(
        "/admin/neighbourhoods/listing-claims/refresh",
        headers={"X-API-Key": auth.api_key},
    )
    assert response.status_code == 400
    assert "disabled" in response.json()["detail"]
