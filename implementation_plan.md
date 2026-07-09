# Implementation Plan — Per-Platform Listings with Price Comparison (BIN-30)

## Goal

Enhance the Properties UI to show per-platform prices with attribution on property cards, and add a grouped listings table in the PropertyModal for easy cross-platform price comparison.

## Affected Areas

- `frontend/src/pages/Properties.jsx` — Card redesign with per-listing-type prices
- `frontend/src/components/PropertyModal.jsx` — Listings table with links and best-price highlight
- `frontend/src/index.css` — New styles for listings table and price comparison layout
- `frontend/src/api.js` — No changes expected (API already returns `listings` array)

**No backend changes needed** — `GET /properties` and `GET /properties/{id}` already return the `listings` array with per-platform prices, listing types, URLs, fees, etc.

## Step-by-Step Implementation

### Step 1: Update PropertyCard to show per-listing-type prices with platform attribution

In `Properties.jsx`, modify the PropertyCard to:
- Extract listings from `p.listings` array
- Group listings by `listing_type` (rent vs sale)
- For each listing type, show the **best price** (lowest) with platform name
- If both rent and sale exist, show both with independent prices
- Add a "2 plataformas" badge when property appears on multiple platforms
- Keep backward compatibility: if no listings array, fall back to `p.price`

### Step 2: Update PropertyModal to show a grouped listings table

In `PropertyModal.jsx`, add a listings section:
- Group listings by listing_type ("Aluguel" / "Venda")
- Show a table with: Platform | Price | Condo Fee | IPTU | Furnished | Pets | Link
- Highlight the best price row (lowest per listing type) with a green indicator
- Each listing links to the original platform URL (`listing.url`)

### Step 3: Sort by price using appropriate listing type

In `Properties.jsx`, update the price sorting logic:
- When sorting by price, use the lowest price from the user's selected listing_type filter
- If no filter, use the lowest price across all listing types

### Step 4: Add CSS styles for the new listings components

In `index.css`:
- Listings table styles (grouped by listing type)
- Best-price highlight (subtle green background)
- Platform badge styles
- Listing type section headers

### Step 5: Test and validate

- Verify cards show correct per-platform prices
- Verify modal shows full listings table
- Verify best price is highlighted
- Run `validate.sh frontend`

## Data / Schema Changes

None — all data is already available in the API response.

## Validation Plan

- Manual testing: verify card layout with properties that have multiple listings
- Visual check: best price highlighted, platform badges shown
- `validate.sh frontend` must pass
- Edge cases: properties with no listings (fallback to `p.price`), properties with single listing

## Risks and Conflict Surface

- **Low risk**: Frontend-only change, no backend modifications
- **Data dependency**: Need properties with multiple platform listings to test properly
- **Fallback**: Must handle properties with no `listings` array gracefully (backward compat)
