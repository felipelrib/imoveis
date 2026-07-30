# Fix GPU semaphore TTL/timeout conflation — decouple held-slot TTL from caller wait-intent

> Feature branch: `fix/gpu-semaphore-ttl-conflation` · Linear: `BIN-147` · Status: implemented

## Problem

`GPUSemaphore.acquire()` (`src/adapters/queue/gpu_semaphore.py`) set
`pipe.setex(f"semaphore:{name}", timeout or 3600, current_value - 1)`. The only call
site, `src/adapters/queue/tasks.py`'s `ai_enrich` task, passed `sem.acquire(timeout=30)`
intending 30s as a wait bound — but `acquire()` is a one-shot check-and-decrement with no
retry/wait loop, so `timeout` never meant "how long the caller is willing to wait." It
just happened to feed straight into the Redis key's TTL for the "held slot" marker.

`analyze_visual_and_sentiment` (`enrich_pipeline.py`) runs the VLM and text/sentiment
Ollama calls sequentially, each bounded by `cfg.ai.timeout` (120s default) with up to 3
JSON-retry attempts, plus image download time for up to `cfg.ai.max_images_per_property`
(8) images. This routinely runs well past 30 seconds. When it did, the Redis TTL expired
mid-task, `GPUSemaphore.available` silently reported the slot free again, and another
`ai_enrich` task could acquire it — oversubscribing the GPU exactly as the
`OLLAMA_NUM_PARALLEL`/`gpu.semaphore_limit` invariant in `CLAUDE.md` warns against (VRAM
spills into system RAM on ~20GB cards).

## Approach

- Added an explicit `slot_ttl` keyword-only argument to `GPUSemaphore.acquire()`,
  decoupled from `timeout`. `timeout` is kept for the caller's wait-intent /
  retry-countdown documentation and backward compatibility, but is **no longer** used to
  compute the Redis `SETEX` TTL. `slot_ttl` defaults to the pre-existing
  `DEFAULT_SLOT_TTL_SECONDS` (3600s) when not supplied, so callers that don't opt in keep
  their prior (already generous) behavior.
- `tasks.ai_enrich` now declares explicit Celery `time_limit` /
  `soft_time_limit` (`AI_ENRICH_TIME_LIMIT_SECONDS` = 600s hard,
  `AI_ENRICH_SOFT_TIME_LIMIT_SECONDS` = 570s soft) — neither existed before this fix.
  `soft_time_limit` raises `SoftTimeLimitExceeded` inside the task so the existing
  `finally: sem.release()` still runs in the common case; `time_limit` is Celery's hard
  SIGKILL backstop on the worker child process, which bypasses Python exception handling
  entirely (no `finally` runs).
- The call site now passes `sem.acquire(timeout=30, slot_ttl=AI_ENRICH_GPU_SLOT_TTL_SECONDS)`
  where `AI_ENRICH_GPU_SLOT_TTL_SECONDS = AI_ENRICH_TIME_LIMIT_SECONDS + 60`
  — a TTL that always exceeds the task's own hard kill, so the "held slot" marker cannot
  expire before the task finishes normally or is hard-killed by Celery.
- Left `release()` and `scale()` untouched — this fix is scoped to the `acquire()` TTL
  conflation the ticket identified. `embed_property` (a sibling task that doesn't call
  the semaphore at all today) is explicitly out of scope — tracked separately as BIN-159,
  which was blocked on this ticket landing first to avoid a merge conflict on the same
  call site area.

## Changes

Files touched:

```
src/adapters/queue/gpu_semaphore.py | acquire() gains slot_ttl kwarg; SETEX TTL now
                                     | sourced from slot_ttl (default DEFAULT_SLOT_TTL_
                                     | SECONDS), never from timeout
src/adapters/queue/tasks.py         | ai_enrich: declares time_limit/soft_time_limit;
                                     | new AI_ENRICH_TIME_LIMIT_SECONDS / _SOFT_ /
                                     | AI_ENRICH_GPU_SLOT_TTL_SECONDS constants; call
                                     | site passes slot_ttl derived from the hard limit
src/tests/unit/test_gpu_semaphore.py | NEW regression tests: TTL sourced from slot_ttl
                                     | not timeout, default-TTL fallback, a TTL-decay
                                     | fake Redis proving a long-running acquire
                                     | survives past the old 30s window, and a wiring
                                     | check tying tasks.ai_enrich's Celery time limits
                                     | to the semaphore's slot_ttl
frontend/tests/e2e/compare-map-select.spec.js | unrelated stabilization: raised
                                     | waitForMapCompareHits assertion timeouts (20s/10s
                                     | -> 45s/20s) and per-test timeout (default 30s ->
                                     | 90s) — this pre-existing MapLibre e2e spec was
                                     | flaking under full-suite CPU contention and
                                     | blocking validate.sh's e2e gate for this ticket
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
```

Targeted:

```bash
PYTHONPATH=src pytest src/tests/unit/test_gpu_semaphore.py -v
```

Manual/characterization check of the fix's premise: with the old code,
`sem.acquire(timeout=30)` set a 30s Redis TTL on `semaphore:gpu`; a task still running at
31s would have its slot silently freed. With this fix, `slot_ttl=660` (10 min hard limit
+ 60s margin) keeps the marker held for the task's entire realistic runtime.

## Notes / Follow-ups

- Tracked as part of the BIN-128 tech-debt remediation epic (v0.10 milestone).
- Related: BIN-143 ("fail-open semaphore" — a distinct concern, Redis-unreachable
  behavior, left unchanged here). BIN-129/130/133 previously touched the same file for
  Celery beat/logging fixes; confirmed this ticket's target lines were still present
  post-merge.
- BIN-159 (embed_property semaphore bypass, unbounded `/admin/gpu/scale`, zapimoveis
  checkpoint gap) was deliberately blocked on this ticket to avoid a merge conflict on
  `tasks.py`'s GPU-semaphore call-site area — it can proceed once this PR merges.
- `AI_ENRICH_TIME_LIMIT_SECONDS` (600s) is a judgment-call estimate (VLM + text
  sequential calls, each up to `cfg.ai.timeout` x 3 JSON-retry attempts, plus image
  downloads) rather than a value derived from production telemetry — if real-world
  `ai_enrich` durations approach it, revisit alongside `pipeline:ai:telemetry` data.
