# Implementation Plan: OLX Scraper (BIN-9)

## Overview

Add a second platform scraper for OLX Brazil (`olx.com.br`), subclassing `BaseScraper` and
self-registering via the existing `@ScraperRegistry.register("olx")` decorator.

## Approach

OLX Brazil serves real-estate listings via an embedded JSON state object in the HTML page
(Next.js `__NEXT_DATA__` script tag) — the same pattern QuintoAndar uses. The scraper will:

1. Build search URLs for Belo Horizonte (rent + sale) with price windows
2. Fetch each page, parse the `__NEXT_DATA__` JSON
3. Extract listing objects from the state tree
4. `normalize()` each raw listing into a `PropertyCandidate`-compatible dict

## Files

| File | Action |
|------|--------|
| `src/adapters/scrapers/olx.py` | **Create** — `OLXScraper` class |
| `configs/app_config.yaml` | **Edit** — enable olx (keep `enabled: true` but test carefully) |
| `src/tests/unit/test_olx.py` | **Create** — unit tests for normalize + fetch |
| `src/tests/unit/test_registry.py` | **Edit** — verify olx is registered |

## Key Design Decisions

- **Rate limiting**: Use `config["rate_limit"]` and `config["jitter_min"]`/`jitter_max` (not hardcoded)
- **Missing coordinates**: OLX listings may lack lat/lon — set `location: None` and let dedupe skip spatial matching
- **Price parsing**: OLX shows "R$ X.XXX" — strip non-numeric chars and convert to float
- **Listing type detection**: OLX separates "Aluguel" (rent) vs "Venda" (sale) via URL path

## Acceptance Criteria

- [ ] `POST /scrape {platform:"olx"}` ingests real listings
- [ ] Cross-platform duplicate detection works with QuintoAndar
- [ ] Scraper self-registers (appears in `GET /platforms`)
- [ ] Rate limit and jitter respected from config
- [ ] Unit test with fixtures
- [ ] `validate.sh backend` passes