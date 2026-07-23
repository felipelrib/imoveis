# Scoring cohorts prefer spatial neighbourhoods — FK name over props_json string

> Feature branch: `feat/bin-55-scoring-cohorts-spatial` · Linear: `BIN-55` · Status: implemented

## Problem

After BIN-54 assigns `neighborhood_id` from PostGIS containment, deal colouring still needed proof that neighbourhood stats / combined scores prefer the linked neighbourhood over the brittle `props_json` string, without inventing a second scoring path (AD-10 / FR-22).

## Approach

- Keep the single scoring module (`adapters.metrics.scoring`) as the only writer of `metrics_scoring` cohort stats.
- Cohort key remains name-based: `COALESCE(n.name, props_json->>'neighborhood', 'Unknown')` so spatial FK wins when set; string-only properties keep working.
- Shared SQL fragment + `_property_neighborhood_key` so bulk recompute and single-property scoring cannot drift.
- Fix broken `WITH stats AS (...)` CTE (missing `WITH` after earlier median refactor).
- No assigner calls from scoring or API; assignment stays in the enrichment pipeline (BIN-54).

## Changes

Files touched:

```
 src/adapters/metrics/scoring.py                              | Fix WITH CTE; shared cohort-key SQL; key helper
 src/tests/unit/test_scoring_cohort_key.py                    | NEW — FK preference / string / Unknown
 src/tests/integration/test_scoring_spatial_cohorts.py        | NEW — string fallback + FixtureA membership shift
 docs/features/32-scoring-cohorts-spatial-preference.md       | NEW — this doc
 _bmad-output/implementation-artifacts/sprint-status.yaml     | Story 5.3 done
```

## New Dependencies

None.

## How to Test

1. Agent gate:
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Focused (worktree ports via `validate.sh` / `.env.local`):
   ```bash
   bash scripts/agent/validate.sh backend
   # or:
   PYTHONPATH=src pytest src/tests/unit/test_scoring_cohort_key.py \
     src/tests/integration/test_scoring_spatial_cohorts.py -v
   ```

## Notes / Follow-ups

- Existing rows without pipeline re-assignment stay on string cohorts until scrape/`ai_enrich` runs (no bulk backfill in this story).
- Admin `POST /scoring/recalculate` remains a bulk recompute of the same functions — not a competing geo/score job.
- Related: BIN-53 polygons, BIN-54 assignment, epic BIN-23 / FR-22.
