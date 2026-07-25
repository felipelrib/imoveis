# enrich-missing — Dashboard button to queue AI enrichment for unenriched properties

> Feature branch: `feat/enrich-missing-button` · Linear: n/a · Status: implemented

## Problem

Many scraped properties never receive AI enrichment when scrapes noop them or workers
were paused. Operators could see a low “AI Enriched” rate on the Dashboard but had no
one-click way to backfill — only re-scrape (which skips unchanged listings) or manual
Celery enqueue. “Recalculate All Scores” only recomputes stat/combined math and does
not run VLM/LLM enrichment.

## Approach

- Add authenticated `POST /admin/enrichment/missing` that finds active properties with
  no usable AI score (`metrics_scoring` missing, or `ai_score` NULL/0 — same semantics
  as Dashboard `enriched_properties`) and enqueues `ai_enrich` on the `ai` queue.
- Skip candidates without image URLs (same gate as post-scrape `_enqueue_post_scrape_jobs`).
- Surface an **Enrich Missing** Quick Action on the Dashboard next to Recalculate.

## Changes

Files touched:

```
 src/api/admin.py                                 | NEW endpoint POST /admin/enrichment/missing
 src/tests/unit/test_enrich_missing.py            | NEW — queues only unenriched+images; auth required
 frontend/src/api.js                              | NEW enrichMissing()
 frontend/src/pages/Dashboard.jsx                 | Enrich Missing button + result banner
 frontend/tests/e2e/dashboard.spec.js             | NEW e2e for Quick Action POST
 docs/features/54-enrich-missing.md               | NEW — this note
```

## New Dependencies

None.

## How to Test

1. Ensure API key is set in the SPA credential gate and AI workers are running (not paused).
2. Open Dashboard → Quick Actions → **Enrich Missing**.
3. Confirm toast/result shows queued count; Celery `ai` queue depth rises; Dashboard
   “AI Enriched” increases as tasks complete.
4. Automated:
   ```bash
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- Properties without images are counted in `skipped_no_images` and are not queued.
- Large backfills can saturate a single GPU for a long time; pause workers or scale GPU
  if needed via Scraper Control.
- Recalculate All Scores remains useful after enrichment and as the neighbourhood cohort
  grows (stat z-scores / percentiles become more stable with more peers).
