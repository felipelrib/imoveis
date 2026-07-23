#!/usr/bin/env python3
"""Record live scraper HTML pages into test cassette fixtures.

Usage (from repo root):
  python scripts/dev/record_scraper_cassettes.py

Writes under src/tests/fixtures/scrapers/. Review diffs before committing.
Not required for PR CI — cassettes are the offline gate; this refreshes them.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = REPO_ROOT / "src" / "tests" / "fixtures" / "scrapers"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

TARGETS = [
    (
        "quintoandar_search.html",
        "https://www.quintoandar.com.br/alugar/imovel/"
        "belo-horizonte-mg-brasil/de-500-a-1500-reais",
    ),
    (
        "olx_search.html",
        "https://www.olx.com.br/imoveis/aluguel/apartamentos/"
        "estado-mg/belo-horizonte?o=1",
    ),
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }
    ok = True
    with httpx.Client(headers=headers, follow_redirects=True, timeout=45.0) as client:
        for filename, url in TARGETS:
            print(f"Fetching {url}")
            try:
                resp = client.get(url)
                resp.raise_for_status()
            except Exception as exc:  # noqa: BLE001 — CLI tool
                print(f"  FAILED: {exc}", file=sys.stderr)
                ok = False
                continue
            if "__NEXT_DATA__" not in resp.text:
                print(f"  WARNING: no __NEXT_DATA__ in response for {filename}")
            path = OUT / filename
            path.write_text(resp.text, encoding="utf-8")
            print(f"  Wrote {path} ({len(resp.text)} bytes)")

    print(
        "\nNote: quintoandar_detail.html is not auto-recorded "
        "(needs a stable listing URL). Update it manually if the detail shape changes."
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
