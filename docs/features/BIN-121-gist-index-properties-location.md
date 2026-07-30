# GIST index on properties.location — spatial filter performance

> Feature branch: `feat/bin-121-gist-index-properties-location` · Linear: `BIN-121` · Status: implemented

## Problem

Feature docs 28 / 31 left an optional follow-up: a GIST on `properties.location` if containment / map filters needed it. The initial Alembic migration only *commented* that GeoAlchemy2 would manage a spatial index; the durable, project-named index was never asserted, and dual GISTs could appear if both GeoAlchemy2’s default `idx_properties_location` and an explicit migration ran.

## Approach

- Proactively ship a migration (acceptance allows this without a prior production profile) that normalizes to one canonical GIST: `ix_properties_location_gist` (same naming pattern as `ix_neighborhoods_geometry_gist`).
- On upgrade: rename GeoAlchemy2’s `idx_properties_location` when present; otherwise `CREATE INDEX`; drop the legacy name if both exist so inserts never maintain two identical GISTs.
- Set `spatial_index=False` on the SQLAlchemy `Property.location` column so `create_all` / future autogenerate do not invent a second index name; Alembic owns the GIST.
- Helps geometry predicates used by map bbox (`ST_Within` + `ST_MakeEnvelope` in `api.properties`) and any future “points in polygon” scans. Does **not** accelerate `ST_DWithin(location::geography, …)` in fuzzy dedupe — that would need a separate geography GIST (out of scope).

### Benchmark note

On a fresh PostGIS 15 worktree DB after this migration (empty `properties`):

```text
EXPLAIN SELECT 1 FROM properties p
WHERE ST_Within(
  p.location,
  ST_MakeEnvelope(-44.0, -20.0, -43.0, -19.0, 4326)
);
```

Planner chose:

```text
Index Scan using ix_properties_location_gist on properties p
  Index Cond: (location @ <envelope>)
  Filter: st_within(location, <envelope>)
```

So the GIST is eligible for the same predicate shape as the Properties list `bbox` filter. Tiny corpora may still Seq Scan when `enable_seqscan` is on; with volume (or `SET enable_seqscan = off`) the index path is preferred. Re-check on a populated primary with `EXPLAIN (ANALYZE, BUFFERS)` when map viewport queries feel slow.

## Changes

Files touched:

```
 alembic/versions/f4eea36d6f80_gist_index_properties_location.py | NEW — rename/create/dedupe GIST
 src/adapters/db/models.py                                       | spatial_index=False on location
 src/tests/integration/test_properties_location_gist.py          | NEW — index presence lock
 docs/features/BIN-121-gist-index-properties-location.md              | NEW — this doc
 docs/features/BIN-53-load-neighbourhood-polygons.md                 | Follow-up → BIN-121
 docs/features/BIN-54-assign-properties-spatial-containment.md       | Follow-up → BIN-121
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
   # or: PYTHONPATH=src pytest src/tests/integration/test_properties_location_gist.py -v
   ```
3. Confirm index:
   ```bash
   psql "$DATABASE_URL" -c "\di+ ix_properties_location_gist"
   ```

## Notes / Follow-ups

- Optional later: GIST on `(location::geography)` if fuzzy-dedupe `ST_DWithin` becomes hot under large corpora.
- Single-property `ST_Covers(n.geometry, p.location)` assignment still benefits primarily from `ix_neighborhoods_geometry_gist`; this index matters more when scanning many property points against a fixed envelope/polygon.
