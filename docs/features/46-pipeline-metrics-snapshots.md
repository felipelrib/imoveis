# pipeline-metrics-snapshots — Persist pipeline metrics for Dashboard consultation

> Feature branch: `feat/bin-61-pipeline-metrics-snapshots` · Linear: `BIN-61` · Status: implemented

## Problem

Pipeline Metrics charts were built only in browser `useState` from live polls.
A refresh wiped history. Redis telemetry lists are capped and not meant for
durable consultation. Operators could not review throughput / queue depth over
the last hour after navigating away.

## Approach

- Persist periodic snapshots in Postgres (`pipeline_metric_snapshots`).
- Celery beat task every 30s (configurable) samples the same sources as
  `GET /system/pipeline` plus property counts, then prunes rows older than
  7 days.
- `GET /system/pipeline/history?minutes=60` serves the series.
- Dashboard loads history on mount, then continues live polling for the tip.

## Changes

Files touched:

```
 alembic/versions/a2b3c4d5e6f7_add_pipeline_metric_snapshots.py | NEW migration
 src/adapters/db/models.py                                     | PipelineMetricSnapshot ORM
 src/adapters/metrics/pipeline_snapshots.py                    | NEW collect/write/prune/list
 src/adapters/queue/celery_app.py                              | beat entry snapshot-pipeline-metrics
 src/adapters/queue/tasks.py                                   | tasks.snapshot_pipeline_metrics
 src/infra/config.py / configs/app_config.yaml                 | pipeline_metrics section
 src/api/system.py / schemas.py                                | GET /system/pipeline/history
 frontend/src/api.js / pages/Dashboard.jsx                     | load history into charts
 src/tests/unit/test_pipeline_metric_snapshots.py              | NEW unit tests
 docs/features/46-pipeline-metrics-snapshots.md                | NEW — this doc
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
```

Manual:

1. Start stack with beat worker running.
2. Wait ~1 minute, then `curl localhost:8000/system/pipeline/history?minutes=60`
   should return growing `points`.
3. Refresh Dashboard — charts should populate without waiting for multiple live polls.

## Notes / Follow-ups

- Related: BIN-60 (false-zero property counts / volume footguns).
- v1 uses plain Postgres rows (no Timescale/Prometheus).
