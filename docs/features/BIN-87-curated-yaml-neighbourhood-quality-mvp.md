# curated-yaml-neighbourhood-quality-mvp — Operator-curated BH quality scores

> Feature branch: `feat/curated-yaml-nhood-quality` · Linear: `BIN-87` · Status: implemented

## Problem

BIN-86 added durable neighbourhood quality columns, but there was no fill path. Shipping transparent MVP scores for major BH bairros should not wait on OSM/transit/risk pipelines.

## Approach

- Config-driven curated profiles in `configs/neighbourhood_quality.yaml` keyed by display name + city (defaults BH/MG), with optional `slug` matching scraper fan-out.
- Idempotent loader updates existing `neighborhoods` rows only; unknown names are skipped with `neighbourhood_quality_unknown` log — never invent rows.
- Stamp `quality_meta.source = curated` (plus `refreshed_at`). Scores are **operator judgment**, not ground truth; later geo jobs override by stamping their own `source`.
- Seed the QuintoAndar + OLX BH fan-out union (~36 bairros including Horto).
- CLI (`scripts/dev/load_neighbourhood_quality.py`) and `POST /admin/neighbourhoods/quality/load` share the same core apply path.

## Changes

Files touched:

```
 configs/neighbourhood_quality.yaml                              | NEW — curated BH profiles
 src/core/neighbourhood_quality_yaml.py                          | NEW — parse + apply loader
 scripts/dev/load_neighbourhood_quality.py                       | NEW — CLI
 src/api/admin.py                                                | POST /admin/neighbourhoods/quality/load
 src/tests/fixtures/neighbourhood_quality_tiny.yaml              | NEW — tiny parse/load fixture
 src/tests/unit/test_neighbourhood_quality_yaml.py               | NEW — parse + fan-out coverage
 src/tests/unit/test_admin_neighbourhood_quality_load.py         | NEW — admin endpoint
 src/tests/integration/test_neighbourhood_quality_yaml.py        | NEW — DB round-trip / skip / idempotent
 docs/features/BIN-87-curated-yaml-neighbourhood-quality-mvp.md      | NEW — this doc
 _bmad-output/implementation-artifacts/sprint-status.yaml        | 6-2 → done
```

## New Dependencies

None.

## How to Test

1. Ensure neighbourhood polygons (or at least name/city/state rows) exist for the seeded bairros.
2. Dry-run then load:
   ```bash
   PYTHONPATH=src python scripts/dev/load_neighbourhood_quality.py --dry-run
   PYTHONPATH=src python scripts/dev/load_neighbourhood_quality.py
   ```
3. Or admin: `POST /admin/neighbourhoods/quality/load` with API key.
4. Automated:
   ```bash
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- Scores are provisional operator judgment; document overrides when [BIN-88](https://linear.app/felipelrib/issue/BIN-88)–[BIN-91](https://linear.app/felipelrib/issue/BIN-91) land.
- Blend into scoring/UI: [BIN-94](https://linear.app/felipelrib/issue/BIN-94). Epic: [BIN-85](https://linear.app/felipelrib/issue/BIN-85).
- Schema/API foundation: [BIN-86](https://linear.app/felipelrib/issue/BIN-86) / docs/features/BIN-86-neighbourhood-quality-profile-schema-api.md.
