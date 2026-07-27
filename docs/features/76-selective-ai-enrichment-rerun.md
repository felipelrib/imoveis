# selective-ai-enrichment-rerun — Operator controls to re-run AI enrichment selectively

> Feature branch: `feat/bin-95-selective-ai-enrichment-rerun` · Linear: `BIN-95` · Status: implemented

## Problem

Operators could only backfill AI via **Enrich Missing** (`ai_score` NULL/0). After prompt,
model, or verdict-input changes (including neighbourhood profiles feeding the deal
verdict), there was no force-refresh, no city/platform filters, no dry-run count, and no
verdict-only path — only wipe-and-rerun or hand-queueing Celery tasks.

## Approach

- Add `POST /admin/enrichment/rerun` with `mode` (`missing` | `force` | `stale_before`),
  filters (city, neighbourhood_ids, platform, limit, active_only), `stages`
  (`all` | `visual+sentiment` | `verdict_only`), and `dry_run`.
- Keep `POST /admin/enrichment/missing` as a thin wrapper (`mode=missing`) for the
  one-click Dashboard button.
- Teach `tasks.ai_enrich` a `stages` kwarg; stamp `meta.enriched_at` on success for
  stale detection. `verdict_only` skips VLM/image download and reuses existing
  visual/sentiment meta.
- Point `/admin/verdict/recompute` at `verdict_only` (was accidentally full VLM).
- Dashboard panel under Quick Actions for selective re-run; document
  **recalculate vs AI re-run** (geo/weights → recalculate; prompt/verdict → AI re-run).
- Never clear existing scores on enqueue failure; GPU semaphore stays runtime-only;
  photo gate applies to visual stages at enqueue.

## Changes

Files touched:

```
 src/core/enrichment_rerun.py                      | NEW — candidate selection + enqueue loop
 src/api/admin.py                                  | NEW /enrichment/rerun; wrap missing; fix verdict/recompute
 src/adapters/queue/tasks.py                       | stages kwarg + enriched_at + helpers
 src/tests/unit/test_enrichment_rerun.py           | NEW — modes, filters, dry-run, API
 src/tests/unit/test_enrich_missing.py             | UPDATED — stages kwargs on apply_async
 src/tests/unit/test_ai_enrich_stages.py           | NEW — verdict_only / visual+sentiment branching
 frontend/src/api.js                               | NEW enrichmentRerun()
 frontend/src/pages/Dashboard.jsx                  | AI Enrichment re-run panel
 frontend/tests/e2e/dashboard.spec.js              | dry-run + force mode e2e
 docs/features/76-selective-ai-enrichment-rerun.md | NEW — this note
 docs/features/54-enrich-missing.md                | cross-link recalculate vs AI re-run
 docs/features/75-blend-neighbourhood-profiles-scoring-ui.md | point at this feature
 _bmad-output/implementation-artifacts/sprint-status.yaml | 6-10 → done
```

## New Dependencies

None.

## How to Test

1. Open Dashboard → **AI Enrichment re-run** panel.
2. Set mode **Force**, click **Dry-run** — confirm `would_queue` without Celery growth.
3. Run with a small **Limit** and watch the `ai` queue; scores must not be wiped if enqueue fails.
4. After curated YAML / OSM profile updates, use **Recalculate All Scores** (not AI re-run).
5. After prompt or verdict changes, use this panel (optionally `verdict_only`).
6. Automated:
   ```bash
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- `stale_before` uses `meta.enriched_at` (ISO UTC). Rows without the stamp are treated as stale.
- `verdict_only` skips candidates missing prior visual+sentiment meta
  (`skipped_missing_prior_enrichment`).
- Related: BIN-54 enrich-missing, BIN-94 blend profiles, BIN-85 epic close after this story.
