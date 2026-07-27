# Access / travel-time to downtown hubs — neighbourhood access_score fill

> Feature branch: `feat/bin-90-access-travel-time-hubs` · Linear: `BIN-90` · Status: implemented

## Problem

House-hunters cannot tell how accessible a neighbourhood is to downtown / fixed life hubs; distance-to-life was guessed from ads. BIN-86 already stores `access_score` + `quality_meta`, but nothing computed those fields.

## Approach

- Configurable hubs per city in `configs/app_config.yaml` (`neighbourhood_access.hubs`).
- Refresh job computes a representative point via `ST_PointOnSurface`, then routes to hubs with self-hosted OSRM when `base_url` is set; otherwise haversine + `avg_speed_kmh` estimates minutes.
- Best hub (lowest minutes) → `access_score = clamp(1 - minutes/max_minutes, 0, 1)`.
- Nested `quality_meta.access` (hub_id, minutes, mode, distance_m, provider, refreshed_at) so parallel fill jobs do not wipe sibling meta keys.
- Celery beat + admin enqueue + CLI; tests mock OSRM HTTP.

## Changes

Files touched:

```
 configs/app_config.yaml                         | NEW section neighbourhood_access + hubs
 src/infra/config.py                             | AccessHubConfig + NeighbourhoodAccessConfig
 src/core/neighbourhood_access.py                | NEW — score/meta/hub helpers
 src/adapters/geo/__init__.py                    | NEW — geo adapters package
 src/adapters/geo/osrm_client.py                 | NEW — OSRM httpx client
 src/adapters/geo/access_refresh.py              | NEW — DB refresh orchestrator
 src/adapters/queue/tasks.py                     | tasks.refresh_neighbourhood_access
 src/adapters/queue/celery_app.py                | task_routes + beat entry
 src/api/admin.py                                | POST /admin/neighbourhoods/access/refresh
 scripts/dev/refresh_neighbourhood_access.py     | NEW — one-shot CLI
 src/tests/unit/test_neighbourhood_access.py     | NEW — domain score/meta tests
 src/tests/unit/test_osrm_client.py              | NEW — mocked OSRM HTTP
 src/tests/unit/test_config.py                   | neighbourhood_access config coverage
 src/tests/unit/test_schedule.py                 | route + beat assertions
 src/tests/integration/test_neighbourhood_access.py | NEW — DB write + API read
 _bmad-output/implementation-artifacts/sprint-status.yaml | 6-5 → done
 docs/features/68-access-travel-time-hubs.md     | NEW — this doc
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
```

Manual one-shot (haversine when `base_url` empty):

```bash
PYTHONPATH=src python scripts/dev/refresh_neighbourhood_access.py
```

Optional: set `neighbourhood_access.base_url` to a self-hosted OSRM root and re-run.

## Notes / Follow-ups

- No Compose OSRM service in this ticket — point `base_url` when an operator runs OSRM/Valhalla locally.
- City matching is case-insensitive against `neighborhoods.city`; hubs must be configured for that city name.
- Related: BIN-86 schema/API; BIN-85 epic fills (amenity/transit/curated) also write `quality_meta` siblings.
