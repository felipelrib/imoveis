# OLX listing type + location accuracy — seller vs property

> Feature branch: `feat/olx-listing-type-location` · Linear: `BIN-72` · Status: implemented

## Problem

OLX sale listings were often stored as rent because modern detail/Flight URLs omit `/venda|/aluguel`, and `_detect_listing_type` defaulted to rent while ignoring the search-window category. Separately, OLX `locationDetails` often reflects the seller or metro region (e.g. São Tomáz, BH) rather than the property — titles like “Cobertura no Itapoã” or “Vendo casa em Cabo Frio” hold the truth, so wrong neighbourhoods and out-of-geo noise entered the catalog.

## Approach

- Stamp `_olx_listing_type` from the search path (`aluguel` / `venda`) and prefer path segments over substring `venda` (avoids `venda-nova` false positives).
- OLX-only location reconcile: fast heuristic, then local Ollama with allowlist cities + neighbourhood catalog; update address/neighbourhood when city stays in BH/SP/Campinas; reject/purge when corrected city is out of geo; clear seller coords and name-assign neighbourhood when text disagrees with the pin.
- One-shot backfill: `scripts/dev/fix_olx_listings.py` (dry-run / `--apply` / `--skip-ai`).

## Changes

Files touched:

```
 src/adapters/scrapers/olx.py                      | Stamp listing type; path-segment detection; default sale
 src/core/olx_location.py                          | NEW — heuristic + AI reconcile helpers
 src/core/neighbourhood_assignment.py              | Name-based assign + load_neighborhood_names
 src/adapters/ai/prompts.py                        | build_olx_location_prompt
 src/adapters/ai/__init__.py                       | Export new prompt
 src/adapters/queue/tasks.py                       | Reconcile OLX before geo allowlist; name assign
 scripts/dev/fix_olx_listings.py                  | NEW — backfill type + location + purge + merge
 src/tests/unit/test_olx.py                        | Listing-type regressions
 src/tests/unit/test_olx_location.py               | NEW — location reconcile specs
 src/tests/unit/test_neighbourhood_assignment.py   | By-name assign unit test
 src/tests/unit/test_scrape_listings_pipeline.py   | Mock catalog/AI; expect by-name assign
 src/tests/unit/test_scrape_run_telemetry.py       | Mock catalog/AI for OLX scrape
 docs/features/BIN-72-olx-listing-type-and-location.md | NEW — this doc
```

## New Dependencies

None.

## How to Test

1. Unit regressions:
   ```bash
   bash scripts/agent/validate.sh fast
   ```
2. Scraper + AI gates (after code changes on those surfaces):
   ```bash
   bash scripts/agent/validate-scrapers.sh --require-live
   bash scripts/agent/validate-ai.sh
   bash scripts/agent/validate.sh all
   ```
3. Backfill (dry-run first):
   ```bash
   PYTHONPATH=src python scripts/dev/fix_olx_listings.py --skip-ai
   PYTHONPATH=src python scripts/dev/fix_olx_listings.py --apply
   ```

## Notes / Follow-ups

- Geocoding corrected neighbourhoods to new lat/lon: shipped as BIN-112 (`docs/features/BIN-112-geocode-corrected-neighbourhoods.md` — neighbourhood `ST_PointOnSurface`, not street geocoding).
- Live Ollama is required for best location corrections during scrape and `--apply` without `--skip-ai`.
- Related: BIN-68 / BIN-70 geo allowlist; BIN-9 original OLX scraper.
