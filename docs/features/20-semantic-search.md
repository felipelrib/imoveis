# semantic-search — Free-text search via embeddings

> Feature branch: `feat/semantic-search` · Linear: `BIN-18` · Status: implemented

## Problem

Property discovery was limited to structured filters (price, beds, neighbourhood). Users could not search by natural language over titles/descriptions (e.g. "apto perto do metrô com varanda").

## Approach

- Store 768-d embeddings from Ollama `nomic-embed-text` on `properties.embedding` (pgvector) with an HNSW cosine index.
- Embed on scrape via a dedicated Celery task (`embed_property`) that does not require images or the GPU semaphore.
- `GET /properties?q=` embeds the query once and orders by `embedding <=> query_vec`, ANDing existing filters.
- Custom `Dockerfile.postgres` extends PostGIS Alpine with pgvector so local compose and CI share one image.

## Changes

Files touched:

```
 Dockerfile.postgres                                      | NEW — PostGIS 15 + pgvector
 alembic/versions/e8a1b2c3d4e5_add_property_embedding…  | NEW — vector extension + column + HNSW
 docker-compose.yml / .github/workflows/{ci,nightly}.yml  | Use custom Postgres image
 configs/app_config.yaml + src/infra/config.py            | ai.embedding_model
 src/adapters/ai/client.py + embeddings.py                | embed() + text helpers
 src/adapters/queue/tasks.py + celery_app.py              | embed_property task + scrape enqueue
 src/api/properties.py                                    | q= semantic list
 src/api/admin.py                                         | POST /admin/embeddings/backfill
 frontend/src/api.js + pages/Properties.jsx               | Search box + q param
 scripts/ci/start-postgres-pgvector.sh                    | CI Postgres bootstrap
 scripts/agent/validate.sh                                | Prefer project .venv Python
 src/tests/unit/test_embeddings.py + test_ai_client.py    | Unit coverage
 src/tests/integration/test_semantic_search.py            | Cosine order integration test
```

## New Dependencies

- `pgvector` (Python) in `requirements.txt`
- Postgres extension `vector` (via `Dockerfile.postgres`)
- Ollama model `nomic-embed-text` (runtime; not pip)

## How to Test

1. Rebuild Postgres: `docker compose build postgres && docker compose up -d`
2. Migrate: `alembic upgrade head`
3. Pull model: `ollama pull nomic-embed-text`
4. Backfill: `POST /admin/embeddings/backfill` (JWT)
5. Search: `GET /properties?q=apartamento+metro` or use the Properties search box
6. Automated:
   ```bash
   bash scripts/agent/validate.sh backend
   ```

## Notes / Follow-ups

- Listings without title/description are not embedded; rows with `embedding IS NULL` are excluded from `q=` results.
- Re-embed on text-only updates happens when scrape action is not `noop`.
- LM Studio backends use `/v1/embeddings` for parity.
- Closed mistaken PR #15 (wrong branch); shipped as [#16](https://github.com/felipelrib/imoveis/pull/16).
