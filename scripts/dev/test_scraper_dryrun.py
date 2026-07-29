#!/usr/bin/env python3
"""Live dry-run against QuintoAndar + ZapImóveis (merge-blocking via validate-scrapers.sh)."""

from __future__ import annotations

import json
import os
import sys

# Ensure repo root (for `src.*` imports) and src/ (for `adapters.*`) are on path
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "src"))

from adapters.scrapers.quintoandar import QuintoAndarScraper  # noqa: E402
from adapters.scrapers.zapimoveis import ZapImoveisScraper  # noqa: E402


def _dry_run_qa() -> int:
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

    print("Fetching QuintoAndar listings (price-window dry-run, first 3)...")
    properties_found = 0
    try:
        for i, raw_listing in enumerate(scraper.fetch_pages({"scrape_type": "rent"})):
            if i >= 3:
                break

            print(f"\n--- QA Raw Property {i + 1} ---")
            print(f"ID: {raw_listing.get('id')}")

            normalized = scraper.normalize(raw_listing)
            print(f"\n--- QA Normalized Property {i + 1} ---")
            print(json.dumps(normalized, indent=2, ensure_ascii=False))
            properties_found += 1
    finally:
        scraper.close()

    if properties_found == 0:
        raise SystemExit(
            "QuintoAndar dry-run found 0 properties — site may be down or HTML "
            "structure changed. If HTTP worked, refresh cassettes: "
            "python3 scripts/dev/record_scraper_cassettes.py"
        )

    print(f"\nSuccessfully scraped and normalized {properties_found} QuintoAndar properties.")
    return properties_found


def _dry_run_zap() -> int:
    """Single search-page probe (avoids full price-funnel under Cloudflare flakiness).

    Returns the number of normalized listings. Cloudflare/proxy ``403`` is
    environmental (same policy as OLX) — returns ``-1`` so the caller can
    warn without failing the merge gate when QuintoAndar already passed.
    Raises ``SystemExit`` when HTTP succeeds but parsing yields nothing.
    """
    print("\nInitializing ZapImóveis scraper...")
    config = {
        "base_url": "https://www.zapimoveis.com.br",
        "rate_limit": 60,
        "jitter_min": 0,
        "jitter_max": 0,
        "extra": {
            "max_pages": 1,
            "cities": [{"city_slug": "mg+belo-horizonte", "neighborhoods": []}],
        },
    }

    scraper = ZapImoveisScraper("zapimoveis", config)
    scraper.start()

    urls = (
        "https://www.zapimoveis.com.br/aluguel/apartamentos/mg+belo-horizonte/",
        "https://www.zapimoveis.com.br/aluguel/casas/mg+belo-horizonte/",
    )
    properties_found = 0
    saw_success = False
    last_status = None
    try:
        for url in urls:
            print(f"Fetching ZapImóveis search page: {url}")
            try:
                response = scraper._throttled_request(url)
            except Exception as exc:  # noqa: BLE001
                print(f"  request error: {exc}")
                continue
            last_status = response.status_code
            if response.status_code in (403, 429):
                print(f"  HTTP {response.status_code} (Cloudflare/rate-limit) — trying next URL")
                continue
            if response.status_code != 200:
                print(f"  HTTP {response.status_code} — trying next URL")
                continue
            saw_success = True
            listings = scraper.extract_listings(response.text or "")
            for i, raw_listing in enumerate(listings[:3]):
                print(f"\n--- Zap Raw Property {i + 1} ---")
                print(f"ID: {raw_listing.get('id')}")
                normalized = scraper.normalize(raw_listing)
                print(f"\n--- Zap Normalized Property {i + 1} ---")
                print(json.dumps(normalized, indent=2, ensure_ascii=False))
                properties_found += 1
            if properties_found:
                break
    finally:
        scraper.close()

    if properties_found > 0:
        print(
            f"\nSuccessfully scraped and normalized {properties_found} ZapImóveis properties."
        )
        return properties_found

    if not saw_success and last_status in (403, 429, None):
        print(
            "\nZapImóveis dry-run skipped: Cloudflare/proxy blocked all probes "
            f"(last_status={last_status}). Cassette tests remain the offline gate; "
            "enable proxy pool for live Zap coverage."
        )
        return -1

    raise SystemExit(
        "ZapImóveis dry-run found 0 properties after HTTP success — HTML structure "
        "likely changed. Refresh cassettes: "
        "python3 scripts/dev/record_scraper_cassettes.py"
    )


def test_scraper() -> None:
    qa_n = _dry_run_qa()
    zap_n = _dry_run_zap()
    if zap_n < 0:
        print(f"\nDry-run OK (Zap live skipped): quintoandar={qa_n}, zapimoveis=blocked")
    else:
        print(f"\nDry-run OK: quintoandar={qa_n}, zapimoveis={zap_n}")


if __name__ == "__main__":
    test_scraper()
