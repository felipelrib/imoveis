from abc import ABC, abstractmethod
from typing import Generator


class CircuitBreakerException(Exception):
    """Exception raised when a circuit breaker is open."""


class BaseScraper(ABC):
    """Base interface for scraper adapters.

    Responsibilities
    ----------------
    * Be idempotent and checkpoint-aware.
    * Enforce politeness (rate limits, jitter) transparently.
    * Expose ``start()``, ``fetch_pages(checkpoint)`` and ``normalize(raw)``.
    """

    def __init__(self, platform_name: str, config: dict):
        self.platform_name = platform_name
        self.config = config

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
