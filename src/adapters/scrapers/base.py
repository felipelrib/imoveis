from abc import ABC, abstractmethod
from typing import Generator

import httpx

from adapters.scrapers.http_client import create_scraper_http_client


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

    def create_http_session(self) -> httpx.Client:
        """Build an HTTP client using global proxy config + optional override.

        Non-null ``extra.proxy`` is a fixed per-platform override; ``null`` /
        absent defers to ``AppConfig.proxy`` rotation.
        """
        override = (self.config.get("extra") or {}).get("proxy")
        return create_scraper_http_client(platform_override=override)

    @abstractmethod
    def fetch_pages(self, checkpoint: dict) -> Generator:
        """Fetch pages of raw data from the platform."""

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
