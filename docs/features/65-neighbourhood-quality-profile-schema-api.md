# neighbourhood-quality-profile-schema-api — Durable nhood quality profile storage + read API

> Feature branch: `feat/neighbourhood-quality-profile-schema-api` · Linear: `BIN-86` · Status: implemented

## Problem

The `neighborhoods` table only stored name/city/state/geometry. Later curated YAML and geo jobs (OSM amenities, transit, access, risk) had nowhere durable to write objective quality scores, and the Properties neighbourhoods endpoint only returned filter counts.

## Approach

- Add nullable score columns (`amenity_score`, `transit_score`, `access_score`, `safety_score`) plus `risk_flags[]`, JSONB `quality_meta`, and `quality_notes` on `neighborhoods`.
- Scores are floats in `[0.0, 1.0]` at the API layer; `null` means unknown so partial fills (YAML → OSM → transit) work.
- Extend `NeighborhoodModel` and `GET /properties/neighborhoods` to include profile fields; add `GET /properties/neighborhoods/{id}` for a single row.
- No scoring blend or UI changes — storage + read only (BIN-94 later).

## Changes

Files touched:

```
 alembic/versions/7b8c9d0e1f2a_neighbourhood_quality_profile.py | NEW — profile columns
 src/adapters/db/models.py                                      | Neighborhood quality fields
 src/core/neighbourhood_quality.py                              | NEW — score/flag/meta mapping
 src/api/schemas.py                                             | NeighborhoodModel profile fields
 src/api/properties.py                                          | List + detail endpoints
 src/tests/unit/test_neighbourhood_quality.py                   | NEW — mapper + schema
 src/tests/contract/test_api_contract.py                        | Profile keys + detail 404
 src/tests/integration/test_neighbourhood_quality_profile.py    | NEW — DB round-trip
 docs/features/65-neighbourhood-quality-profile-schema-api.md   | NEW — this doc
 _bmad-output/implementation-artifacts/sprint-status.yaml       | Epic 6 / 6.1 tracking
```

## New Dependencies

None.

## How to Test

1. Migrate DB (`alembic upgrade head` / compose recreate API).
2. Optionally set profile columns on a neighbourhood row; `GET /properties/neighborhoods` and `GET /properties/neighborhoods/{id}` return nullable scores / `risk_flags` / `quality_meta`.
3. Automated:
   ```bash
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- Fill pipelines: [BIN-87](https://linear.app/felipelrib/issue/BIN-87) curated YAML, [BIN-88](https://linear.app/felipelrib/issue/BIN-88)–[BIN-91](https://linear.app/felipelrib/issue/BIN-91) geo overlays, optional [BIN-92](https://linear.app/felipelrib/issue/BIN-92) crime.
- Blend into scoring/UI: [BIN-94](https://linear.app/felipelrib/issue/BIN-94). Epic: [BIN-85](https://linear.app/felipelrib/issue/BIN-85).
