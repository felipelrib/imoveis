# english-listing-accuracy — English product language, listing table UX, geo allowlist

> Feature branch: `feat/bin-64-english-listing-accuracy` · Linear: `BIN-64` (children BIN-65..69; Future BIN-63) · Status: implemented

## Problem

The property modal mixed Portuguese and English (PT deal verdict vs EN analysis panels), showed empty Furnished/Pets cells (wrong API field names) beside money columns, hid QuintoAndar base rent (`partial_price`), and could persist out-of-geo cities (e.g. Porto Alegre) despite BH/MG scrape config.

## Approach

- Flip product language to English-only (UI chrome + AI templates / `ai.output_language`); defer multi-locale to BIN-63 AI translation.
- Bind `is_furnished` / `accepts_pets`; move amenities to chips under the fees table; expose first-class `base_price`.
- Post-scrape geo allowlist (`scraping.geo_allowlist`) rejects explicit non-BH/MG city/state before persist.
- Map QuintoAndar pet amenity to listing `accepts_pets`.

## Changes

Files touched:

```
 configs/app_config.yaml                         | EN output_language + geo_allowlist
 src/infra/config.py                             | GeoAllowlistConfig; AI default en
 src/core/geo_allowlist.py                       | NEW — city/state allowlist
 src/core/dedupe.py                              | Persist base_price
 src/adapters/db/models.py                       | base_price column
 alembic/versions/a1b2c3d4e5f6_*.py              | NEW — migration
 src/api/schemas.py / property_projection.py     | base_price + fees_bundled
 src/api/property_export.py                      | Export base_price
 src/adapters/scrapers/{quintoandar,olx}.py      | base_price, city/state, pets
 src/adapters/queue/tasks.py                     | scrape_geo_rejected skip path
 src/adapters/ai/{client,prompts}.py             | English verdict template
 frontend/src/components/PropertyModal.jsx       | Fees vs attrs + EN labels
 frontend/src/components/CompareView.jsx         | EN rent/sale labels
 frontend/src/pages/Properties.jsx               | EN fallbacks
 frontend/tests/e2e/property-modal-listings.spec.js | NEW regression
 src/tests/unit/test_geo_allowlist.py            | NEW
 src/tests/unit/test_deal_verdict.py             | EN expectations
 _bmad-output/planning-artifacts/*               | NFR-7 / FR-9 correct-course
```

## New Dependencies

None.

## How to Test

1. Open a property with furnished + pets listings — chips appear under the fees table; Base column shows rent before condo/IPTU.
2. Confirm deal verdict header reads "Deal verdict" and new enrichments are English (`ai.output_language: en`).
3. Re-run scrapes — Porto Alegre (or other non-allowlist) candidates log `scrape_geo_rejected` and do not persist.
4. Automated:
   ```bash
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- Stale PT `deal_summary` rows remain until operator re-runs AI enrichment.
- **No other_taxes field** — platforms do not expose a separate source; bundled condo+IPTU shows a badge when `fees_bundled`.
- Legacy out-of-geo rows are not auto-deleted; re-scrape / manual cleanup optional.
- Multi-language via AI translation: [BIN-63](https://linear.app/felipelrib/issue/BIN-63).
- OLX `…-e-regiao` URLs remain; allowlist is the hard geo gate.
