"""Unit tests for AppConfig-backed API credential at the edge (BIN-44)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api.main import app
from infra.config import AuthConfig, get_config


@pytest.fixture(autouse=True)
def _clear_config_cache():
    get_config.cache_clear()
    yield
    get_config.cache_clear()


def _auth_config(
    *,
    api_key: str = "test-valid-key",
    jwt_secret: str = "test-jwt-secret",
    principal_id: str = "default",
    admin_user: str = "admin",
    admin_pass: str = "admin",
) -> AuthConfig:
    return AuthConfig(
        api_key=api_key,
        jwt_secret=jwt_secret,
        principal_id=principal_id,
        admin_user=admin_user,
        admin_pass=admin_pass,
    )


@pytest.fixture
def client_with_auth(monkeypatch: pytest.MonkeyPatch):
    """TestClient with a known AuthConfig (no real env dependency)."""
    auth = _auth_config(principal_id="tenant-a")
    cfg = MagicMock()
    cfg.auth = auth
    monkeypatch.setattr("api.auth.get_config", lambda: cfg)
    monkeypatch.setattr("infra.config.get_config", lambda: cfg)
    return TestClient(app, raise_server_exceptions=False), auth


@pytest.mark.unit
def test_admin_rejects_missing_credential(client_with_auth):
    client, _ = client_with_auth
    response = client.get("/admin/health")
    assert response.status_code == 401
    assert "detail" in response.json()


@pytest.mark.unit
def test_admin_rejects_invalid_api_key(client_with_auth):
    client, _ = client_with_auth
    response = client.get("/admin/health", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 403
    assert "API Key" in response.json()["detail"] or "validate" in response.json()["detail"].lower()


@pytest.mark.unit
def test_admin_accepts_valid_api_key(client_with_auth):
    client, auth = client_with_auth
    response = client.get("/admin/health", headers={"X-API-Key": auth.api_key})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.unit
def test_admin_rejects_when_api_key_not_configured(monkeypatch: pytest.MonkeyPatch):
    cfg = MagicMock()
    cfg.auth = _auth_config(api_key="")
    monkeypatch.setattr("api.auth.get_config", lambda: cfg)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/admin/health", headers={"X-API-Key": "any-key"})
    assert response.status_code == 403
    assert "not configured" in response.json()["detail"].lower()


@pytest.mark.unit
def test_verify_api_key_returns_stable_principal(monkeypatch: pytest.MonkeyPatch):
    from api.auth import verify_api_key

    cfg = MagicMock()
    cfg.auth = _auth_config(principal_id="stable-principal")
    monkeypatch.setattr("api.auth.get_config", lambda: cfg)

    principal = verify_api_key(cfg.auth.api_key)
    assert principal.id == "stable-principal"
    assert principal.method == "api_key"


@pytest.mark.unit
def test_admin_jwt_maps_to_same_principal(client_with_auth):
    client, auth = client_with_auth
    login = client.post(
        "/auth/admin/login",
        data={"username": auth.admin_user, "password": auth.admin_pass},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    response = client.get("/admin/health", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.unit
def test_api_key_loaded_via_appconfig_env_channel(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """API_KEY reaches auth only through AppConfig load path (AD-2)."""
    from infra.config import load_config

    cfg_file = tmp_path / "app_config.yaml"
    cfg_file.write_text("auth:\n  api_key: ''\n  principal_id: from-env\n")
    monkeypatch.setenv("API_KEY", "env-wired-key")
    for key in list(os.environ):
        if key.startswith("IMOVEIS_"):
            monkeypatch.delenv(key, raising=False)

    cfg = load_config(cfg_file)
    assert cfg.auth.api_key == "env-wired-key"
    assert cfg.auth.principal_id == "from-env"

    # auth module must not read os.environ for API_KEY directly
    import inspect

    import api.auth as auth_mod

    source = inspect.getsource(auth_mod)
    assert "os.environ" not in source
    assert "os.getenv" not in source
