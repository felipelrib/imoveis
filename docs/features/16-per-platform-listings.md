# per-platform-listings — Cross-platform price comparison on property cards and in the detail modal

> Feature branch: `feat/per-platform-listings` · Linear: `BIN-XX` · Status: implemented

## Problem

Properties can be listed on multiple platforms simultaneously (e.g. OLX and QuintoAndar)
with different prices for rent vs. sale. The old property card showed a single aggregated
price, making it impossible for users to:
- Identify which platform offers the best deal.
- Compare rent vs. sale prices side by side.
- Navigate directly to the original listing URL.

## Approach

- **Frontend-only change**: The API already returns a `listings` array with per-platform
  data (via `property_listings` table JOIN). No backend changes were required.
- **Property card redesign**: Cards group listings by `listing_type` (rent/sale). For each
  type the **lowest price** across all platforms is displayed with the platform name badge.
  When both rent and sale listings exist both rows are shown. A `"2 plataformas"` badge
  appears when more than one platform lists the property.
- **Property modal listings table**: A new section shows all listings grouped by type with
  columns: Platform, Price, Condo Fee, IPTU, Furnished, Pets, and a direct link to the
  source URL. The row with the best (lowest) price is highlighted with a green background.
- **Backward compatibility**: Falls back to `p.price` on property cards when `listings` is
  absent or empty.

## Changes

Files touched:

```
 frontend/src/pages/Properties.jsx            | Card redesign with per-listing-type lowest-price display and multi-platform badge
 frontend/src/components/PropertyModal.jsx    | NEW "Listings by Platform" section with comparison table and best-price row highlight
 frontend/src/index.css                       | NEW .listings-table, .best-price, .listing-link styles
```

## New Dependencies

None.

## How to Test

1. Start the stack: `bash scripts/start.sh`
2. Ensure at least one property exists that is listed on two or more platforms.
3. Open **Properties** page:
   - Cards for multi-platform properties should show a `"2 plataformas"` badge.
   - Separate rent/sale price rows should appear on applicable cards.
4. Click a property → modal "Listings by Platform" section should show the table.
5. Verify that the row with the lowest price per group has the green background class.
6. Click a platform link → should open the original listing URL in a new tab.

```bash
bash scripts/test.sh all  # validates build + lint + unit + integration
```

## Notes / Follow-ups

- **BUG (XSS — listing URL)**: Each listing renders an `<a href={l.url}>` where `l.url`
  comes from the database. If a scraper persists a `javascript:` URL, clicking the link
  executes arbitrary JS. Validate/sanitise the URL before rendering: check that it starts
  with `https://` and matches the known platform hostname.
- **Best-price highlight uses array index comparison**: The "best price" detection iterates
  over `listings` to find the minimum price and marks the matching row. If two listings have
  the same minimum price, only the first is highlighted — this is visually inconsistent.
- **No server-side price sorting**: The listings array order depends on DB insertion order.
  Sort by `price ASC` on the API side or in the frontend before rendering the table.
- **Condo fee and IPTU are shown as raw floats**: The values are `null` for platforms that
  don't report them. The table should display `"—"` instead of empty cells for better
  readability.
- **Listing URL opens external site**: No `rel="noopener noreferrer"` on the `<a>` tag —
  add it to prevent reverse tabnapping.
