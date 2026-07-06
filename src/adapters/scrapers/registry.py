"""Scraper registry — maps platform names to scraper classes.

Usage:
    from adapters.scrapers.registry import ScraperRegistry

    @ScraperRegistry.register('quintoandar')
    class QuintoAndarScraper(BaseScraper):
        ...

    scraper = ScraperRegistry.get('quintoandar', platform_config)
"""
from __future__ import annotations

from typing import Dict, List, Type

from .base import BaseScraper


class ScraperRegistry:
    """Central registry that maps platform name → scraper class.

    Scraper modules use the ``@ScraperRegistry.register('name')`` decorator
    at import time, and callers use ``ScraperRegistry.get(name, config)``
    to obtain a ready-to-use instance.
    """

    _registry: Dict[str, Type[BaseScraper]] = {}

    @classmethod
    def register(cls, platform_name: str):  # noqa: ANN206
        """Decorator to register a scraper class for *platform_name*."""

        def wrapper(scraper_cls: Type[BaseScraper]) -> Type[BaseScraper]:
            cls._registry[platform_name] = scraper_cls
            return scraper_cls

        return wrapper

    @classmethod
    def get(cls, platform_name: str, platform_config: dict) -> BaseScraper:
        """Instantiate and return the scraper for *platform_name*."""
        if platform_name not in cls._registry:
            raise ValueError(
                f"No scraper registered for platform: {platform_name}. "
                f"Available: {list(cls._registry.keys())}"
            )
        return cls._registry[platform_name](platform_config)

    @classmethod
    def available(cls) -> List[str]:
        """Return the list of registered platform names."""
        return list(cls._registry.keys())
