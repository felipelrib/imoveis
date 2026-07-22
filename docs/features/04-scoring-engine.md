# Scoring Engine — Per-neighbourhood statistical scoring with dynamic weight recalculation

> Feature branch: `feat/scoring-engine` · Linear: `BIN-XX` · Status: implemented

## Problem

Users need to identify undervalued properties relative to their neighbourhood. A global price ranking is misleading because R$3,000/month in Savassi is cheap but expensive in Venda Nova. Per-neighbourhood z-scores solve this by answering "how does this property compare to its peers?"

## Approach

- **SQL window functions**: A single CTE-based query computes per-neighbourhood mean, median (via `PERCENTILE_CONT`), stddev, z-score, and percentile rank for all properties in one database round-trip.
- **Sigmoid transformation**: Z-scores are mapped to [0, 1] via `1 / (1 + exp(z))` — negative z (cheaper) → higher stat_score.
- **Combined score**: `combined_score = stat_score × stat_weight + ai_score × ai_weight` with configurable weights (default 50/50).
- **Bulk recalculation**: `recalculate_all_combined_scores()` uses a single `UPDATE ... SET` SQL statement, making weight changes O(1) in application memory.
- **Single-property scoring**: `score_single_property()` recomputes the entire neighbourhood stats for the property's neighbourhood after AI enrichment, ensuring scores stay fresh.
- **Categorical labels**: Z-scores are mapped to human-readable categories (Highly Undervalued → Highly Overvalued) stored in `metrics_scoring.meta.stat_analysis`.

## Changes

Files touched:

```
 src/adapters/metrics/scoring.py | compute_neighborhood_stats, recalculate_all_combined_scores, score_single_property
 src/adapters/db/models.py       | MetricsScoring ORM model
 src/core/entities.py            | ScoringWeights Pydantic model
```

## New Dependencies

None — uses PostgreSQL window functions and built-in Python `math`.

## How to Test

1. Populate the database with properties from at least 2 neighbourhoods.
2. Trigger score recalculation via admin API:
   ```bash
   curl -X POST http://localhost:8000/admin/scoring/recalculate \
     -H 'X-API-Key: YOUR_KEY' \
     -H 'Content-Type: application/json'
   ```
3. Verify scores in the database:
   ```sql
   SELECT property_id, stat_score, ai_score, combined_score, z_score, percentile_rank
   FROM metrics_scoring ORDER BY combined_score DESC LIMIT 10;
   ```

## Notes / Follow-ups

### Tech Debt

- **`score_single_property` recomputes the ENTIRE neighbourhood** — For a neighbourhood with 10,000 properties, this is a heavy operation triggered after every AI enrichment. Should cache or batch.
- **No index on `props_json->>'neighborhood'`** — The window function queries use this JSONB access path without a GIN or functional index, which will be slow at scale.
- **Median computation repeated** — The median is computed in a separate CTE and then JOINed, which could be combined with the stats CTE.
