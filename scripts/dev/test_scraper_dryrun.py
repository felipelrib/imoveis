#!/usr/bin/env python3
"""Live dry-run against QuintoAndar (merge-blocking via validate-scrapers.sh)."""

from __future__ import annotations

import json
import os
import sys

# Ensure src is in PYTHONPATH
sys.path.insert(0, os.path.abspath("src"))

from adapters.scrapers.quintoandar import QuintoAndarScraper  # noqa: E402


def test_scraper() -> None:
    print("Initializing QuintoAndar scraper...")
    config = {
        "base_url": "https://www.quintoandar.com.br/alugar/imovel/belo-horizonte-mg-brasil",
        "rate_limit": 60,
        "jitter_min": 0,
        "jitter_max": 0,
        "extra": {"city_slug": "belo-horizonte-mg-brasil"},
    }

    scraper = QuintoAndarScraper("quintoandar", config)
    scraper.start()

    print("Fetching listings (price-window dry-run, first 3)...")
    properties_found = 0
    try:
        for i, raw_listing in enumerate(scraper.fetch_pages({"scrape_type": "rent"})):
            if i >= 3:
                break

            print(f"\n--- Raw Property {i + 1} ---")
            print(f"ID: {raw_listing.get('id')}")

            normalized = scraper.normalize(raw_listing)
            print(f"\n--- Normalized Property {i + 1} ---")
            print(json.dumps(normalized, indent=2, ensure_ascii=False))
            properties_found += 1
    finally:
        scraper.close()

    if properties_found == 0:
        raise SystemExit(
            "Dry-run found 0 properties — site may be down or HTML structure changed. "
            "If HTTP worked, refresh cassettes: python3 scripts/dev/record_scraper_cassettes.py"
        )

    print(f"\nSuccessfully scraped and normalized {properties_found} properties.")


if __name__ == "__main__":
    test_scraper()
