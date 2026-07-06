from abc import ABC, abstractmethod
from typing import Any, Iterator, Dict, List

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
        pass

    async def close(self) -> None:
        """Close any open resources."""
        pass

    async def start(self):
        """Initialize the scraper."""
        pass

    @abstractmethod
    async def normalize(self, raw_data: dict) -> dict:
        """Normalize raw data into standard format."""
        pass
