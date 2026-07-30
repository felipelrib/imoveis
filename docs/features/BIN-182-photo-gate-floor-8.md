# Raise photo gate + VLM analyze budget to 8 — BIN-78 follow-up

> Feature branch: `feat/bin-78-photo-floor-8` · Linear: `BIN-182` · Status: implemented

## Problem

The initial photo gate floor of 3 (and VLM analyze cap of 5) was too thin for whole-home condition scoring — three photos often miss rooms and features.

## Approach

- Raise ingest floor to **8** (`scraping.photo_gate.floor_min`) and set `coverage_ratio: 1.0` so the gate tracks a full VLM budget.
- Raise `ai.max_images_per_property` to **8** so enrichment sends up to eight photos.
- Raise `ai.num_ctx` to **16384** so eight images fit the local qwen2.5vl context window (drop to 8192 if OOM).
- Re-run `deactivate_low_photo_properties.py --apply` on local DB after deploy.

## Changes

Files touched:

```
 configs/app_config.yaml                         | floor_min=8, coverage=1.0, max_images=8, num_ctx=16384
 src/infra/config.py                             | matching pydantic defaults
 src/core/photo_gate.py                          | default heuristic args → 8 / 1.0
 src/adapters/ai/image_store.py                  | download default max_images=8
 src/tests/unit/test_photo_gate.py               | expectations for 8-photo gate
 src/tests/unit/test_enrich_missing.py           | enough-gallery fixture size
 src/tests/unit/test_scrape_listings_pipeline.py | happy-path 8 URLs
 src/tests/unit/test_scrape_run_telemetry.py     | happy-path 8 URLs
 src/tests/unit/test_config.py                   | default assertions
 docs/features/BIN-182-photo-gate-floor-8.md          | NEW — this doc
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh backend
PYTHONPATH=src python scripts/dev/deactivate_low_photo_properties.py --apply
```

## Notes / Follow-ups

- If OOM or timeouts appear on enrichment, lower `num_ctx` / `max_images_per_property` or raise `ai.timeout`.
- Related: `docs/features/BIN-78-min-photo-count-gate.md` (original gate).
