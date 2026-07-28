# Max price rent/sale filter — hide steppers and cap by listing type

> Feature branch: `feat/max-price-rent-sale-filter` · Linear: `BIN-77` · Status: implemented

## Problem

The Properties “Max price R$” control used a native `type="number"` input with browser increment/decrement steppers. Separately, `max_price` was applied to the property row’s decisioning price (`p.price` / lowest listing, rent preferred). A sale budget like R$500k therefore still returned dual-listed homes whose rent was under the cap but whose sale price was far higher.

## Approach

- Suppress number steppers with CSS (`appearance: textfield` + webkit spin-button none) so the field stays numeric for mobile keyboards without looking like a spinner.
- Add `price_type=rent|sale` to list/export filters. When `max_price` is set, require an matching `property_listings` row (`listing_type` + `price <= max_price`) instead of filtering `p.price`.
- Default `price_type` to `rent` when omitted (backward compatible); if omitted but `listing_type` is `rent` or `sale`, inherit that.
- UI: Rent/Sale select next to max price; Transaction Rent Only / Sale Only syncs the price type.

## Changes

Files touched:

```
 src/api/properties.py                                      | Filter max_price via property_listings + price_type
 src/api/saved_searches.py                                  | Persist optional price_type on saved searches
 frontend/src/api.js                                        | Pass price_type when max_price is set
 frontend/src/pages/Properties.jsx                          | Price-type control, sync, clear/export/map wiring
 frontend/src/index.css                                     | Hide number input steppers
 frontend/tests/e2e/properties-max-price-filter.spec.js     | NEW — regression for steppers + price_type=sale
 frontend/tests/e2e/properties-export.spec.js               | Use max-price data-testid
 src/tests/unit/test_property_max_price_filter.py           | NEW — unit coverage for SQL filter builder
 docs/features/57-max-price-rent-sale-filter.md             | NEW — this note
```

## New Dependencies

None.

## How to Test

1. Open Properties → Advanced Filters.
2. Confirm Max price has no up/down steppers.
3. Set Max price to `500000` and Price type to **Sale** — dual-listed homes with sale above 500k should drop even if rent is low.
4. Switch Transaction to **Sale Only** — price type should become Sale automatically.
5. Automated:
   ```bash
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- ~~Sort-by-price still uses decisioning `p.price` (lowest listing); only the max-price *filter* is listing-type aware.~~ Resolved by [BIN-106](https://linear.app/felipelrib/issue/BIN-106/listing-type-aware-sort-by-price-not-decisioning-pprice) / feature 86.
- Saved-search camelCase vs snake_case: fixed in [BIN-100](https://linear.app/felipelrib/issue/BIN-100) / `docs/features/80-locale-aware-filters.md` (API aliases + `toSavedSearchWire`). [BIN-109](https://linear.app/felipelrib/issue/BIN-109) adds create-path + Playwright regressions for `price_type` / `max_price` round-trip.
