"""Unit tests for POST /admin/neighbourhoods/quality/load (BIN-87)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from infra.config import AuthConfig, get_config


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
    monkeypatch.setattr("api.auth.get_config", lambda: cfg)
    monkeypatch.setattr("infra.config.get_config", lambda: cfg)
    return TestClient(app, raise_server_exceptions=False), auth


@pytest.mark.unit
def test_admin_quality_load_returns_counts(client_with_auth):
    client, auth = client_with_auth
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)

    with (
        patch("api.admin.SessionLocal", return_value=session),
        patch(
            "core.neighbourhood_quality_yaml.load_curated_neighbourhood_quality",
            return_value=SimpleNamespace(updated=12, skipped=3),
        ) as mock_load,
        patch("api.admin.log_audit_action") as mock_audit,
    ):
        response = client.post(
            "/admin/neighbourhoods/quality/load",
            headers={"X-API-Key": auth.api_key},
        )

    assert response.status_code == 200, response.text
    assert response.json() == {"updated": 12, "skipped": 3}
    mock_load.assert_called_once()
    mock_audit.assert_called_once_with(
        "neighbourhood_quality_load",
        {"updated": 12, "skipped": 3},
    )


@pytest.mark.unit
def test_admin_quality_load_requires_auth(client_with_auth):
    client, _auth = client_with_auth
    response = client.post("/admin/neighbourhoods/quality/load")
    assert response.status_code in (401, 403)


@pytest.mark.unit
def test_admin_quality_load_yaml_error_is_500(client_with_auth):
    client, auth = client_with_auth
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)

    from core.neighbourhood_quality_yaml import NeighbourhoodQualityYamlError

    with (
        patch("api.admin.SessionLocal", return_value=session),
        patch(
            "core.neighbourhood_quality_yaml.load_curated_neighbourhood_quality",
            side_effect=NeighbourhoodQualityYamlError("bad yaml"),
        ),
        patch("api.admin.log_audit_action"),
    ):
        response = client.post(
            "/admin/neighbourhoods/quality/load",
            headers={"X-API-Key": auth.api_key},
        )

    assert response.status_code == 500
    assert "bad yaml" in response.json()["detail"]
