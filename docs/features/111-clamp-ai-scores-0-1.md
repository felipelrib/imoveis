# Clamp/validate AI condition & sentiment scores to [0,1] contract

> Feature branch: `feat/clamp-ai-scores-0-1` · Linear: `BIN-148` · Status: implemented

## Problem

`VisualResult`/`SentimentResult` (`src/adapters/ai/client.py`) parsed `condition_score`/`sentiment_score` directly from local-model JSON output with no `Field(ge=0, le=1)` bound — only the *type* (`float`) was enforced, not the *range*. A model drifting to a 0-100 scale (or emitting a slightly out-of-range float like `1.02` from rounding) flowed unclamped into `a_score = condition_score*visual_weight + sentiment_score*text_weight` (`src/adapters/queue/tasks.py:755-758`), which is persisted to `MetricsScoring` and used to rank deals.

`CLAUDE.md` explicitly documents the "AI scores are floats in `[0.0, 1.0]`" contract because of the prior BIN-56 incident (`ResponseValidationError` from an int/float mismatch), but nothing enforced the *range* before this change. Unlike BIN-56, this failure mode was **silent**: a bad score would persist and corrupt deal ranking rather than raise a loud, visible error.

## Approach

Two different bounds strategies at two different boundaries, deliberately not the same everywhere:

- **Ingestion boundary (`adapters/ai/client.py`) — clamp, don't reject.** Added a shared `_clamp_unit_score()` helper wired via `@field_validator` on `VisualResult.condition_score` and `SentimentResult.sentiment_score`. Values are clamped into `[0.0, 1.0]` with `max(0.0, min(1.0, value))`, and a `logger.warning(...)` fires whenever clamping actually changed the value (so drift stays visible in logs instead of silent). Rationale for clamping over hard rejection here: local VLM/text model output is noisy by nature (a stray `1.02` from float rounding, or a model that starts answering on a 0-100 scale) and the rest of the parsed result (`category`, `reasoning`, `features_detected`/`issues_detected`, `green_flags`/`red_flags`) is still useful and should not be thrown away just because one score field drifted. Genuinely malformed (non-numeric) values still fail loudly — Pydantic's ordinary type coercion runs *before* the field validator, so e.g. `condition_score: "high"` still raises a `ValidationError`, caught by the existing `except Exception` fallback in `analyze_visuals`/`analyze_text` (falls back to the existing `condition_score=0.5` / `sentiment_score=0.5` default with `analysis="Error"`).
- **Response boundary (`api/schemas.py`) — hard validate, fail loudly.** Added `Field(None, ge=0.0, le=1.0)` to `PropertyModel.ai_score`/`condition_score`/`sentiment_score` and `PropertyDetailModel.ai_score`. By the time a score reaches the API response layer it has already gone through the client.py clamp (or persisted-data-that-should-already-be-canonical), so an out-of-range value here indicates a genuine bug elsewhere in the pipeline (bad backfill, a new producer that bypasses the clamp, manual DB edit, etc.) rather than ordinary model noise — consistent with the BIN-56 precedent of failing loudly (`ResponseValidationError`) rather than silently serving a corrupted value.
- `cfg.ai.visual_weight` (0.7) + `cfg.ai.text_weight` (0.3) sum to 1.0 (`configs/app_config.yaml`), so once both inputs are guaranteed `∈ [0,1]` at the ingestion boundary, `a_score` (their convex combination) is guaranteed `∈ [0,1]` too — the schema-level bound is defense-in-depth, not a load-bearing fix on its own.

## Changes

Files touched:

```
src/adapters/ai/client.py                        | NEW _clamp_unit_score() helper + @field_validator on VisualResult.condition_score / SentimentResult.sentiment_score
src/api/schemas.py                                | Field(ge=0.0, le=1.0) bounds on PropertyModel.ai_score/condition_score/sentiment_score and PropertyDetailModel.ai_score
src/tests/unit/test_ai_client.py                  | NEW tests: clamp scale-drift (85/70 on a 0-100 scale), clamp minor overflow (1.02), clamp negative, in-range passthrough, and two full-pipeline tests (analyze_visuals/analyze_text) proving a raw drifted Ollama JSON response comes out clamped
src/tests/unit/test_properties_response_schema.py | NEW parametrized test: PropertyModel rejects out-of-range condition_score/sentiment_score/ai_score with ValidationError
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
bash scripts/agent/validate-ai.sh
```

Targeted:

```bash
PYTHONPATH=src pytest src/tests/unit/test_ai_client.py src/tests/unit/test_properties_response_schema.py -v
```

## Notes / Follow-ups

- `stat_score`/`combined_score`/`percentile_rank`/`z_score` and other statistical fields intentionally remain unbounded — they are not `[0,1]`-contracted scores (z-scores can be negative/large, percentile ranks are already derived safely). Only the AI-model-produced `condition_score`/`sentiment_score`/`ai_score` triple is in scope per the ticket.
- Related: BIN-56 (`Fix GET /properties 500 on float condition/sentiment scores`) — the type-level half of this same contract.
