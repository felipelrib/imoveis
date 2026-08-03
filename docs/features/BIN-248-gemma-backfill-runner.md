# Gemma free-tier enrichment backfill — resumable RPD-aware runner + backend wiring

> Feature branch: `feat/bin-248-gemma-backfill-runner` · Linear: `BIN-248` · Status: implemented

## Problem

BIN-242 proved **Gemma 4 31B (free tier) + 768px image downscaling** is the best-quality AI-enrichment
option (0 failures, discriminating output, $0). But productionizing it against the existing pipeline is a
mismatch: the `ai_enrich` Celery path acquires a **GPU semaphore** per call, assuming a local, unlimited,
GPU-bound backend. Free-tier Gemma is instead a **remote, RPD-capped** provider — ~14,400 requests/day
and 16K TPM — so a full ~26k-property backfill (×3 requests each) takes **~6 days** and must pace on the
API budget, run across days, and survive stop/restart. It also must not fight the live scrape/enrich
workers.

## Approach

- **Live workers stay on Ollama; the runner is the only Gemma consumer.** The global `ai.backend` stays
  `ollama`. The backfill runner builds a Gemma client **explicitly** (`_gemini_client_for(cfg.ai.gemma_model, …)`),
  independent of the global flag. This *is* the coordination mechanism — the GPU-bound `ai_enrich` and the
  RPD-paced backfill never contend for the same resource. `backend: gemma` is *also* wired into
  `create_ai_client()` so an operator can opt the whole pipeline over, but the runner doesn't depend on it.
- **Semaphore bypass by construction.** The runner calls the shared `run_enrichment()` orchestration
  **directly** (extracted from the `ai_enrich` task closure), never the task wrapper where the
  `GPUSemaphore` acquire lives. It paces on a Redis-backed daily request budget instead.
- **Resumable + idempotent.** A per-UTC-day budget counter (`DailyBudget`) stops the run at the ceiling; a
  Redis checkpoint records the last property + running total. `mode=missing` selection (reusing
  `fetch_candidate_rows`) plus a `force`-gated skip of already-scored rows make re-invocation safe — no
  double-processing if a live worker enriched a row in between.
- **Downscaling helps both backends.** 768px capping lives in `_read_image_b64` (shared by every client),
  so it benefits Ollama *and* Gemma; the downscaled variant is cached on disk next to the original. The
  step is fail-open: a bad image falls back to the original bytes rather than breaking a run.
- **Pacing.** Default inter-property sleep spreads the daily budget evenly across 24h, which keeps the run
  well under the free-tier 30 RPM as well as the RPD cap (`--min-interval` overrides).
- **Standalone CLI, not a beat job** (chosen with the user): simplest to operate, unit-test, and
  pause/resume; the operator controls when it runs.

## Changes

Files touched:

```
 src/infra/config.py                        | AIConfig.gemma_model + image_max_dimension; new BackfillConfig on AppConfig
 src/adapters/ai/client.py                  | create_ai_client() handles backend: gemma; _read_image_b64 downscales + caches
 src/adapters/ai/image_ops.py               | NEW — pure downscale_jpeg / variant_path helpers (fail-open)
 src/adapters/queue/tasks.py                | Extracted run_enrichment() (semaphore-free); ai_enrich delegates to it
 src/core/backfill_runner.py                | NEW — DailyBudget, Checkpoint, Heartbeat, run_backfill (pure, injectable)
 scripts/dev/backfill_gemma.py              | NEW — CLI runner: --limit/--dry-run/--force/--daily-budget/--status
 configs/app_config.yaml                    | ai.gemma_model + image_max_dimension; new backfill: section
 requirements.in / requirements.txt         | add Pillow
 src/tests/unit/test_image_ops.py           | NEW — downscale unit tests
 src/tests/unit/test_backfill_runner.py     | NEW — budget/resume/idempotency/dry-run/pacing tests
 src/tests/unit/test_ai_client.py           | + backend: gemma routing + _read_image_b64 downscale tests
 src/tests/unit/test_config.py              | + gemma_model / image_max_dimension / backfill defaults
```

## New Dependencies

- **Pillow** (`pillow`) — image downscaling before the VLM call. Added to `requirements.in` /
  `requirements.txt`.

## How to Test

1. Automated (CI-safe, no network):
   ```bash
   bash scripts/agent/validate.sh all
   ```
   Pure unit tests cover downscaling (`test_image_ops.py`) and the budget/resume/idempotency/dry-run/pacing
   loop (`test_backfill_runner.py`); the `ai_enrich` stage tests characterize the `run_enrichment`
   extraction.
2. AI-client surface changed → run the AI gate (needs Ollama reachable):
   ```bash
   bash scripts/agent/validate-ai.sh
   ```
3. Operator dry-run / trial (needs a real key + populated DB — **not** CI):
   ```bash
   PYTHONPATH=src python scripts/dev/backfill_gemma.py --dry-run          # plan only
   GEMINI_API_KEY=… PYTHONPATH=src python scripts/dev/backfill_gemma.py --limit 2   # real 2-prop trial
   PYTHONPATH=src python scripts/dev/backfill_gemma.py --status           # enriched/total + budget + ETA
   ```
   The trial writes real Gemma visual/sentiment/verdict into `MetricsScoring.meta` with 768px images.

## Notes / Follow-ups

- **Budget accounting is conservative:** the runner reserves a fixed `requests_per_property` (3) up-front
  per property. Retries (on 429/5xx) issue extra HTTP requests not counted against the daily budget; at the
  paced rate the A/B observed 0 retries, and `--status` / progress logs surface `rate_limit_hits` /
  `retry_count` so drift is visible. Default budget (14,000) sits under the 14,400 RPD cap for headroom.
- **Day boundary is UTC**, which may not align exactly with the provider's RPD reset (Pacific). The default
  budget margin absorbs the small overlap; confirm live RPD on the AI Studio dashboard before raising it.
- Embeddings stay on local `bge-m3` (out of scope). No schema change — enrichment writes to the existing
  `metrics_scoring.meta` JSON.
- Actually running the full ~6-day backfill is an operator action (daily invocation), not part of this PR.
- Related: `BIN-242` (spike, Done), `BIN-243` (empty-descriptions sentiment gap, already handled by
  `neutral_sentiment_no_description`).
