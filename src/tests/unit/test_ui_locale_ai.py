"""BIN-101 — resolve_ai_output_language follows active UI locale."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from infra.config import get_config
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


@pytest.mark.unit
def test_shipped_default_writes_new_ai_free_text_in_pt_br(
    monkeypatch: pytest.MonkeyPatch,
):
    """The real configs/app_config.yaml, with no Redis override, writes pt-BR.

    Every other test here hands the resolver a MagicMock, so nothing pinned what
    the *shipped* config actually resolves to — and v0.13-s1.6 flipped
    ``ui.locale`` to pt-BR, which BIN-101 makes the language of new verdicts,
    visual descriptions and sentiment summaries, not only of SPA chrome. That
    reach is the reason this assertion exists: a future edit to ``ui.locale``
    changes model output, and it should fail a test rather than surface as
    Portuguese free text nobody asked for.
    """
    redis = MagicMock()
    redis.get.return_value = None  # no ui:locale override set
    monkeypatch.setattr("infra.redis_client.get_redis", lambda: redis)

    cfg = get_config()
    assert cfg.ui.locale == "pt-BR"
    assert resolve_ai_output_language() == "pt-BR"


@pytest.mark.unit
def test_ai_output_language_alone_cannot_change_the_language(
    monkeypatch: pytest.MonkeyPatch,
):
    """``ai.output_language`` is unreachable while ``ui.locale`` is set.

    The resolver's Redis-failure fallback reads ``ui.locale`` first and only
    reaches ``ai.output_language`` when that is falsy — which a
    ``Literal["en", "pt-BR"]`` field never is. An operator editing
    ``ai.output_language`` to get English verdicts changes nothing, so the config
    comment says so and this pins the behaviour it describes.
    """
    cfg = MagicMock()
    cfg.ui.locale = "pt-BR"
    cfg.ui.supported_locales = ["en", "pt-BR"]
    cfg.ai.output_language = "en"

    monkeypatch.setattr("infra.config.get_config", lambda: cfg)

    def _boom():
        raise ConnectionError("redis down")

    monkeypatch.setattr("infra.redis_client.get_redis", _boom)
    assert resolve_ai_output_language() == "pt-BR"
