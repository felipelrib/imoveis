# Max price Sale filter live — rebuild API + text input (BIN-79)

> Feature branch: `fix/max-price-sale-filter` · Linear: `BIN-79` · Status: implemented

## Problem

After BIN-77, the Properties UI offered Rent/Sale next to max price, but the local API Docker image was still on the pre-BIN-77 code path (`p.price <= max_price`). Selecting Sale + R$5000 therefore kept dual-listed homes whose rent was under the cap. Number steppers also still appeared because CSS alone did not suppress them in the user’s browser.

## Approach

- Rebuild/restart the primary `api` image so `_build_list_filters` listing-based `price_type` is live (verified: sale≤5000 dropped from ~2489 → 1).
- Change max-price to `type="text"` + `inputMode="numeric"` (digits only) so native steppers cannot render.
- Add an integration regression that seeds rent+sale listings and asserts sale caps do not match on rent.

## Changes

Files touched:

```
 frontend/src/pages/Properties.jsx                              | Max price type=text, digits-only
 frontend/tests/e2e/properties-max-price-filter.spec.js         | Assert type=text (no steppers)
 src/tests/integration/test_max_price_sale_filter.py            | NEW — dual-list sale/rent cap regression
 docs/features/BIN-79-max-price-sale-filter-live.md                 | NEW — this note
```

## New Dependencies

None.

## How to Test

1. Ensure API image is current: `docker compose --env-file .env.local build api && docker compose --env-file .env.local up -d api`
2. Properties → Advanced Filters → Max price `5000` → Sale — dual-listed homes with sale ≫ 5000 must disappear.
3. Automated:
   ```bash
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- API code is baked into the image (only `configs/` is bind-mounted). After filter/API Python changes, rebuild `api` before trusting local UI.
- One remaining sale≤5000 row in prod data has a ~R$1300 “sale” listing (data quality) — out of scope here.
