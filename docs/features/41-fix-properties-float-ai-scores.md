# Fix properties 500 on float AI scores — align PropertyModel with AI domain

> Feature branch: `fix/properties-endpoint-500` · Linear: `BIN-56` · Status: implemented

## Problem

`GET /properties` returned 500 Internal Server Error whenever listed properties had AI enrichment. FastAPI response validation rejected fractional `condition_score` / `sentiment_score` values because `PropertyModel` typed them as `Optional[int]` while the AI clients store floats in `[0.0, 1.0]`. Contract tests swallowed all 500s as “DB unavailable,” so the bug never failed CI.

## Approach

- Change `condition_score` and `sentiment_score` on `PropertyModel` to `Optional[float]` to match `VisualResult` / `SentimentResult`.
- Add unit tests that exercise FastAPI `response_model` validation with mocked DB rows containing fractional scores.
- Add an integration test that seeds enriched `metrics_scoring.meta` and asserts list/export return 200.
- Harden contract helpers: only skip when the properties schema is missing; fail when the table exists but the endpoint returns 500.
- Run Alembic migrations in the CI contract job so those checks actually hit a migrated schema.

## Changes

Files touched:

```
 src/api/schemas.py                                      | FIX — condition_score/sentiment_score Optional[float]
 src/tests/unit/test_properties_response_schema.py       | NEW — response_model lock with float AI scores
 src/tests/unit/test_property_projection.py              | FIX — use float fixture scores + PropertyModel validate
 src/tests/unit/test_property_export.py                  | FIX — float fixture scores
 src/tests/integration/test_properties_ai_scores.py      | NEW — seed enriched row, assert list/export 200
 src/tests/contract/test_api_contract.py                 | FIX — fail schema 500s; DB-free float score contract
 .github/workflows/ci.yml                                | FIX — migrate DB before contract tests
 docs/features/41-fix-properties-float-ai-scores.md      | NEW — this doc
```

## New Dependencies

None.

## How to Test

1. With the API running against a DB that has enriched properties:
   ```bash
   curl -sS -o /dev/null -w "%{http_code}\n" "http://localhost:8000/properties?page=1&page_size=5"
   # expect 200
   ```
2. Automated gate:
   ```bash
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- Related: AI prompts/clients already document scores as floats (`adapters/ai/prompts.py`, `VisualResult` / `SentimentResult`).
- Linear: https://linear.app/felipelrib/issue/BIN-56/fix-get-properties-500-on-float-conditionsentiment-scores
