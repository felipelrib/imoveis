# Implementation Plan: price-history-tracking

**Feature**: `price-history-tracking` (Linear BIN-7)  
**Branch**: `feat/price-history-tracking`  
**Goal**: Populate the existing `price_history` table on every price change and expose it via API.

## Affected Areas

- `src/core/dedupe.py` — price change detection + history writes
- `src/api/properties.py` — new `GET /properties/{id}/price-history` endpoint
- `src/adapters/db/models.py` — reference existing `PriceHistory` model (no changes)
- `src/tests/unit/test_dedupe.py` — extend with price-history tests

## Step-by-step

### Step 1: Write implementation plan (this file)

### Step 2: Modify `src/core/dedupe.py`
- Add a helper `_record_price_change(session, property_id, new_price)` that:
  - Finds the current open interval (`end_ts IS NULL`) for the property
  - If it exists and the price differs: closes it (`end_ts = now()`) and inserts a new row
  - If no open interval exists (shouldn't happen after creation, but handle gracefully): insert one
- Call `_record_price_change` in `match_or_create_property`:
  - After the update at line 82 (`existing.price = candidate.price`): call it if old price ≠ new
  - After the fuzzy-match update at line 121 (`prop.price = candidate.price`): same logic
  - After creating a new property (line 155): insert an initial open interval

### Step 3: Add `GET /properties/{id}/price-history` endpoint
- Add to `src/api/properties.py`
- Query `price_history` ordered by `start_ts DESC`
- Return `[{price, start_ts, end_ts}, ...]`

### Step 4: Add unit tests
- Test `_record_price_change` logic (mock session)
- Test that same price = no new history row
- Test that different price = close old + insert new
- Test that first-seen gets seeded interval

### Step 5: Validate
- `bash scripts/agent/validate.sh backend`
- If Docker unavailable, run pytest directly in the worktree

### Step 6: Commit + finish feature

## Data / Schema Changes

None — `price_history` table already exists from the initial migration.

## Risks

- Low conflict surface — changes are additive inside existing dedupe paths
- Docker may need manual setup for full validation