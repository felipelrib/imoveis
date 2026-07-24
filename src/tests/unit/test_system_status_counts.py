"""Unit tests for GET /system/status property counts (BIN-60)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.system import _check_db_and_counts
from infra.config import get_config


@pytest.fixture(autouse=True)
def _clear_config_cache():
    get_config.cache_clear()
    yield
    get_config.cache_clear()


@pytest.mark.unit
def test_check_db_and_counts_returns_none_on_error():
    """DB failures must not report total_properties=0 (false empty DB)."""
    with patch("infra.db.SessionLocal", side_effect=RuntimeError("connection refused")):
        status, total, enriched = _check_db_and_counts()
    assert status["status"] == "error"
    assert "connection refused" in status["detail"]
    assert total is None
    assert enriched is None


@pytest.mark.unit
def test_system_status_omits_zero_counts_when_db_errors():
    client = TestClient(app, raise_server_exceptions=False)
    redis = MagicMock()
    redis.exists.return_value = 0
    with (
        patch("api.system.get_redis", return_value=redis),
        patch(
            "api.system._check_db_and_counts",
            return_value=({"status": "error", "detail": "boom"}, None, None),
        ),
        patch("api.system._check_redis", return_value={"status": "ok"}),
        patch(
            "api.system._check_ollama",
            new_callable=AsyncMock,
            return_value={"status": "ok", "models": []},
        ),
        patch("api.system._check_workers", return_value={"status": "ok"}),
    ):
        response = client.get("/system/status")
    assert response.status_code == 200
    data = response.json()
    assert data["database"]["status"] == "error"
    assert data["stats"]["total_properties"] is None
    assert data["stats"]["enriched_properties"] is None
