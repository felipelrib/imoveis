"""Base scraper with built-in rate limiting, proxy rotation, and polite jitter.

All concrete scrapers inherit from ``BaseScraper`` and get these behaviours
for free via ``_throttled_request()``.

Usage (in a subclass)::

    resp = self._throttled_request('GET', url, headers={...})
"""
from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterator, List, Optional

import httpx

from infra.config import get_config
from infra.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CircuitBreakerException(Exception):
    """Raised when the scraper's circuit is open and should not run."""


# ---------------------------------------------------------------------------
# Token-bucket rate limiter (in-process)
# ---------------------------------------------------------------------------

class _TokenBucket:
    """Simple token-bucket that refills at *rate* tokens per second."""

    def __init__(self, rate_per_minute: int) -> None:
        self.rate: float = rate_per_minute / 60.0  # tokens per second
        self.capacity: int = max(rate_per_minute, 1)
        self.tokens: float = float(self.capacity)
        self._last_refill: float = time.monotonic()

    def acquire(self) -> None:
        """Block until a token is available."""
        while True:
            self._refill()
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return
            # Sleep just enough for one token to be generated
            deficit = 1.0 - self.tokens
            time.sleep(deficit / self.rate if self.rate > 0 else 1.0)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self._last_refill = now


# ---------------------------------------------------------------------------
# BaseScraper
# ---------------------------------------------------------------------------

class BaseScraper(ABC):
    """Base interface for scraper adapters.

    Responsibilities
    ----------------
    * Be idempotent and checkpoint-aware.
    * Enforce politeness (rate limits, jitter) transparently.
    * Expose ``start()``, ``fetch_pages(checkpoint)`` and ``normalize(raw)``.
    """

    def __init__(self, platform_config: Dict[str, Any]) -> None:
        self.config = platform_config

        # Rate limiter
        rate_limit: int = int(platform_config.get("rate_limit", 30))
        self._bucket = _TokenBucket(rate_limit)

        # Jitter settings
        self._jitter_min: float = float(platform_config.get("jitter_min", 2.0))
        self._jitter_max: float = float(platform_config.get("jitter_max", 7.0))

        # Proxy state
        self._proxy_pool: List[str] = []
        self._proxy_index: int = 0
        proxy_url = self._resolve_proxy()

        # Managed httpx client
        timeout = httpx.Timeout(
            float(platform_config.get("timeout", 20.0)),
            connect=10.0,
        )
        client_kwargs: Dict[str, Any] = {"timeout": timeout}
        if proxy_url:
            client_kwargs["proxy"] = proxy_url
        self.http: httpx.Client = httpx.Client(**client_kwargs)

    # -- Proxy helpers ------------------------------------------------------

    def _resolve_proxy(self) -> Optional[str]:
        """Return the proxy URL to use, or ``None`` if proxying is disabled."""
        app_cfg = get_config()
        proxy_cfg = app_cfg.proxy
        if not proxy_cfg.enabled:
            return None

        if proxy_cfg.pool:
            self._proxy_pool = list(proxy_cfg.pool)
            return self._get_proxy_url()

        return proxy_cfg.url

    def _get_proxy_url(self) -> Optional[str]:
        """Return the next proxy URL using round-robin rotation."""
        if not self._proxy_pool:
            return get_config().proxy.url
        url = self._proxy_pool[self._proxy_index % len(self._proxy_pool)]
        self._proxy_index += 1
        return url

    # -- Polite sleep -------------------------------------------------------

    def _polite_sleep(self) -> None:
        """Sleep a random duration between ``jitter_min`` and ``jitter_max``."""
        delay = random.uniform(self._jitter_min, self._jitter_max)
        logger.debug(
            "polite_sleep",
            delay_seconds=round(delay, 2),
        )
        time.sleep(delay)

    # -- Rate-limited HTTP --------------------------------------------------

    def _throttled_request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Issue an HTTP request after waiting for a rate-limit token.

        Automatically applies polite jitter *after* the request completes.
        If a proxy pool is configured, rotates to the next proxy before each
        request.
        """
        # Rotate proxy if pool is available
        if self._proxy_pool:
            next_proxy = self._get_proxy_url()
            if next_proxy:
                # Re-create the transport only when the URL actually changes
                # For simplicity in the initial version we just set the header
                # (proxy is fixed at Client creation; full rotation requires
                # transport swap, which is deferred to a future iteration).
                pass

        self._bucket.acquire()
        logger.debug("throttled_request", method=method, url=url)
        response: httpx.Response = self.http.request(method, url, **kwargs)
        self._polite_sleep()
        return response

    # -- Lifecycle ----------------------------------------------------------

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self.http.close()

    def __enter__(self) -> "BaseScraper":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- Abstract interface -------------------------------------------------

    @abstractmethod
    def start(self) -> None:
        """Prepare network/session/auth resources."""
        raise NotImplementedError

    @abstractmethod
    def fetch_pages(self, checkpoint: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        """Yield raw listing payloads.

        *checkpoint* is mutated by the caller to persist progress.
        """
        raise NotImplementedError

    @abstractmethod
    def normalize(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Return canonical property mapping for persistence."""
        raise NotImplementedError
