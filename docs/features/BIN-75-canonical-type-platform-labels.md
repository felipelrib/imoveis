# canonical-type-platform-labels — EN snake_case property type + platform display labels

> Feature branch: `feat/canonical-type-platform-labels` · Linear: `BIN-75` · Status: implemented

## Problem

The Type filter missed OLX listings because `props_json.type` was never written. QuintoAndar stored Portuguese API strings (`Apartamento`, `CasaCondominio`). Platform display was inverted: the Source filter showed `OLX` / `QuintoAndar` while cards, modal, compare, dashboard alerts, and Scraper Control rendered raw slugs (`olx`, `quintoandar`).

## Approach

- Persist canonical English snake_case types (`apartment`, `house`, `condo_house`, `studio`) from both scrapers.
- OLX stamps type from the search category path (same pattern as rent/sale) with URL / prop / title fallbacks.
- API filter matches canonical keys plus legacy aliases so existing QuintoAndar rows still work until re-scrape.
- Shared frontend `formatPlatform` / property-type options for all user-visible surfaces.

## Changes

Files touched:

```
 src/core/property_type.py                         | NEW — normalize + filter aliases
 src/adapters/scrapers/olx.py                      | Extract/stamp props_json.type
 src/adapters/scrapers/quintoandar.py              | Map PT type → canonical
 src/api/properties.py                             | Type filter IN (canonical + aliases)
 frontend/src/labels.js                            | NEW — platform/type display helpers
 frontend/src/pages/Properties.jsx                 | Canonical type options + platform labels
 frontend/src/pages/ScraperControl.jsx             | Platform display labels throughout
 frontend/src/pages/Dashboard.jsx                  | Alert platform labels
 frontend/src/components/PropertyModal.jsx         | Platform display labels
 frontend/src/components/CompareView.jsx           | Platform display labels
 src/tests/unit/test_property_type.py              | NEW — normalization unit tests
 src/tests/unit/test_olx.py                        | Type extraction regressions
 src/tests/unit/test_scoring_and_fees.py           | QA type normalization
 src/tests/unit/test_property_city_filters.py      | Type filter SQL builder
 frontend/tests/e2e/property-type-platform-labels.spec.js | NEW — UI regressions
 docs/features/BIN-75-canonical-type-platform-labels.md | NEW — this doc
```

## New Dependencies

None.

## How to Test

1. Open Properties → Type filter options are Apartment / House / Condo house / Studio; selecting Apartment sends `property_type=apartment`.
2. Property cards and Scraper Control platform select show `OLX` / `QuintoAndar`, not raw slugs.
3. Re-scrape OLX — new rows have `props_json.type` set; Type=Apartment includes them.
4. Automated:
   ```bash
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- Existing OLX rows without `type` need a re-scrape (or a one-shot backfill) before the Type filter includes them.
- Legacy QuintoAndar PT strings continue to match via filter aliases until overwritten on re-scrape.
- Linear: [BIN-75](https://linear.app/felipelrib/issue/BIN-75/canonical-property-type-platform-display-labels).
