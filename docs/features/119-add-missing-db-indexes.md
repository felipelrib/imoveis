# Missing indexes on properties.active and metrics_scoring.property_id — hot-path query performance

> Feature branch: `feat/add-missing-db-indexes` · Linear: `BIN-152` · Status: implemented

## Problem

Found during the 2026-07-29 technical debt audit follow-up pass (API/infra lane). `WHERE p.active = true` appears in nearly every hot-path query (`list_properties`, `export_properties`, count queries, neighbourhoods/cities aggregates), and `metrics_scoring.property_id` is joined in every properties list/detail/export query — but neither column had an index. No `op.create_index` in `alembic/versions/` targeted either column before this change. Fine at current listing volume; would become a sequential-scan bottleneck as volume grows (same class of concern as the already-shipped `BIN-121` GIST index on `properties.location`).

## Approach

- Checked the actual value distribution on `properties.active` in the primary DB before deciding index shape (per acceptance criteria):
  ```text
  SELECT active, count(*) FROM properties GROUP BY active;
   active | count
  --------+-------
   f      |   817
   t      | 25371
  ```
  `active = true` is ~96.9% of rows. Because the hot-path predicate (`active = true`) matches the overwhelming majority of the table, a partial index scoped to `WHERE active` would still index ~97% of rows — negligible size/selectivity benefit over a plain index, and Postgres is unlikely to prefer an index scan over a seq scan for a single-column predicate that matches almost everything anyway. A **full (non-partial) btree index** was used instead of a partial one.
- `metrics_scoring.property_id` is a plain FK/join column (one row per property, no skew) — indexed unconditionally, matching the existing pattern already used for `properties.platform_id` and `properties.neighborhood_id` in this codebase.
- Both indexes are created with `CREATE INDEX CONCURRENTLY` (via `op.get_context().autocommit_block()`) so applying the migration doesn't hold a table-locking transaction on `properties` / `metrics_scoring`, which matters as both tables grow.
- Mirrored `index=True` onto the corresponding SQLAlchemy `Column` declarations in `src/adapters/db/models.py` so the ORM model and the DB stay in sync (confirmed via `alembic check` — no drift introduced by either new index).
- Schema-only change — no application query code was modified; the query planner picks up the new indexes automatically for existing `WHERE active = true` / `JOIN metrics_scoring ON property_id = ...` predicates.

## Changes

Files touched:

```
 alembic/versions/b65411932ef9_add_indexes_properties_active_metrics_.py | NEW — CONCURRENTLY create ix_properties_active + ix_metrics_scoring_property_id
 src/adapters/db/models.py                                              | index=True on Property.active and MetricsScoring.property_id
 src/tests/integration/test_missing_db_indexes.py                       | NEW — index presence lock (full, non-partial on active; btree on property_id)
 docs/features/119-add-missing-db-indexes.md                            | NEW — this doc
```

## New Dependencies

None.

## How to Test

1. Agent gate:
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Focused integration:
   ```bash
   bash scripts/agent/validate.sh backend
   # or: PYTHONPATH=src pytest src/tests/integration/test_missing_db_indexes.py -v
   ```
3. Confirm indexes:
   ```bash
   psql "$DATABASE_URL" -c "\di+ ix_properties_active"
   psql "$DATABASE_URL" -c "\di+ ix_metrics_scoring_property_id"
   ```

## Notes / Follow-ups

- `alembic check` reports pre-existing drift unrelated to this change (PostGIS `postgis_tiger_geocoder` system tables — `place`, `county`, `edges`, `topology`, etc. — plus a couple of older index/constraint naming mismatches predating BIN-152). `validate.sh` already treats this specific check as informational-only (`alembic check: PostGIS system tables detected (expected — informational only)`); neither `ix_properties_active` nor `ix_metrics_scoring_property_id` appear in that drift output.
- Re-check `EXPLAIN (ANALYZE, BUFFERS)` on the populated primary DB once volume is materially higher than the ~26k rows measured here, to confirm the planner is actually choosing the new indexes for the hot-path queries (an empty/small worktree DB will always prefer Seq Scan, same caveat as `docs/features/90-gist-index-properties-location.md`).
- If `properties.active` selectivity shifts significantly in the future (e.g. most listings become inactive), reconsider a partial index — the current full-index decision is based on the 2026-07-29 distribution snapshot above.
