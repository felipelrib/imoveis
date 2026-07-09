from typing import Dict, Type

from adapters.scrapers.base import BaseScraper


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
        """Get a ready-to-use scraper instance for *platform_name*."""
        if platform_name not in cls._registry:
            raise ValueError(f"No scraper registered for platform '{platform_name}'")

        scraper_cls = cls._registry[platform_name]
        return scraper_cls(platform_name, platform_config)

    @classmethod
    def available(cls) -> list[str]:
        """Get list of all available platform names."""
        return list(cls._registry.keys())
