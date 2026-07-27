# AI enrichment RAM / concurrency tuning — stop VRAM→system-RAM spill

> Feature branch: `ai/enrich-ram-tune` · Linear: n/a · Status: implemented

## Problem

On an AMD RX 7900 XT (20 GB VRAM), AI enrichment was spilling model KV cache into system RAM (“GPU→CPU leak”), pushing host memory toward ~20 GB and thrashing. Host Ollama had `OLLAMA_NUM_PARALLEL=10` with 16k context, and each `ai_enrich` task ran visual + text generates via `asyncio.gather` — two concurrent Ollama requests under a single Celery GPU semaphore slot.

## Approach

- Cap Windows Ollama to **`OLLAMA_NUM_PARALLEL=2`** (aligned with app concurrency), bind `OLLAMA_HOST=0.0.0.0:11434` for Docker/WSL, shorten keep-alive to `30m`.
- Serialize visual → text → verdict inside `ai_enrich` so one semaphore slot = one in-flight generate.
- Raise measured-safe concurrency to **2**: `gpu.semaphore_limit` + `worker_ai --concurrency=2`, keep `num_ctx=16384` / 8 images (case A ~6 GB VRAM, case D dual-property ~7 GB, **0 spill**).
- Add `scripts/dev/bench_ollama_vram.py` to re-measure against real local listings (read-only DB).

## Changes

Files touched:

```
 configs/app_config.yaml                       | gpu.semaphore_limit: 2 + comment
 docker-compose.yml                            | worker_ai --concurrency=2
 src/infra/config.py                           | GPUConfig.semaphore_limit default 2
 src/adapters/ai/enrich_pipeline.py            | NEW — serial visual→text helper
 src/adapters/queue/tasks.py                   | use enrich_pipeline; GPUSemaphore(max_concurrent=cfg…)
 src/api/admin.py                              | GPU scale uses config default limit
 src/tests/unit/test_ai_enrich_serial.py       | NEW — peak in-flight generates == 1
 src/tests/unit/test_config.py                 | empty-YAML default semaphore 2
 scripts/dev/bench_ollama_vram.py              | NEW — A/B/C/D VRAM matrix on real properties
 scripts/agent/validate-ai.sh                  | prefer .venv python; PYTHONPATH
 src/tests/unit/test_ai_quality.py             | fix stale CONDITION_ANALYSIS_PROMPT; ±0.20 tolerance
 docs/setup.md                                 | Ollama Windows env + AI worker guidance
 docs/architecture.md                          | ai queue concurrency note
 docs/features/66-ai-enrich-ram-concurrency.md | NEW — this doc
 mkdocs.yml                                    | nav link
 .gitignore                                    | data/bench/
```

## New Dependencies

None (bench uses existing `httpx` / `psycopg2`).

## How to Test

1. Host Ollama env (Windows User variables), then restart `ollama serve`:

   | Variable | Recommended |
   |---|---|
   | `OLLAMA_NUM_PARALLEL` | `2` (must match `gpu.semaphore_limit`) |
   | `OLLAMA_CONTEXT_LENGTH` | `16384` (match `ai.num_ctx`) |
   | `OLLAMA_KEEP_ALIVE` | `30m` |
   | `OLLAMA_MAX_LOADED_MODELS` | `2` |
   | `OLLAMA_HOST` | `http://0.0.0.0:11434` |

2. VRAM bench (read-only; needs Ollama + Postgres with listings):

   ```bash
   export DATABASE_URL=postgresql://imoveis:imoveis_local_dev@127.0.0.1:5433/realestate
   PYTHONPATH=src python scripts/dev/bench_ollama_vram.py --cases A,D
   ```

3. Unit / AI gates:

   ```bash
   bash scripts/agent/validate.sh fast
   bash scripts/agent/validate-ai.sh
   ```

## Notes / Follow-ups

- Measured peaks (RX 7900 XT, `qwen2.5vl:7b` Q4, 8 images): A ≈ 6.1 GB VRAM; D (2 props) ≈ 7.0 GB; spill 0. Do not raise `OLLAMA_NUM_PARALLEL` above `gpu.semaphore_limit`.
- If OOM returns after model upgrades, drop `ai.num_ctx` to 8192 and/or `semaphore_limit` to 1, then re-run the bench.
- Related: `docs/features/52-ai-qwen-vl-bge-m3.md`, `docs/features/60-photo-gate-floor-8.md`.
