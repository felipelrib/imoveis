# Reliability follow-ups: embed semaphore, gpu-scale bound, zapimoveis checkpoint, per-run checkpoint write

> Feature branch: `feat/bin-159-reliability-follow-ups` · Linear: `BIN-159` · Status: implemented

## Problem

Four low-severity reliability items from the 2026-07-29 tech-debt audit (scrapers/AI lane), bundled like [BIN-143](https://linear.app/felipelrib/issue/BIN-143):

1. **`embed_property` bypassed the GPU semaphore.** `ai_enrich` gates its Ollama calls through `GPUSemaphore`, but `embed_property` called `client.embed()` against the same backend with no gating. Masked today by `worker_ai --concurrency=2`, but scaling replicas/concurrency would reintroduce unmetered concurrent GPU calls.
2. **`/admin/gpu/scale` had no upper bound.** `GPUScaleRequest.limit` accepted any int, so an operator could scale the semaphore past what the Ollama server (`OLLAMA_NUM_PARALLEL`) can actually serve — or to 0/negative, wedging the semaphore.
3. **`CheckpointStore.CHECKPOINT_MODELS` was missing `zapimoveis`.** OLX/QuintoAndar checkpoints get validated and reset-to-fresh on corruption; zapimoveis fell through as a raw dict with no such protection.
4. **Per-item checkpoint write was a no-op.** `scrape_listings` re-persisted an identical `cp` dict via `store.set(...)` after *every* processed listing. The price-funnel scrapers never mutate `cp` mid-run (they only read it in `fetch_pages`), so this was a needless DB write+commit per item, and the "resume mid-run" docstring never held.

## Approach

1. Acquire/release `GPUSemaphore` around `embed_property`'s work, mirroring `ai_enrich` (acquire before the `try`, release in `finally`, retry on busy). New `EMBED_GPU_SLOT_TTL_SECONDS = 180` — generous for a single embed, short vs. VLM enrichment.
2. `GPUScaleRequest.limit` gets `Field(ge=1)` (schema-level lower bound → 422); the handler rejects `limit > cfg.gpu.max_semaphore_limit` with HTTP 400. New config `gpu.max_semaphore_limit` (default 8) in `config.py` + `app_config.yaml`.
3. New `ZapImoveisCheckpoint` model (`scrape_type`, `processed_ids`) registered in `CHECKPOINT_MODELS`. Preserves current behavior (validated `scrape_type` still read by the scraper) while adding reset-on-corruption parity.
4. Moved `store.set(platform_name, cp)` out of the per-item loop to run **once** after the run, so any caller-supplied `checkpoint` override is still recorded without per-item writes.

## Changes

Files touched:

```
 src/adapters/queue/tasks.py                    | embed_property GPU semaphore + EMBED_GPU_SLOT_TTL; checkpoint store.set once per run
 src/api/admin.py                               | GPUScaleRequest ge=1; /gpu/scale rejects > max_semaphore_limit
 src/infra/config.py                            | GPUConfig.max_semaphore_limit (default 8)
 configs/app_config.yaml                        | gpu.max_semaphore_limit: 8
 src/adapters/scrapers/checkpoint_store.py      | ZapImoveisCheckpoint model + registry entry
 src/tests/unit/test_bin159_reliability.py      | NEW — items 1,2,4 (semaphore, gpu-scale bound, checkpoint-once)
 src/tests/unit/test_checkpoint_store.py        | zapimoveis validate/reset tests (item 3)
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh backend
```

Unit coverage: `embed_property` acquires+releases the semaphore and retries when busy; `/gpu/scale` rejects over-ceiling (400) and zero/negative (422) and accepts within-ceiling; a two-item scrape persists the checkpoint exactly once; zapimoveis checkpoints validate and reset-to-empty on corruption.

## Notes / Follow-ups

- Holding the semaphore across `embed_property`'s (fast) DB read/write mirrors `ai_enrich`; acceptable given embeds are quick. If embed throughput ever matters, narrow the hold to just the `client.embed()` call.
- OLX/QuintoAndar checkpoint models still omit `scrape_type` (a latent quirk where a persisted `scrape_type` would be stripped on `get()`); left as-is — out of scope for this bundle.
- Part of epic [BIN-128](https://linear.app/felipelrib/issue/BIN-128) (v0.10 — Technical debt remediation).
