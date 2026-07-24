# Adaptive scraper funneling — Price + neighborhood coverage for OLX and QuintoAndar

> Feature branch: `feat/bin-62-scraper-adaptive-funneling` · Linear: `BIN-62` · Status: implemented

## Problem

City-wide OLX scrapes stopped at ~1500 listings because each category path only paginated up to `max_pages` (~5 × ~50 ads). QuintoAndar already bisected price windows at the 12-result SSR cap, but atomic price bands that were still full silently dropped listings past the first page. Neither scraper fanned out by neighborhood, so dense Belo Horizonte inventory could not be fully ingested.

## Approach

- **Price-first BFS**: both platforms start with city-level price windows from YAML (`price_rent` / `price_sale`).
- **Split on saturation**: OLX treats a window as saturated when it hits `max_pages` with a full last page (`page_size_hint`); QuintoAndar when `len(houses) >= 12`. Splittable bands are bisected via shared `bisect_price`.
- **Neighborhood fan-out only when needed**: if the price band is atomic and still saturated, enqueue the same band per curated YAML neighborhood (OLX `zone`+`slug` path segments; QuintoAndar `{slug}-{city_slug}`).
- **In-run listing-id dedupe** so overlapping windows do not double-yield.
- Empty `neighborhoods` keeps price-only behavior (backward compatible).

## Changes

Files touched:

```
 src/adapters/scrapers/funnel.py          | NEW — bisect_price, unique_by, listing_id_from_raw
 src/adapters/scrapers/olx.py             | Adaptive ps/pe windows + geo fan-out; estado-mg paths
 src/adapters/scrapers/quintoandar.py     | Neighborhood fan-out on atomic ≥12; config price bounds
 configs/app_config.yaml                  | price_* bands + curated BH neighborhoods for both platforms
 src/tests/unit/test_funnel.py            | NEW — bisect / unique / id helpers
 src/tests/unit/test_olx.py               | Saturation split, fan-out, dedupe, URL builders
 src/tests/unit/test_quintoandar.py       | Config prices, neighborhood URLs, atomic fan-out
 docs/features/01-scraper-framework.md    | Point at adaptive funnel behavior
 docs/features/47-scraper-adaptive-funneling.md | NEW — this note
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
bash scripts/agent/validate-scrapers.sh --require-live
```

Manual:

1. Trigger `POST /scrape` for `olx` and watch worker logs for `olx_splitting_price_window` / `olx_fanout_neighborhoods` instead of a hard stop near 1500.
2. Same for `quintoandar` — look for `quintoandar_fanout_neighborhoods` when dense atomic bands appear.
3. Confirm Redis `pipeline:scraper:{platform}:status` `processed` climbs past the old city-only ceiling when inventory exists.

## Notes / Follow-ups

- Curated neighborhood lists are intentionally ~35 major BH bairros, not every official neighborhood; expand YAML as coverage gaps appear.
- Full funnel runs are longer (more HTTP + jitter); Celery soft/hard time limits may need raising if large runs abort mid-queue.
- Invalid or drifted platform slugs return empty windows and are skipped — monitor `olx_http_error` / `quintoandar_no_next_data`.
- Related prior work: `docs/features/01-scraper-framework.md`, `39-fix-quintoandar-olx-scrapers.md`, BIN-62.
