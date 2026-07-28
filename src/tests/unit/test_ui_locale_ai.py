"""BIN-101 — resolve_ai_output_language follows active UI locale."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from infra.ui_locale import resolve_active_locale, resolve_ai_output_language


@pytest.mark.unit
def test_resolve_ai_output_language_prefers_redis(monkeypatch: pytest.MonkeyPatch):
    cfg = MagicMock()
    cfg.ui.locale = "en"
    cfg.ui.supported_locales = ["en", "pt-BR"]
    cfg.ai.output_language = "en"

    redis = MagicMock()
    redis.get.return_value = b"pt-BR"

    monkeypatch.setattr("infra.config.get_config", lambda: cfg)
    monkeypatch.setattr("infra.redis_client.get_redis", lambda: redis)

    assert resolve_ai_output_language() == "pt-BR"
    assert resolve_active_locale(cfg, redis) == "pt-BR"


@pytest.mark.unit
def test_resolve_ai_output_language_falls_back_on_redis_error(
    monkeypatch: pytest.MonkeyPatch,
):
    cfg = MagicMock()
    cfg.ui.locale = "pt-BR"
    cfg.ui.supported_locales = ["en", "pt-BR"]
    cfg.ai.output_language = "en"

    monkeypatch.setattr("infra.config.get_config", lambda: cfg)

    def _boom():
        raise ConnectionError("redis down")

    monkeypatch.setattr("infra.redis_client.get_redis", _boom)
    assert resolve_ai_output_language() == "pt-BR"
