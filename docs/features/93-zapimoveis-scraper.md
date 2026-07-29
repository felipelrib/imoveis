# ZapImóveis first-class scraper — FR-23 additional platform

> Feature branch: `feat/bin-127-zapimoveis-scraper` · Linear: `BIN-127` · Status: implemented

## Problem

PRD FR-23 deferred an additional first-class platform (ZapImóveis) past v0.5. The UI already trusted `zapimoveis.com.br` listing URLs, but no scraper registered with `BaseScraper` / Celery beat / availability recheck — so Zap inventory never entered the dedupe corpus alongside QuintoAndar and OLX.

## Approach

- Register platform id `zapimoveis` (not the unrelated test stub `"zap"`).
- Parse search HTML via Next.js Flight (`__next_f.push` → `"listings":[...]`) with schema.org `ItemList` Product JSON-LD as fallback — same family as OLX Flight, no Selenium/Apify.
- City shells for BH / SP / Campinas with empty neighborhoods (city-wide price bisect + `max_pages`); refuse to bisect when price query params are clearly ignored (Cloudflare / A-B drift).
- Soft-deactivate via Zap-specific availability classifier (`InStock` / `OutOfStock` / Flight listing / 404|410); 403/429/5xx stay UNKNOWN.
- Dedup uses existing geo + title matching — no engine changes.

## Changes

Files touched:

```
 src/adapters/scrapers/zapimoveis.py              | NEW — BaseScraper + Flight/JSON-LD parse + normalize
 src/adapters/scrapers/availability.py            | Zap detail availability classifier + dispatch
 src/adapters/queue/tasks.py                      | Side-effect import for registry
 src/api/main.py                                  | Side-effect import for /platforms + scrape trigger
 configs/app_config.yaml                          | scraping.platforms.zapimoveis block
 src/tests/fixtures/scrapers/zapimoveis_*.html    | NEW — search / detail / unavailable cassettes
 src/tests/unit/test_zapimoveis.py                | NEW — normalize / URL / price-filter / registry
 src/tests/unit/test_scraper_cassettes.py         | Zap cassette asserts
 src/tests/unit/test_availability.py              | Zap availability unit tests
 scripts/agent/validate-scrapers.sh               | Include test_zapimoveis.py
 scripts/dev/record_scraper_cassettes.py          | Zap search TARGET + Flight warning
 scripts/dev/test_scraper_dryrun.py               | Live Zap single-page probe after QA
 docs/features/93-zapimoveis-scraper.md           | NEW — this doc
```

## New Dependencies

None.

## How to Test

1. Offline cassette gate:
   ```bash
   bash scripts/agent/validate-scrapers.sh --skip-live
   ```
2. Full scraper gate (QA + Zap live dry-run; Zap needs non-Cloudflare HTTP):
   ```bash
   bash scripts/agent/validate-scrapers.sh --require-live
   ```
3. Confirm platform is registered:
   ```bash
   PYTHONPATH=src python -c "import adapters.scrapers.zapimoveis; from adapters.scrapers.registry import ScraperRegistry; print(ScraperRegistry.available())"
   ```
4. Rebuild `worker_scraper` after config changes before trusting scheduled scrapes.

## Notes / Follow-ups

- BH neighborhood fan-out left empty on purpose; deepen like BIN-113 when coverage needs it.
- Zap Cloudflare 403s are environmental — enable `proxy:` pool rather than treating as parse regression. Live dry-run skips Zap on 403/429 after QA passes; cassette tests remain the offline merge gate for parse regressions.
- IPTU values from Zap `prices.rental.iptu` are stored as the site emits them (often annual); no monthly conversion invented here.
- Existing unit fixtures that use platform string `"zap"` are unrelated stubs and were left unchanged; availability still reports `unsupported_platform:zap` for that id.
