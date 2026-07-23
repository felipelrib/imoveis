"""Proxy-aware HTTP client factory for scrapers (AD-5 / FR-20).

Selection happens once per session. Platform ``extra.proxy`` overrides the
global pool when set; otherwise ``AppConfig.proxy`` drives rotation.
"""

from __future__ import annotations

import secrets
import threading
from typing import Any
from urllib.parse import urlparse

import httpx

from infra.config import ProxyConfig, get_config
from infra.logging import get_logger

logger = get_logger(__name__)

_rr_lock = threading.Lock()
_rr_index = 0


def reset_round_robin() -> None:
    """Reset the process-local round-robin counter (for tests)."""
    global _rr_index
    with _rr_lock:
        _rr_index = 0


def redact_proxy_url(url: str | None) -> str | None:
    """Return scheme://host:port with userinfo stripped, or None."""
    if not url:
        return None
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return None
    port = f":{parsed.port}" if parsed.port else ""
    scheme = f"{parsed.scheme}://" if parsed.scheme else ""
    return f"{scheme}{host}{port}"


def proxy_mode_summary(
    proxy: ProxyConfig,
    platform_override: str | None = None,
    selected: str | None = None,
) -> dict[str, Any]:
    """Safe operational fields for logs / Redis (no credentials)."""
    if platform_override:
        mode = "override"
    elif not proxy.enabled or selected is None:
        mode = "direct"
    elif proxy.pool:
        mode = "pool"
    elif proxy.url:
        mode = "single"
    else:
        mode = "direct"

    return {
        "proxy_enabled": proxy.enabled,
        "proxy_mode": mode,
        "rotation_strategy": proxy.rotation_strategy,
        "pool_size": len(proxy.pool),
        "proxy_host": redact_proxy_url(selected),
    }


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
            return secrets.choice(proxy.pool)
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
    summary = proxy_mode_summary(cfg, platform_override=platform_override, selected=selected)
    logger.info("scraper_proxy_mode", **summary)
    client = httpx.Client(proxy=selected, **client_kwargs)
    # Safe fields for scrape-run Redis status (no credentials).
    client.imoveis_proxy_summary = summary  # type: ignore[attr-defined]
    return client
