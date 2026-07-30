# Minimum photo count gate for AI scoring — BIN-78

> Feature branch: `feat/bin-78-min-photo-filter` · Linear: `BIN-78` · Status: implemented

## Problem

Thin listing galleries (0–2 photos) produce incomplete VLM condition scores. Those properties still polluted the deal feed and wasted GPU on unreliable AI enrichment.

## Approach

- Dynamic threshold: `effective_min = max(floor_min, ceil(ai.max_images_per_property * coverage_ratio))`.
- Defaults (`floor_min=3`, `coverage_ratio=0.6`, stock `max_images_per_property=5`) → **3 photos**. Raising the VLM budget automatically raises the bar.
- Optional hard override via `scraping.photo_gate.min_photos`.
- Under-threshold rows are **persisted with `active=false`** (kept for offline price/geo analysis) and skip `ai_enrich`; text embed may still run.
- Idempotent backfill: `scripts/dev/deactivate_low_photo_properties.py` (dry-run by default; `--apply` / `--reactivate`).

## Changes

Files touched:

```
 configs/app_config.yaml                              | ADD scraping.photo_gate block
 src/infra/config.py                                  | ADD PhotoGateConfig on ScrapingConfig
 src/core/photo_gate.py                               | NEW — heuristic + passes_photo_gate
 src/adapters/queue/tasks.py                          | Wire gate after geo; deactivate + skip AI
 src/api/admin.py                                     | enrich_missing respects photo gate
 scripts/dev/deactivate_low_photo_properties.py       | NEW — dry-run / apply backfill
 src/tests/unit/test_photo_gate.py                    | NEW — unit coverage
 src/tests/unit/test_enrich_missing.py                | Assert too-few-photos skip
 src/tests/unit/test_scrape_listings_pipeline.py      | Thin-gallery deactivation path
 src/tests/unit/test_scrape_run_telemetry.py          | Enough photos for happy path
 src/tests/unit/test_config.py                        | Default photo_gate assertions
 docs/features/BIN-78-min-photo-count-gate.md             | NEW — this doc
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh backend
PYTHONPATH=src python scripts/dev/deactivate_low_photo_properties.py
PYTHONPATH=src python scripts/dev/deactivate_low_photo_properties.py --apply
```

## Notes / Follow-ups

- Live statistical cohorts (`metrics_scoring`) still filter `active=true`; inactive thin galleries remain queryable for offline analysis.
- If live price cohorts should include inactive rows, that is a separate scoring change.
- Related: geo purge script `scripts/dev/purge_out_of_geo_properties.py` (hard delete); photo gate prefers soft deactivate.
