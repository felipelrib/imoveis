# OLX dual rent+sale as two property_listings rows

> Feature branch: `feat/bin-108-dual-rent-sale-listings` · Linear: `BIN-108` · Status: implemented

## Problem

OLX dual “venda ou locação” ads that carry both rent and sale prices were normalized to a **single** `property_listings` row. Cross-window sightings (same `listId` in `/aluguel/` and `/venda/`) dropped the second price via `unique_by`, so filters, dual scores, and cards could not show both transactions.

## Approach

- Mirror QuintoAndar: emit two listing dicts when both prices are known; keep a single correctly-typed row when only one price exists (BIN-81 title/price inference unchanged).
- Merge same-`listId` sightings across rent/sale search windows into `_olx_prices`, then clear the single-type stamp.
- Parse multi-entry `pricingInfos` (monthly → rent; empty/sale-band → sale).
- Fix dedupe noop so adding a second listing type is not treated as unchanged.

## Changes

Files touched:

```
 src/adapters/scrapers/olx.py                              | Dual `_prices_for_listing`, window merge, normalize
 src/core/dedupe.py                                        | `_listings_prices_unchanged` key-set asymmetry
 src/tests/unit/test_olx.py                                | Dual normalize + merge unit coverage
 src/tests/unit/test_dedupe_noop.py                        | New listing type is not noop
 src/tests/fixtures/scrapers/olx_dual_pricing.html         | NEW — dual pricingInfos cassette
 src/tests/unit/test_scraper_cassettes.py                  | Cassette asserts two listings
 docs/features/88-olx-dual-rent-sale-listings.md           | NEW — this note
 docs/features/60-olx-venda-nova-listing-type.md           | Close dual-rows follow-up
```

## New Dependencies

None.

## How to Test

1. Unit:
   ```bash
   PYTHONPATH=src pytest src/tests/unit/test_olx.py::TestOLXNormalize::test_dual_olx_prices_emits_rent_and_sale \
     src/tests/unit/test_olx.py::TestOLXDualPriceMerge \
     src/tests/unit/test_scraper_cassettes.py::TestOLXCassettes::test_dual_pricing_cassette_emits_rent_and_sale \
     src/tests/unit/test_dedupe_noop.py::TestIsUnchanged::test_new_listing_type_not_noop
   ```
2. Scraper gate: `bash scripts/agent/validate-scrapers.sh --require-live`
3. After merge, rebuild `worker_scraper` so new scrapes pick up dual emission.

## Notes / Follow-ups

- Title-only dual ads with a single `priceValue` stay one row (correct type via BIN-81); we do not invent a second price.
- Historical backfill via `fix_olx_listings.py` is out of scope — `raw_json` rarely stores both prices. Re-scrape dual ads to populate the second row.
- Rebuild `worker_scraper` after merge.
