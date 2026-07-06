from abc import ABC, abstractmethod
import logging
from typing import Optional

logger = logging.getLogger(__name__)

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
        self._http_client = None

    @abstractmethod
    async def start(self) -> None:
        """Initialize the scraper."""
        pass

    @abstractmethod
    async def fetch_pages(self, checkpoint: dict) -> list:
        """Fetch pages of listings."""
        pass

    @abstractmethod
    async def normalize(self, raw_data: dict) -> dict:
        """Normalize raw data into standard format."""
        pass

    async def close(self) -> None:
        """Close any open connections."""
        try:
            if self._http_client is not None:
                # Fechar o cliente HTTP se existir
                if hasattr(self._http_client, 'close'):
                    await self._http_client.close()
                elif hasattr(self._http_client, 'session'):
                    await self._http_client.session.close()
                logger.info(f"Closed connections for platform {self.platform_name}")
        except Exception as e:
            logger.error(f"Error closing connections for platform {self.platform_name}: {e}")

    def _ensure_http_client(self):
        """Ensure HTTP client is initialized."""
        if self._http_client is None:
            # Inicialização do cliente HTTP
            pass  # Implementação específica por subclasse
