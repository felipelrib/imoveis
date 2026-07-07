# Implementation Plan: property-listings-table

## Goal
Create the missing `property_listings` table and populate it during deduplication/ingest.

## Problem
- `src/api/properties.py` queries `property_listings` but the table doesn't exist
- The scraper produces listings data that is discarded during deduplication
- Properties grid/modal break on a clean DB

## Steps

### Step 1: Add ORM model
- File: `src/adapters/db/models.py`
- Add `PropertyListing` class with columns: id, property_id (FK), platform, platform_listing_id, listing_type, price, currency, url, is_furnished, accepts_pets, condo_fee, iptu, raw_json, first_seen, last_seen, active
- Unique constraint on (platform, platform_listing_id, listing_type)

### Step 2: Create Alembic migration
- Run `alembic revision -m "add_property_listings_table"`
- Create `property_listings` table in upgrade()
- Drop it in downgrade()

### Step 3: Add listing upsert to dedupe
- File: `src/core/dedupe.py`
- Add `_upsert_listings()` helper
- Call it in all 3 paths: exact match update, fuzzy match update, new create

### Step 4: Update scraper normalize output
- File: `src/adapters/scrapers/quintoandar.py`
- Rename `platform_id` → `platform_listing_id` in listing dicts
- Add `currency: "BRL"` to each listing

### Step 5: Fix API subquery columns
- File: `src/api/properties.py`
- Change `pl.platform_id` → `pl.platform_listing_id` in both subqueries
- Add `pl.currency` to the output

### Step 6: Tests
- Unit test for `_upsert_listings()`
- Integration test for listing persistence through dedupe

### Step 7: Validate
- Run `bash scripts/agent/validate.sh backend`