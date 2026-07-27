"""Unit tests for POST /admin/enrichment/missing (legacy wrapper)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.main import app
from infra.config import AIConfig, AuthConfig, PhotoGateConfig, ScrapingConfig, get_config


@pytest.fixture(autouse=True)
def _clear_config_cache():
    get_config.cache_clear()
    yield
    get_config.cache_clear()


def _auth_config(*, api_key: str = "test-valid-key") -> AuthConfig:
    return AuthConfig(
        api_key=api_key,
        jwt_secret="test-jwt-secret",
        principal_id="default",
        admin_user="admin",
        admin_pass="admin",
    )


@pytest.fixture
def client_with_auth(monkeypatch: pytest.MonkeyPatch):
    auth = _auth_config()
    cfg = MagicMock()
    cfg.auth = auth
    cfg.scraping = ScrapingConfig(photo_gate=PhotoGateConfig())
    cfg.ai = AIConfig()
    monkeypatch.setattr("api.auth.get_config", lambda: cfg)
    monkeypatch.setattr("infra.config.get_config", lambda: cfg)
    return TestClient(app, raise_server_exceptions=False), auth


def _prop(*, image_urls, description="Nice flat"):
    return SimpleNamespace(
        id=uuid4(),
        image_urls=image_urls,
        description=description,
        active=True,
        platform="zap",
        neighborhood_id=None,
    )


@pytest.mark.unit
def test_enrich_missing_queues_only_unenriched_with_enough_photos(client_with_auth):
    client, auth = client_with_auth
    enough = _prop(
        image_urls=[f"https://cdn.example/{i}.jpg" for i in range(8)]
    )
    too_few = _prop(
        image_urls=[f"https://cdn.example/{i}.jpg" for i in range(3)]
    )
    no_images = _prop(image_urls=[])
    null_images = _prop(image_urls=None)

    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    query = MagicMock()
    session.query.return_value = query
    query.outerjoin.return_value = query
    query.filter.return_value = query
    query.limit.return_value = query
    query.all.return_value = [
        (enough, None),
        (too_few, None),
        (no_images, None),
        (null_images, None),
    ]

    mock_enrich = MagicMock()
    with (
        patch("api.admin.SessionLocal", return_value=session),
        patch("adapters.queue.tasks.ai_enrich", mock_enrich),
        patch("api.admin.log_audit_action"),
    ):
        response = client.post(
            "/admin/enrichment/missing",
            headers={"X-API-Key": auth.api_key},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["queued_enrichments"] == 1
    assert body["skipped_no_images"] == 2
    assert body["skipped_too_few_photos"] == 1
    mock_enrich.apply_async.assert_called_once_with(
        args=[str(enough.id), enough.image_urls, "Nice flat"],
        kwargs={"stages": "all"},
        queue="ai",
    )


@pytest.mark.unit
def test_enrich_missing_requires_admin_credential(client_with_auth):
    client, _ = client_with_auth
    response = client.post("/admin/enrichment/missing")
    assert response.status_code == 401
