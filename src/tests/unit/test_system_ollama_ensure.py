"""Unit tests for POST /system/ollama/ensure (BIN-59)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from infra.config import AuthConfig, get_config


@pytest.fixture(autouse=True)
def _clear_config_cache():
    get_config.cache_clear()
    yield
    get_config.cache_clear()


def _auth_cfg(api_key: str = "test-valid-key") -> AuthConfig:
    return AuthConfig(
        api_key=api_key,
        jwt_secret="test-jwt-secret",
        principal_id="default",
        admin_user="admin",
        admin_pass="admin",
    )


@pytest.fixture
def client_with_auth(monkeypatch: pytest.MonkeyPatch):
    auth = _auth_cfg()
    cfg = MagicMock()
    cfg.auth = auth
    cfg.ai.ollama_url = "http://localhost:11434"
    monkeypatch.setattr("api.auth.get_config", lambda: cfg)
    monkeypatch.setattr("api.system.get_config", lambda: cfg)
    return TestClient(app, raise_server_exceptions=False), auth


@pytest.mark.unit
def test_ollama_ensure_requires_credential(client_with_auth):
    client, _ = client_with_auth
    response = client.post("/system/ollama/ensure")
    assert response.status_code in (401, 403)


@pytest.mark.unit
def test_ollama_ensure_already_running(client_with_auth):
    client, auth = client_with_auth
    with patch(
        "api.system._check_ollama",
        new_callable=AsyncMock,
        return_value={"status": "ok", "models": ["llava:latest"]},
    ):
        response = client.post(
            "/system/ollama/ensure",
            headers={"X-API-Key": auth.api_key},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "already_running"
    assert data["models"] == ["llava:latest"]


@pytest.mark.unit
def test_ollama_ensure_error_when_unreachable_and_no_binary(client_with_auth):
    client, auth = client_with_auth
    with (
        patch(
            "api.system._check_ollama",
            new_callable=AsyncMock,
            return_value={"status": "error", "detail": "connection refused"},
        ),
        patch("api.system.shutil.which", return_value=None),
    ):
        response = client.post(
            "/system/ollama/ensure",
            headers={"X-API-Key": auth.api_key},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert "host" in data["detail"].lower() or "outside docker" in data["detail"].lower()


@pytest.mark.unit
def test_ollama_ensure_started_after_local_popen(client_with_auth):
    client, auth = client_with_auth
    probes = [
        {"status": "error", "detail": "down"},
        {"status": "ok", "models": ["mistral"]},
    ]

    async def _probe():
        return probes.pop(0)

    with (
        patch("api.system._check_ollama", side_effect=_probe),
        patch("api.system.shutil.which", return_value="/usr/bin/ollama"),
        patch("api.system.subprocess.Popen") as popen,
        patch("api.system.time.sleep"),
    ):
        response = client.post(
            "/system/ollama/ensure",
            headers={"X-API-Key": auth.api_key},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "started"
    popen.assert_called_once()
