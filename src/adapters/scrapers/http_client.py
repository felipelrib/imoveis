"""Proxy-aware HTTP client factory for scrapers (AD-5 / FR-20).

Selection happens once per session. Platform ``extra.proxy`` overrides the
global pool when set; otherwise ``AppConfig.proxy`` drives rotation.
"""

from __future__ import annotations

import random
import threading
from typing import Any

import httpx

from infra.config import ProxyConfig, get_config

_rr_lock = threading.Lock()
_rr_index = 0


def reset_round_robin() -> None:
    """Reset the process-local round-robin counter (for tests)."""
    global _rr_index
    with _rr_lock:
        _rr_index = 0


def resolve_proxy_url(
    proxy: ProxyConfig,
    platform_override: str | None = None,
) -> str | None:
    """Pick a proxy URL for one HTTP session.

    Resolution order:
    1. Non-null ``platform_override`` → fixed platform proxy (no rotation).
    2. ``proxy.enabled`` false → direct (``None``).
    3. Non-empty ``pool`` → rotate per ``rotation_strategy``.
    4. Single ``url`` → that URL.
    5. Otherwise → direct (``None``).
    """
    if platform_override:
        return platform_override

    if not proxy.enabled:
        return None

    if proxy.pool:
        if proxy.rotation_strategy == "random":
            return random.choice(proxy.pool)
        global _rr_index
        with _rr_lock:
            url = proxy.pool[_rr_index % len(proxy.pool)]
            _rr_index += 1
            return url

    if proxy.url:
        return proxy.url

    return None


def create_scraper_http_client(
    proxy: ProxyConfig | None = None,
    platform_override: str | None = None,
    **client_kwargs: Any,
) -> httpx.Client:
    """Build an ``httpx.Client`` with the resolved proxy (or direct)."""
    cfg = proxy if proxy is not None else get_config().proxy
    selected = resolve_proxy_url(cfg, platform_override=platform_override)
    return httpx.Client(proxy=selected, **client_kwargs)
