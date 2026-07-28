"""Unit tests for GET/POST /admin/locale (BIN-98)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from api.admin import REDIS_KEY_UI_LOCALE, resolve_active_locale


def _ui_cfg(locale: str = "en", supported: list[str] | None = None):
    return SimpleNamespace(
        ui=SimpleNamespace(
            locale=locale,
            supported_locales=supported or ["en", "pt-BR"],
        )
    )


@pytest.mark.unit
def test_resolve_active_locale_falls_back_to_yaml():
    redis = MagicMock()
    redis.get.return_value = None
    assert resolve_active_locale(_ui_cfg(), redis) == "en"


@pytest.mark.unit
def test_resolve_active_locale_uses_redis_override():
    redis = MagicMock()
    redis.get.return_value = b"pt-BR"
    assert resolve_active_locale(_ui_cfg(), redis) == "pt-BR"


@pytest.mark.unit
def test_resolve_active_locale_ignores_invalid_redis():
    redis = MagicMock()
    redis.get.return_value = "fr"
    assert resolve_active_locale(_ui_cfg(), redis) == "en"


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_get_locale_returns_shape(mock_get_config, mock_get_redis, _audit):
    from api.admin import get_locale

    mock_get_config.return_value = _ui_cfg()
    redis = MagicMock()
    redis.get.return_value = None
    mock_get_redis.return_value = redis

    data = get_locale()
    assert data == {
        "locale": "en",
        "default": "en",
        "supported": ["en", "pt-BR"],
    }
    redis.get.assert_called_once_with(REDIS_KEY_UI_LOCALE)


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_update_locale_persists_and_returns(mock_get_config, mock_get_redis, mock_audit):
    from api.admin import LocaleUpdateRequest, update_locale

    mock_get_config.return_value = _ui_cfg()
    redis = MagicMock()
    mock_get_redis.return_value = redis

    data = update_locale(LocaleUpdateRequest(locale="pt-BR"))
    assert data["locale"] == "pt-BR"
    assert data["default"] == "en"
    assert data["supported"] == ["en", "pt-BR"]
    redis.set.assert_called_once_with(REDIS_KEY_UI_LOCALE, "pt-BR")
    mock_audit.assert_called_once()


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_update_locale_rejects_unsupported(mock_get_config, mock_get_redis, _audit):
    from api.admin import LocaleUpdateRequest, update_locale

    mock_get_config.return_value = _ui_cfg()
    mock_get_redis.return_value = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        update_locale(LocaleUpdateRequest(locale="fr"))
    assert exc_info.value.status_code == 400
    assert "Unsupported locale" in str(exc_info.value.detail)


@pytest.mark.unit
@patch("api.admin.log_audit_action")
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
def test_locale_preference_round_trip(mock_get_config, mock_get_redis, _audit):
    """POST then GET returns the Redis override (preference round-trip)."""
    from api.admin import LocaleUpdateRequest, get_locale, update_locale

    store: dict[str, str] = {}
    redis = MagicMock()
    redis.get.side_effect = lambda k: store.get(k)
    redis.set.side_effect = lambda k, v: store.__setitem__(k, v)
    mock_get_redis.return_value = redis
    mock_get_config.return_value = _ui_cfg()

    assert get_locale()["locale"] == "en"
    update_locale(LocaleUpdateRequest(locale="pt-BR"))
    assert get_locale()["locale"] == "pt-BR"
