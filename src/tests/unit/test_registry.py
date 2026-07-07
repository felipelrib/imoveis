"""Unit tests for the ScraperRegistry."""

from __future__ import annotations

import pytest

from adapters.scrapers.base import BaseScraper
from adapters.scrapers.registry import ScraperRegistry


class _DummyScraper(BaseScraper):
    def start(self):
        pass

    def fetch_pages(self, checkpoint):
        return iter([])

    def normalize(self, raw):
        return {}


def test_register_and_get():
    # Register a fresh name so we don't pollute the real registry
    ScraperRegistry.register("_test_platform")(_DummyScraper)
    assert "_test_platform" in ScraperRegistry.available()
    scraper = ScraperRegistry.get("_test_platform", {})
    assert isinstance(scraper, _DummyScraper)


def test_get_unknown_raises():
    with pytest.raises(ValueError, match="No scraper registered"):
        ScraperRegistry.get("nonexistent_xyz", {})


def test_available_returns_list():
    result = ScraperRegistry.available()
    assert isinstance(result, list)
