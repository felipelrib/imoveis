import json
import os
import sys

# Ensure src is in PYTHONPATH
sys.path.insert(0, os.path.abspath('src'))

from adapters.scrapers.quintoandar import QuintoAndarScraper  # noqa: E402


def test_scraper():
    print("Initializing QuintoAndar scraper...")
    config = {
        "base_url": "https://www.quintoandar.com.br/alugar/imovel/belo-horizonte-mg-brasil",
        "rate_limit": 60,
        "jitter_min": 0,
        "jitter_max": 0,
    }

    scraper = QuintoAndarScraper(config)

    print("Fetching page 1...")
    iterator = scraper.fetch_pages({"page": 1})

    properties_found = 0
    with scraper:
        for i, raw_listing in enumerate(iterator):
            if i >= 3:  # Just grab the first 3 to prove it works
                break

            print(f"\n--- Raw Property {i+1} ---")
            print(f"ID: {raw_listing.get('id')}")

            normalized = scraper.normalize(raw_listing)
            print(f"\n--- Normalized Property {i+1} ---")
            print(json.dumps(normalized, indent=2, ensure_ascii=False))
            properties_found += 1

    print(f"\nSuccessfully scraped and normalized {properties_found} properties.")


if __name__ == "__main__":
    test_scraper()
