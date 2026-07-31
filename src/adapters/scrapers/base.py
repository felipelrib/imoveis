from abc import ABC, abstractmethod
from typing import Generator

import httpx

from adapters.scrapers.flaresolverr import CloudflareFallbackSession, FlareSolverrSession
from adapters.scrapers.http_client import create_scraper_http_client
from infra.config import get_config
from infra.logging import get_logger

logger = get_logger(__name__)


class CircuitBreakerException(Exception):
    """Exception raised when a circuit breaker is open."""


class BaseScraper(ABC):
    """Base interface for scraper adapters.

    Responsibilities
    ----------------
    * Be idempotent and checkpoint-aware.
    * Enforce politeness (rate limits, jitter) transparently.
    * Expose ``start()``, ``fetch_pages(checkpoint)`` and ``normalize(raw)``.
    * Obtain HTTP clients via ``create_http_session()`` (proxy contract / AD-5).
    """

    def __init__(self, platform_name: str, config: dict):
        self.platform_name = platform_name
        self.config = config
        self.proxy_summary: dict = {}

    def create_http_session(self):
        """Build the HTTP session for this scraper.

        Non-null ``extra.proxy`` is a fixed per-platform override; ``null`` /
        absent defers to ``AppConfig.proxy`` rotation. When
        ``scraping.cloudflare_bypass`` is enabled, GETs route through a
        FlareSolverr sidecar (BIN-246/BIN-247) — a drop-in session, so
        throttling/circuit-breaker in the scraper stay unchanged. Platforms on
        the ``platforms`` always-list bypass on every request; any other platform
        gets an auto-fallback session (direct first, FlareSolverr only on a
        Cloudflare 403) when ``auto_fallback`` is on.
        """
        override = (self.config.get("extra") or {}).get("proxy")
        client = create_scraper_http_client(platform_override=override)
        self.proxy_summary = getattr(client, "imoveis_proxy_summary", {}) or {}

        bypass = get_config().scraping.cloudflare_bypass
        if bypass.enabled:
            if self.platform_name in bypass.platforms:
                headers = httpx.Headers(client.headers)
                client.close()
                self.proxy_summary = {**self.proxy_summary, "cloudflare_bypass": True}
                logger.info(
                    "scraper_cloudflare_bypass",
                    platform=self.platform_name,
                    endpoint=bypass.endpoint,
                )
                return FlareSolverrSession(bypass, headers=headers)
            if bypass.auto_fallback:
                self.proxy_summary = {
                    **self.proxy_summary,
                    "cloudflare_autofallback": True,
                }
                logger.info(
                    "scraper_cloudflare_autofallback",
                    platform=self.platform_name,
                    endpoint=bypass.endpoint,
                )
                return CloudflareFallbackSession(client, bypass)
        return client

    @abstractmethod
    def fetch_pages(self, checkpoint: dict) -> Generator:
        """Fetch pages of raw data from the platform."""

    @staticmethod
    def _record_circuit_outcome(cb, status_code: int) -> None:
        """Feed an HTTP response status into a scraper's circuit breaker.

        Shared by all platform ``_throttled_request`` implementations
        (BIN-156). 2xx marks success. 403 (Cloudflare block) buckets into
        its own failure-reason counter (``cloudflare_403``) so a sustained
        403 streak can open the SAME breaker `is_open()` gates without
        diluting — or being diluted by — a 5xx/429 streak. 403 is NOT an
        `errors` metric — that classification is unchanged and lives in
        ``availability.py``.
        """
        if 200 <= status_code < 300:
            cb.record_success()
        elif status_code == 403:
            cb.record_failure(reason="cloudflare_403")
        elif status_code >= 500 or status_code == 429:
            cb.record_failure()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # close() must be synchronous for use in Celery sync workers
        self.close()

    def close(self) -> None:
        """Close any open resources."""
        if hasattr(self, "session") and self.session:
            self.session.close()

    def start(self) -> None:
        """Initialize the scraper."""

    @abstractmethod
    async def normalize(self, raw_data: dict) -> dict:
        """Normalize raw data into standard format."""
