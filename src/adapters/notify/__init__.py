"""Notifier module — pluggable alert channels for price-drop notifications."""

from __future__ import annotations

from typing import List, Tuple

from adapters.notify.base import Notifier
from infra.config import get_config
from infra.logging import get_logger

logger = get_logger(__name__)

# The one registry (AD-9): each notifier with the channel type it was built for.
_registry: List[Tuple[str, Notifier]] | None = None


def _build_registry() -> List[Tuple[str, Notifier]]:
    """Build the (channel type, notifier) registry from config."""
    from adapters.notify.email_notifier import EmailNotifier
    from adapters.notify.log_notifier import LogNotifier
    from adapters.notify.redis_notifier import RedisNotifier

    cfg = get_config()
    channels = getattr(cfg, "alerts", None)
    if channels is None or not channels.enabled:
        return [("log", LogNotifier())]

    result: List[Tuple[str, Notifier]] = []
    for ch in channels.channels:
        ch_type = ch.get("type", "log") if isinstance(ch, dict) else ch
        if ch_type == "redis":
            result.append(("redis", RedisNotifier()))
        elif ch_type == "email":
            result.append(("email", EmailNotifier()))
        else:
            result.append(("log", LogNotifier()))

    return result or [("log", LogNotifier())]


def _get_registry() -> List[Tuple[str, Notifier]]:
    global _registry
    if _registry is None:
        _registry = _build_registry()
    return _registry


def get_notifiers() -> List[Notifier]:
    """Return the configured notifier instances (cached)."""
    return [notifier for _channel, notifier in _get_registry()]


def get_notifiers_for_channel(channel: str) -> List[Notifier]:
    """Return the cached registry's notifiers of one channel type.

    Empty when alerts are disabled or the channel is not configured: a message
    that belongs to one channel (Story 1.9: email only) then goes nowhere,
    never to another channel.
    """
    return [notifier for ch_type, notifier in _get_registry() if ch_type == channel]


def reset_notifiers() -> None:
    """Reset the cached notifiers (useful in tests)."""
    global _registry
    _registry = None
