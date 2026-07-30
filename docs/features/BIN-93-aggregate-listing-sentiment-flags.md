# aggregate-listing-sentiment-flags — weak neighbourhood aggregates from listing LLM flags

> Feature branch: `feat/bin-93-listing-sentiment-agg` · Linear: `BIN-93` · Status: implemented

## Problem

Neighbourhood quality fills (YAML, OSM, access, risk) are objective. Listing LLM green/red flags remain per-property marketing noise. Operators still want an optional bairro-level view of those claims — clearly labeled as biased, never as ground truth.

## Approach

- Aggregate `metrics_scoring.meta.sentiment` green/red flags by `properties.neighborhood_id`.
- Store only under nested `quality_meta.listing_claim_stats` with `source: listing_llm_aggregate`, sample size, top frequencies, and an explicit bias disclaimer.
- Update `quality_meta` only — never write amenity/transit/access/safety score columns.
- Default `enabled: false`; Celery beat + admin enqueue when opted in; CLI always runnable for ops.

## Changes

Files touched:

```
 src/core/listing_claim_stats.py                         | NEW — normalize / aggregate / merge helpers
 src/adapters/geo/listing_claim_refresh.py               | NEW — DB refresh orchestration
 src/infra/config.py                                     | ListingClaimStatsConfig under neighbourhood_quality
 configs/app_config.yaml                                 | listing_claim_stats block (disabled by default)
 src/adapters/queue/celery_app.py                        | route + beat gate
 src/adapters/queue/tasks.py                             | refresh_listing_claim_stats task
 src/api/admin.py                                        | POST /admin/neighbourhoods/listing-claims/refresh
 scripts/dev/refresh_listing_claim_stats.py              | NEW — operator CLI
 src/tests/unit/test_listing_claim_stats.py              | NEW — domain TDD
 src/tests/unit/test_listing_claim_refresh.py            | NEW — task skip/run glue
 src/tests/unit/test_schedule.py                         | Beat/route assertions
 src/tests/integration/test_listing_claim_stats.py       | NEW — meta write, scores preserved
 docs/features/BIN-93-aggregate-listing-sentiment-flags.md   | NEW — this doc
 _bmad-output/implementation-artifacts/sprint-status.yaml | 6-8 done
```

## New Dependencies

None.

## How to Test

1. Ensure AI-enriched listings have `neighborhood_id` and `metrics_scoring.meta.sentiment`.
2. Dry-run aggregate:
   ```bash
   PYTHONPATH=src python scripts/dev/refresh_listing_claim_stats.py
   ```
3. Confirm `GET /properties/neighborhoods/{id}` shows `quality_meta.listing_claim_stats` with `source: listing_llm_aggregate` and that `amenity_score` / `safety_score` are unchanged.
4. Automated:
   ```bash
   bash scripts/agent/validate.sh all
   ```

### Bias / operator notes

- Sellers omit problems; high green-flag rate ≠ good neighbourhood.
- Treat aggregates as a weak secondary signal alongside OSM/curated/access profiles.
- Set `neighbourhood_quality.listing_claim_stats.enabled: true` only when enough enriched listings exist; rebuild beat + scraper worker for scheduled runs.

## Notes / Follow-ups

- Blend into scoring/UI: [BIN-94](https://linear.app/felipelrib/issue/BIN-94). Epic: [BIN-85](https://linear.app/felipelrib/issue/BIN-85).
- Concurrent fill jobs keep sibling keys under `quality_meta` (access, risk, amenity_counts, listing_claim_stats).
