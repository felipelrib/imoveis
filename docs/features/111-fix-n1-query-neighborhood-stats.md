# Fix N+1 query in compute_neighborhood_stats scoring recalculation

> Feature branch: `fix/n1-query-neighborhood-stats` · Linear: `BIN-151` · Status: implemented

## Problem

`compute_neighborhood_stats` (`src/adapters/metrics/scoring.py`) is step 1 of `POST /admin/scoring/recalculate` (`src/api/admin.py:151`). After running one bulk SQL window-function query to compute per-neighbourhood price statistics, it looped over every returned property row and, **per row**, ran:

- `session.query(MetricsScoring).filter_by(property_id=prop_id).one_or_none()`
- `session.get(Property, prop_id)`
- (via `_neighbourhood_score_for_property`) `session.get(Neighborhood, prop.neighborhood_id)`

Three round trips per scored property — a classic N+1. The sibling `recalculate_all_combined_scores` docstring claims the whole recalculation is "effectively instantaneous even for millions of rows," but step 1 was O(N) DB round trips and would not scale with growing listing volume. The cost was masked at the small scale the system currently runs at.

## Approach

- Batch-loaded `MetricsScoring`, `Property`, and `Neighborhood` **once per call** instead of once per row:
  - `session.query(MetricsScoring).filter(MetricsScoring.property_id.in_(prop_ids)).all()` → dict keyed by `property_id`.
  - `session.query(Property).filter(Property.id.in_(prop_ids)).all()` → dict keyed by `id`.
  - Distinct `neighborhood_id`s collected from the batch-loaded properties, then `session.query(Neighborhood).filter(Neighborhood.id.in_(neighborhood_ids)).all()` → dict keyed by `id`. Skipped entirely when no property in the batch has a neighbourhood FK.
  - The per-row loop now does plain dict lookups (`.get(prop_id)`) against these three maps instead of issuing new queries.
- Extracted a pure `_neighbourhood_score(nhood: Optional[Neighborhood]) -> float` helper (same aggregation logic `_neighbourhood_score_for_property` already had) so both the still-per-property `_neighbourhood_score_for_property` (used by `score_single_property` and `adapters/queue/tasks.py`, out of scope for this ticket — single-property paths don't have an N+1 to fix) and the new batch path in `compute_neighborhood_stats` share one implementation instead of duplicating the score-aggregation logic.
- Behavior is unchanged: same insert-vs-update branching, same `ai_score` / neighbourhood-score defaults (`0.0` / `0.5`) when a row has no existing `MetricsScoring` or no linked `Neighborhood`.
- No SQL query shape or semantics changed for the main per-neighbourhood window-function query itself — only the three per-row Python-side lookups were batched.

### Testing (brownfield characterization + query-count lock, per `CLAUDE.md`'s testing-discipline table)

- `src/tests/integration/test_scoring_neighborhood_stats_n_plus_one.py` (new):
  - **Characterization**: three properties — one with a pre-existing `MetricsScoring` row (update path) linked to a neighbourhood, one brand-new (insert path) with no neighbourhood, one brand-new (insert path) linked to a neighbourhood — each isolated in its own single-row price cohort so `stat_score` is deterministically `0.5` for all three (mean == its own price/m², so `z == 0.0`). Asserts the resulting `combined_score` for each matches `blend_combined_score(...)` computed with the expected `ai_score` / neighbourhood-score inputs, locking that the batched dict lookups resolve identically to the old per-row queries for both the insert and update branches, and with/without a neighbourhood FK.
    - Caught a test-design bug during development: linking two properties to the **same** `Neighborhood` row merges their price cohorts (the cohort key is `COALESCE(n.name, props_json->>'neighborhood', 'Unknown')` — the neighbourhood's `name` wins over the `props_json` label once a FK is set), so each FK-linked fixture needed its own `Neighborhood` row to stay in an isolated cohort.
  - **Query-count lock**: uses a real SQLAlchemy `before_cursor_execute` event listener (no session mocking, per the ticket's explicit instruction) to count SELECT statements issued by one `compute_neighborhood_stats` call over 2 properties, then again after growing to 8 properties. Asserts the SELECT count is identical both times (and `<= 4`: the main window-function query + one batch load each for `MetricsScoring`/`Property`/`Neighborhood`) even though the row count processed grows 4x — locking O(1) round trips instead of O(N).
- Existing integration coverage (`test_scoring_spatial_cohorts.py`, `test_scoring_sql_assembly.py`) continued to pass unchanged, confirming the rent/sale cohort math and spatial-FK-vs-string-cohort behavior the batching touches indirectly (via the `Property`/`Neighborhood` lookups) was not altered.

## Changes

Files touched:

```
src/adapters/metrics/scoring.py                                | compute_neighborhood_stats(): batch-load MetricsScoring/Property/Neighborhood once per call instead of per-row queries; extracted _neighbourhood_score() pure helper shared with _neighbourhood_score_for_property()
src/tests/integration/test_scoring_neighborhood_stats_n_plus_one.py | NEW — characterization lock (insert/update paths, with/without neighbourhood FK) + SQLAlchemy event-based SELECT-count lock (O(1) vs O(N))
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
```

Targeted:

```bash
PYTHONPATH=src pytest src/tests/integration/test_scoring_neighborhood_stats_n_plus_one.py -v
```

## Notes / Follow-ups

- Tracked as part of the BIN-128 tech-debt remediation epic (v0.10 milestone).
- `_neighbourhood_score_for_property` (used by `score_single_property` and `adapters/queue/tasks.py`) still does one `session.get(Neighborhood, ...)` per call — out of scope here since those are single-property code paths, not the batch recalculation this ticket targets.
