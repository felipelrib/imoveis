# rent-sale-price-per-m2-cohorts — Separate rent and sale neighbourhood $/m²

> Feature branch: `feat/bin-84-rent-sale-price-per-m2-cohorts` · Linear: `BIN-84` · Status: implemented

## Problem

Neighbourhood average price/m² mixed rent and sale into one cohort via `properties.price / area_m2`. A rent listing (~R$47/m²) was compared to a blended or sale-skewed average (~R$4000/m²).

## Approach

- Derive $/m² from active `property_listings` (`MIN(price)` per `listing_type`).
- Partition neighbourhood means/medians by listing type so rent and sale never share a cohort.
- Store both pairs (`price_per_m2_*`, `neighborhood_mean_*`, `neighborhood_median_*`) when available.
- Keep legacy `price_per_m2` / `neighborhood_mean` / `stat_score` on the primary type (rent preferred).
- Repair existing rows via `POST /admin/scoring/recalculate` (schema migration only; no data backfill).

## Changes

Files touched:

```
 alembic/versions/d1e2f3a4b5c6_rent_sale_price_per_m2_cohorts.py | NEW — six nullable metrics columns
 src/adapters/db/models.py                                      | MetricsScoring rent/sale fields
 src/adapters/metrics/scoring.py                                | Listing-type cohorts + primary fallback
 src/api/schemas.py                                             | Expose new optional fields
 src/api/property_projection.py                                 | Map + SELECT new columns
 src/api/properties.py                                          | Detail SELECT includes dual fields
 src/api/property_export.py                                     | CSV columns for dual ppm/means
 frontend/src/components/PropertyModal.jsx                      | Type-labeled ppm + avg rows
 frontend/src/components/CompareView.jsx                        | Rent/sale compare rows
 src/tests/unit/test_scoring_rent_sale_ppm.py                   | NEW — primary-type helper
 src/tests/integration/test_scoring_spatial_cohorts.py          | Rent≠sale cohort regression
 docs/features/61-rent-sale-price-per-m2-cohorts.md             | NEW — this doc
```

## New Dependencies

None.

## How to Test

1. After deploy/migrate, open Dashboard → **Recalculate All Scores**.
2. Open a rent-only property in a mixed neighbourhood: Price / m² (rent) and Neighbourhood avg / m² (rent) should be the same order of magnitude.
3. Dual-listed property: both rent and sale pairs appear in the modal.
4. Automated:
   ```bash
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- **Follow-up**: [BIN-83](https://linear.app/felipelrib/issue/BIN-83/dual-stat-score-z-score-by-listing-type-filter-aware-sorting) — dual `stat_score` / `z_score` and filter-aware list sorting (rent vs sale can score differently).
- Existing rows stay stale until Recalculate (or enrichment that calls `score_single_property`).
