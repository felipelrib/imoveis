"""Regression tests for BIN-150: gate /system/* introspection endpoints behind auth.

Previously only ``POST /system/ollama/ensure`` had ``verify_admin_access``; the
five GET routes below were all open — any unauthenticated caller could read
queue depths, worker node names, proxy-pool health, DB/Redis/Ollama status, and
the last 100 price-drop alerts (with ``property_id`` + price).

Fix:
- ``/status``, ``/pipeline``, ``/pipeline/history``, ``/alerts`` — the SPA
  (``App.jsx`` status chrome, ``Dashboard.jsx``, ``ScraperControl.jsx``) calls
  these without pasting an admin credential today, so they use the same
  ``verify_api_key_if_configured`` edge rule as ``GET /properties/export``
  (Epic 2): open when no admin API key is configured (dev/local default),
  required once one is. ``frontend/src/api.ts`` now attaches ``X-API-Key``
  when a credential has been pasted, matching ``exportProperties``.
- ``/ollama/status`` — not called by the SPA (only ``POST /ollama/ensure`` is,
  which already required admin credentials), so it gets the full
  ``verify_admin_access`` gate to match its sibling POST route.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from infra.config import AuthConfig, ProxyConfig, get_config


@pytest.fixture(autouse=True)
def _clear_config_cache():
    get_config.cache_clear()
    yield
    get_config.cache_clear()


def _auth_cfg(api_key: str) -> AuthConfig:
    return AuthConfig(
        api_key=api_key,
        jwt_secret="test-jwt-secret",
        principal_id="default",
        admin_user="admin",
        admin_pass="admin",
    )


@pytest.fixture
def client_with_key(monkeypatch: pytest.MonkeyPatch):
    """A configured admin API key — the common deployed state (.env.local.example)."""
    auth = _auth_cfg("test-valid-key")
    cfg = MagicMock()
    cfg.auth = auth
    monkeypatch.setattr("api.auth.get_config", lambda: cfg)
    monkeypatch.setattr("infra.config.get_config", lambda: cfg)
    return TestClient(app, raise_server_exceptions=False), auth


@pytest.fixture
def client_without_key(monkeypatch: pytest.MonkeyPatch):
    """No admin API key configured — the Dashboard must keep working anonymously."""
    auth = _auth_cfg("")
    cfg = MagicMock()
    cfg.auth = auth
    cfg.proxy = ProxyConfig(enabled=False, url=None, pool=[])
    cfg.scraping.platforms = {}
    monkeypatch.setattr("api.auth.get_config", lambda: cfg)
    monkeypatch.setattr("infra.config.get_config", lambda: cfg)
    monkeypatch.setattr("api.system.get_config", lambda: cfg)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Reject anonymous access once an admin API key is configured
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "path",
    [
        "/system/status",
        "/system/pipeline",
        "/system/pipeline/history",
        "/system/alerts",
        "/system/ollama/status",
    ],
)
def test_gated_system_routes_reject_anonymous_when_key_configured(client_with_key, path):
    """BIN-150: these were open; must now require credentials once an admin API key exists."""
    client, _ = client_with_key
    response = client.get(path)
    assert response.status_code in (401, 403)


@pytest.mark.unit
@pytest.mark.parametrize(
    "path",
    [
        "/system/status",
        "/system/pipeline",
        "/system/pipeline/history",
        "/system/alerts",
        "/system/ollama/status",
    ],
)
def test_gated_system_routes_accept_valid_key(client_with_key, path):
    client, auth = client_with_key
    with (
        patch("api.system.get_redis", return_value=_redis_stub()),
        patch("api.system._check_db_and_counts", return_value=({"status": "ok"}, 1, 1)),
        patch("api.system._check_redis", return_value={"status": "ok"}),
        patch("api.system._check_ollama", new_callable=AsyncMock, return_value={"status": "ok", "models": []}),
        patch("api.system._check_workers", return_value={"status": "ok"}),
        patch("infra.db.SessionLocal", return_value=_session_cm_stub()),
        patch("adapters.metrics.pipeline_snapshots.list_snapshots_since", return_value=[]),
    ):
        response = client.get(path, headers={"X-API-Key": auth.api_key})
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Dashboard/ScraperControl/App chrome must keep working without a pasted key
# when no admin API key is configured server-side (BIN-150 acceptance
# criteria: don't break the credential-gated frontend flow, BIN-46).
# ---------------------------------------------------------------------------


def _redis_stub():
    redis = MagicMock()
    redis.exists.return_value = 0
    redis.llen.return_value = 0
    redis.get.return_value = None
    redis.lrange.return_value = []
    return redis


def _session_cm_stub():
    cm = MagicMock()
    cm.__enter__.return_value = MagicMock()
    cm.__exit__.return_value = False
    return cm


@pytest.mark.unit
def test_status_stays_open_when_key_not_configured(client_without_key):
    with (
        patch("api.system.get_redis", return_value=_redis_stub()),
        patch("api.system._check_db_and_counts", return_value=({"status": "ok"}, 1, 1)),
        patch("api.system._check_redis", return_value={"status": "ok"}),
        patch("api.system._check_ollama", new_callable=AsyncMock, return_value={"status": "ok", "models": []}),
        patch("api.system._check_workers", return_value={"status": "ok"}),
    ):
        response = client_without_key.get("/system/status")
    assert response.status_code == 200


@pytest.mark.unit
def test_pipeline_stays_open_when_key_not_configured(client_without_key):
    with patch("api.system.get_redis", return_value=_redis_stub()):
        response = client_without_key.get("/system/pipeline")
    assert response.status_code == 200


@pytest.mark.unit
def test_pipeline_history_stays_open_when_key_not_configured(client_without_key):
    with (
        patch("infra.db.SessionLocal", return_value=_session_cm_stub()),
        patch("adapters.metrics.pipeline_snapshots.list_snapshots_since", return_value=[]),
    ):
        response = client_without_key.get("/system/pipeline/history")
    assert response.status_code == 200
    assert response.json() == {"points": []}


@pytest.mark.unit
def test_alerts_stays_open_when_key_not_configured(client_without_key):
    with patch("api.system.get_redis", return_value=_redis_stub()):
        response = client_without_key.get("/system/alerts")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.unit
def test_ollama_status_stays_gated_even_when_no_key_configured(client_without_key):
    """Unlike the four read routes above, /ollama/status keeps the full admin
    gate (it isn't called by the SPA) — an unconfigured deployment must reject
    it rather than silently allow anonymous access, matching /ollama/ensure.

    No credential is presented at all here (unlike verify_api_key with an
    invalid key), so verify_admin_access falls through to its final branch:
    401 "Could not validate credentials" (same as test_admin_rejects_missing_credential
    for /admin/health).
    """
    response = client_without_key.get("/system/ollama/status")
    assert response.status_code == 401
    assert "detail" in response.json()
