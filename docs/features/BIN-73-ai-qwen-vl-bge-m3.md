# AI stack — qwen2.5vl:7b + bge-m3 + num_ctx

> Feature branch: `ai/qwen-vl-bge-m3` · Linear: `BIN-73` · Status: implemented

## Problem

Running separate `llava` (vision) + `llama3` (text) models doubles VRAM pressure. Embeddings used English-centric `nomic-embed-text` at 768-d. Context window was left to Ollama defaults, which can over-allocate KV cache on a ~15–17GB free VRAM budget.

## Approach

- One generative VLM for photos **and** text JSON: `qwen2.5vl:7b` as both `visual_model` and `text_model`.
- Multilingual embeddings: `bge-m3` (1024-d); migrate pgvector column and re-embed.
- Configure Ollama `options.num_ctx=8192` (and `num_predict` from `max_tokens`) on every generate call — enough for listing prompts + images without saturating a 7950/7900-class card with ~15–17GB free.

## Changes

Files touched:

```
 configs/app_config.yaml                                      | qwen2.5vl:7b, bge-m3, num_ctx: 8192
 src/infra/config.py                                          | AIConfig.num_ctx + AI_NUM_CTX env
 src/adapters/ai/client.py                                    | Pass options.num_ctx / num_predict
 src/adapters/db/models.py                                    | Vector(1024)
 alembic/versions/c8d9e0f1a2b3_resize_property_embedding_1024.py | NEW — recreate embedding column
 src/api/admin.py                                             | backfill?force=true
 scripts/dev/reembed_properties.py                            | NEW — CLI re-embed
 docker-compose.yml                                           | ollama_init pulls new models
 src/tests/...                                                | 1024-d fixtures, num_ctx assertion
 docs/features/BIN-73-ai-qwen-vl-bge-m3.md                        | NEW — this doc
```

## New Dependencies

Runtime Ollama models (not pip): `qwen2.5vl:7b`, `bge-m3`.

## How to Test

1. `bash scripts/agent/validate.sh all`
2. `bash scripts/agent/validate-ai.sh` (needs Ollama)
3. After merge / migrate:
   ```bash
   docker compose --env-file .env.local build api worker_ai worker_scraper
   docker compose --env-file .env.local up -d
   PYTHONPATH=src python scripts/dev/reembed_properties.py --apply
   # or: curl -X POST -H "X-API-Key: $API_KEY" \
   #   'http://localhost:8000/admin/embeddings/backfill?force=true'
   ```

## Notes / Follow-ups

- Raise `ai.num_ctx` to 16384 only if VRAM headroom remains after loading `qwen2.5vl:7b` + `bge-m3`.
- `llama3.2-vision` returned HTTP 500 on this host during evaluation — do not switch to it without fixing AMD/Windows Ollama support.
- Related: BIN-18 / `docs/features/BIN-18-semantic-search.md` (original 768-d nomic path).
