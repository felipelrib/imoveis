from abc import ABC, abstractmethod


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
    async def fetch_pages(self, checkpoint: dict) -> list:
        """Fetch pages of raw data from the platform."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        import asyncio

        # We need to call async close() but we are in a sync context manager
        # If tasks.py uses `with scraper:`, it's sync. If it should be async, `tasks.py` is wrong.
        # Let's provide a sync __exit__ that runs the async close in the event loop.
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.close())
            else:
                loop.run_until_complete(self.close())
        except Exception:
            pass

    async def close(self) -> None:
        """Close any open resources."""

    async def start(self):
        """Initialize the scraper."""

    @abstractmethod
    async def normalize(self, raw_data: dict) -> dict:
        """Normalize raw data into standard format."""
