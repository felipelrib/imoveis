# dual-stat-score-by-listing-type — Rent/sale scores + filter-aware sorting

> Feature branch: `feat/bin-83-dual-stat-score-by-listing-type` · Linear: `BIN-83` · Status: implemented

## Problem

After BIN-84 split rent/sale price-per-m² cohorts, `stat_score`, `z_score`, and `combined_score` still reflected only the primary listing type (rent preferred). A dual-listed home could look undervalued on rent and overvalued on sale, but list cards, sort, and min-score filters showed one score regardless of the Transaction filter.

## Approach

- Persist `stat_score_rent/sale`, `z_score_rent/sale`, `percentile_rank_rent/sale`, and `combined_score_rent/sale` on `metrics_scoring` alongside legacy primary columns.
- Bulk scoring SQL already had per-type stddev/percentile — compute dual scores in the Python loop and in `score_single_property`.
- List `ORDER BY` and `min_score` switch to typed `combined_score_*` when `listing_type=rent|sale`; primary column when `both`.
- Cards show **dual badges** (Rent + Sale scores) when Transaction=Both and both typed scores exist; single typed badge when filtered.
- Top-deals digest supports type-aware ranking via `alerts.top_deals.score_target` (BIN-107 / feature 88).

## Changes

Files touched:

```
 alembic/versions/a4f8c2e91b7d_dual_listing_type_scores.py | NEW — eight nullable dual score columns
 src/adapters/db/models.py                                  | MetricsScoring dual score fields
 src/adapters/metrics/scoring.py                            | _compute_type_scores + dual persist + bulk recalc
 src/api/schemas.py                                         | Expose dual score fields on list/detail
 src/api/property_projection.py                             | SELECT + map dual scores
 src/api/property_export.py                                 | CSV columns for dual scores
 src/api/properties.py                                      | Filter-aware sort/min_score SQL
 frontend/src/utils/scores.js                               | NEW — listingType score helpers
 frontend/src/pages/Properties.jsx                          | Dual badges, min-score label fix
 frontend/src/components/MapView.jsx                        | Filter-aware pin score
 frontend/src/components/PropertyModal.jsx                  | Dual score detail rows
 frontend/src/components/CompareView.jsx                     | Dual score compare rows
 src/tests/unit/test_scoring_dual_scores.py                 | NEW — dual score math
 src/tests/unit/test_property_list_score_filter.py          | NEW — filter-aware SQL regression
 src/tests/integration/test_scoring_spatial_cohorts.py      | Dual-listed distinct scores
 frontend/tests/e2e/properties-dual-scores.spec.js           | NEW — dual badge e2e
 docs/features/BIN-83-dual-stat-score-by-listing-type.md         | NEW — this doc
```

## New Dependencies

None.

## How to Test

1. After migrate, run Dashboard → **Recalculate All Scores**.
2. Open Properties with Transaction=Both: dual-listed homes show separate Rent/Sale score badges.
3. Switch Transaction to Sale: cards show the sale combined score; sort/min-score use sale column.
4. Automated:
   ```bash
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- Type-aware top-deals digest shipped as BIN-107 / feature 88 (`alerts.top_deals.score_target`).
- Existing rows need Recalculate (or enrichment calling `score_single_property`) to populate dual columns.
- Depends on BIN-84 rent/sale ppm cohort columns.
