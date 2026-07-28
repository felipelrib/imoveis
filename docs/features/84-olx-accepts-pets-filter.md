# olx-accepts-pets-filter — OLX pets column + filter parity

> Feature branch: `feat/bin-110-olx-accepts-pets` · Linear: `BIN-110` · Status: implemented

## Problem

The Properties pets filter only matched QuintoAndar’s `PODE_TER_ANIMAIS_DE_ESTIMACAO` amenity on `props_json`. OLX already mapped “Aceita animais” onto `property_listings.accepts_pets`, but those rows never appeared when the pets toggle was on.

## Approach

- Keep OLX normalize mapping of pet attrs onto listing `accepts_pets`; add the `aceita pets` label synonym and cassette coverage.
- Change `_build_list_filters` pets clause to `EXISTS` on active `property_listings.accepts_pets IS TRUE`, OR the legacy QuintoAndar amenity key for rows never backfilled.
- Unit-test the SQL shape (same pattern as BIN-77 max_price listing filter).

## Changes

Files touched:

```
 src/api/properties.py                              | pets filter uses listing.accepts_pets OR QA amenity
 src/adapters/scrapers/olx.py                       | aceita pets synonym
 src/tests/unit/test_property_pets_filter.py        | NEW — filter SQL regression
 src/tests/unit/test_olx.py                         | extra pets normalize cases
 src/tests/unit/test_scraper_cassettes.py           | assert cassette accepts_pets
 src/tests/fixtures/scrapers/olx_search.html        | Aceita animais / Mobiliado attrs
 src/tests/fixtures/scrapers/olx_search_flight.html | aceita_animais attr
 docs/features/80-locale-aware-filters.md           | follow-up → BIN-110
 docs/features/84-olx-accepts-pets-filter.md        | NEW — this doc
```

## New Dependencies

None.

## How to Test

1. With OLX listings that have `accepts_pets = true` in `property_listings`, enable the pets filter on Properties — OLX rows appear alongside QuintoAndar amenity matches.
2. Automated:
   ```bash
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- Live OLX probe hit Cloudflare 403 from this environment; cassette + unit coverage locks the attr shapes. Refresh via `python scripts/dev/record_scraper_cassettes.py` when the pool is available.
- Legacy QuintoAndar rows with amenity but null `accepts_pets` still match via the amenity OR branch; a one-shot backfill is optional.
- Related: BIN-65 (furnished/pets UI binding), BIN-100 (locale-aware filters deferred this work).
