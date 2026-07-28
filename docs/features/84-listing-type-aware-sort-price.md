# Listing-type-aware sort-by-price

> Feature branch: `feat/bin-106-listing-type-aware-sort-price` · Linear: `BIN-106` · Status: implemented

## Problem

Max-price filtering is listing-type aware (BIN-77), and combined-score sort switches on `listing_type` (BIN-83), but `sort_by=price` still ordered by decisioning `p.price` (lowest listing, rent-preferred). With Transaction = Sale Only, cheap-rent / expensive-sale homes sorted by rent.

## Approach

- Resolve an effective sort price type: explicit `price_type` wins, else inherit `listing_type` when `rent|sale`.
- When typed, `ORDER BY` uses `COALESCE(MIN(active listing price for that type), p.price)`.
- When `listing_type` is omitted/`both` and no `price_type`, keep decisioning `p.price` (do **not** default to rent like max_price does).
- List and export share `_build_list_filters`, so one change covers both. No frontend change — UI already sends `listing_type` / `price_type`.

## Changes

Files touched:

```
 src/api/properties.py                                      | Typed sort price expr + helpers
 src/tests/unit/test_property_sort_price.py                 | NEW — unit coverage for ORDER BY
 src/tests/integration/test_sort_price_listing_type.py      | NEW — crossed dual-listed order
 src/tests/contract/test_api_contract.py                    | Smoke: sort_by=price + listing_type=sale
 docs/features/57-max-price-rent-sale-filter.md             | Mark sort follow-up resolved
 docs/features/84-listing-type-aware-sort-price.md          | NEW — this note
```

## New Dependencies

None.

## How to Test

1. Open Properties → Transaction **Sale Only** → Sort by **Price (low→high)**.
2. Dual-listed homes should order by sale price, not rent.
3. Switch Transaction to **Both** — order returns to decisioning (rent-preferred) price.
4. Automated:
   ```bash
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- Card display price / `primary_listing` projection is unchanged (still AD-12 decisioning).
- Favourites sort has no listing-type filters and still uses its own path.
