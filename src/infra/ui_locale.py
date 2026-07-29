"""Active UI locale resolution (Redis override + AppConfig default).

Shared by the admin API and AI enrichment workers so free-text generation
follows the same preference as SPA chrome (BIN-98 / BIN-101).
"""

from __future__ import annotations

from infra.logging import get_logger

logger = get_logger(__name__)

REDIS_KEY_UI_LOCALE = "ui:locale"


def resolve_active_locale(cfg, redis_client) -> str:
    """Return Redis override if it is in the allowlist, else YAML default.

    Invalid Redis values fall back silently to the YAML default.
    """
    supported = list(cfg.ui.supported_locales)
    default = cfg.ui.locale
    raw = redis_client.get(REDIS_KEY_UI_LOCALE)
    if raw is None:
        return default
    value = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    if value in supported:
        return value
    return default


def resolve_ai_output_language() -> str:
    """Language for new AI free-text (verdicts, reasonings, flags).

    Prefers the active UI locale (Redis → ``ui.locale``) so chrome and new
    enrichments stay aligned. Falls back to ``ai.output_language`` when the
    UI locale resolver is unavailable.
    """
    from infra.config import get_config

    cfg = get_config()
    try:
        from infra.redis_client import get_redis

        return resolve_active_locale(cfg, get_redis())
    except Exception as exc:  # workers may lack Redis briefly
        logger.debug("ai_output_language_fallback", error=str(exc))
        return getattr(getattr(cfg, "ui", None), "locale", None) or cfg.ai.output_language or "en"
