# Deduplication Engine — Multi-strategy property matching and merge with listing upsert

> Feature branch: `feat/dedup-engine` · Linear: `BIN-XX` · Status: implemented

## Problem

Properties appear on multiple platforms or are re-listed. Without deduplication, the database would fill with duplicate entries, skewing scores and confusing users. The engine must handle exact platform matches, cross-platform fuzzy matches (same property on OLX and QuintoAndar), and track per-listing prices independently.

## Approach

- **Three-tier matching strategy** in `match_or_create_property()`:
  1. **Exact match** — `(platform, platform_id)` lookup. If found, check if anything changed (`_is_unchanged`); if not, return `noop` to skip AI enrichment.
  2. **Spatial + text fuzzy match** — PostGIS `ST_DWithin` radius search (default 50m) + Jaro-Winkler title similarity (default threshold 0.85) + area tolerance (±5m²). Merges into existing property.
  3. **Create new** — No match found; inserts new property with PostGIS point geometry.

- **Listing upsert** (`_upsert_listings`): Each scrape produces discrete `PropertyListing` rows keyed on `(platform, platform_listing_id, listing_type)`. Price changes trigger `_record_price_change`.

- **Price history as open intervals**: Each `(property_id, listing_type, platform)` triplet maintains an open-ended time interval. When price changes, the old interval is closed (`end_ts = now`) and a new one is opened.

- **Watchlist integration**: `_check_watchlist_alerts` fires price-drop notifications when a price decrease exceeds the user's configured `min_drop_pct` threshold.

## Changes

Files touched:

```
 src/core/dedupe.py     | Main dedup logic: match_or_create_property, _upsert_listings, _record_price_change, _check_watchlist_alerts
 src/core/entities.py   | PropertyCandidate Pydantic model with validation
 src/adapters/db/models.py | Property, PropertyListing, PriceHistory, Watchlist ORM models
```

## New Dependencies

- `jellyfish` — Jaro-Winkler similarity algorithm
- `geoalchemy2` + `shapely` — PostGIS geometry handling

## How to Test

1. Run unit tests:
   ```bash
   pytest src/tests/unit/test_dedupe.py src/tests/unit/test_dedupe_noop.py src/tests/unit/test_listings.py -v
   ```
2. Integration tests:
   ```bash
   pytest src/tests/integration/test_e2e.py src/tests/integration/test_listings_e2e.py -v
   ```

## Notes / Follow-ups

### Bugs Found

- ~~**BUG (Moderate): `_is_unchanged` safely defaults to True on DB errors**~~ — **FIXED**: Changed to return `False` on DB errors to ensure re-enrichment.
- ~~**BUG (Minor): `text_similarity` catches ALL exceptions**~~ — **FIXED**: Imported jellyfish locally and only catch specific exceptions.
- ~~**BUG (Minor): `_record_price_change` NULL comparison bug**~~ — **FIXED**: Used `IS NOT DISTINCT FROM` in SQL query for correct NULL handling.
- ~~**BUG (Minor): Pydantic v1 API `@validator` used in `entities.py`**~~ — **FIXED**: Updated to Pydantic v2 API `@field_validator` and `@model_validator`.

### Tech Debt

- **`raw_json` is stored as `str(dict)` not proper JSON** (dedupe.py L430, L471): `_upsert_listings` does `str(listing.get("raw_json"))` which produces Python repr, not valid JSON. Should use `json.dumps()`.
- **No unique constraint on `(platform, platform_id)` in `Property` model** — The dedup relies on a query, but concurrent scrapes could create duplicates.
- **`config.yaml` defaults don't match code defaults** — Config has `text_similarity_threshold: 0.65` but `match_or_create_property` defaults to `text_threshold=0.85`. The config values are never passed to the function.
- **`token_sort` algorithm declared in config but not implemented** — Only `jaro_winkler` and `levenshtein` are handled in `text_similarity()`.
