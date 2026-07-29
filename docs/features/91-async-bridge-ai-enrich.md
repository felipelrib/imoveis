# async-bridge-ai-enrich — Shared event-loop bridge for sync Celery AI tasks

> Feature branch: `feat/bin-122-replace-asyncio-run-ai-enrich` · Linear: `BIN-122` · Status: implemented

## Problem

`ai_enrich` (and `embed_property`) are sync Celery tasks that call async httpx/Ollama
clients via `asyncio.run(...)`. Each invocation creates and closes a fresh event loop —
safe but wasteful under prefork `worker_ai --concurrency=2`.

## Approach

- Add `adapters.queue.async_bridge.run_coro`: thread-local persistent event loop.
- Reuse the loop across sequential tasks on the same worker thread; never close after
  each call (unlike `asyncio.run`).
- Fail loud if called while a loop is already running (no nested bridging).
- Keep GPU semaphore acquire/release **outside** the coro — concurrency semantics
  unchanged.
- Prefer this over async Celery / gevent to avoid worker-pool and compose churn.

## Changes

Files touched:

```
 src/adapters/queue/async_bridge.py           | NEW — thread-local run_coro bridge
 src/adapters/queue/tasks.py                  | ai_enrich + embed_property use run_coro
 src/tests/unit/test_async_bridge.py          | NEW — loop reuse, error recovery, nest reject
 src/tests/unit/test_ai_enrich_stages.py      | sequential GPU acquire/release 1:1 smoke
 docs/features/13-image-store-and-vlm-pipeline.md | mark asyncio.run follow-up done
```

## New Dependencies

None.

## How to Test

1. Unit gate:
   ```bash
   bash scripts/agent/validate.sh fast
   ```
2. Optional live AI / VRAM concurrency (host Ollama):
   ```bash
   bash scripts/agent/validate-ai.sh
   PYTHONPATH=src python scripts/dev/bench_ollama_vram.py --cases A,D
   ```
   Confirm dual-property case still respects `gpu.semaphore_limit`.

## Notes / Follow-ups

- FastAPI `properties.py` embed query and `core.olx_location` still use `asyncio.run` —
  out of BIN-122 scope; can adopt `run_coro` later if those hot paths matter.
- Closing the thread-local loop on worker shutdown is not required for prefork workers
  (process exit tears it down).
