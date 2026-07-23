"""Notifier module — pluggable alert channels for price-drop notifications."""

from __future__ import annotations

from typing import List

from adapters.notify.base import Notifier
from infra.config import get_config
from infra.logging import get_logger

logger = get_logger(__name__)

_notifiers: List[Notifier] | None = None


def _build_notifiers() -> List[Notifier]:
    """Build notifier list from config."""
    from adapters.notify.log_notifier import LogNotifier
    from adapters.notify.redis_notifier import RedisNotifier
    from adapters.notify.email_notifier import EmailNotifier

    cfg = get_config()
    channels = getattr(cfg, "alerts", None)
    if channels is None or not channels.enabled:
        return [LogNotifier()]

    result: List[Notifier] = []
    for ch in channels.channels:
        ch_type = ch.get("type", "log") if isinstance(ch, dict) else ch
        if ch_type == "redis":
            result.append(RedisNotifier())
        elif ch_type == "email":
            result.append(EmailNotifier())
        else:
            result.append(LogNotifier())

    return result or [LogNotifier()]


def get_notifiers() -> List[Notifier]:
    """Return the configured notifier instances (cached)."""
    global _notifiers
    if _notifiers is None:
        _notifiers = _build_notifiers()
    return _notifiers


def reset_notifiers() -> None:
    """Reset the cached notifiers (useful in tests)."""
    global _notifiers
    _notifiers = None
