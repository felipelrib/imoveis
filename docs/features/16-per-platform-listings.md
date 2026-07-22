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
- **Presentation**: `PropertyModal` groups listings by `listing_type` (Rent vs Sale),
  sorts by price within each group, and highlights the best price(s) across platforms
  using a `.best-price` styling. If multiple platforms share the best price, all tied rows
  are highlighted.
- **Link Sanitization**: Listing URLs are validated using a `sanitizeListingUrl()` helper
  to ensure they use `https:` and belong to trusted domains (`olx.com.br`, `quintoandar.com.br`, `zapimoveis.com.br`).
  Valid links include `rel="noopener noreferrer"` to prevent tabnapping, while invalid
  or missing URLs render a placeholder.
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

- **Scraper alignment**: Some platforms report "condo fee" (condomínio) and "property tax"
  (IPTU) as a single bundled value, while others report them separately. The UI currently
  displays whatever the scraper provided, which can make cross-platform comparison
  difficult if the values aren't normalized.
- **Historical listings**: If a platform delists a property, the row remains in the UI
  but the link will 404. A daily health-check scraper could verify and prune dead URLs.
