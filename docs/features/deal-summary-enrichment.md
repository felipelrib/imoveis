# deal-summary-enrichment

> Feature branch: `main` · Status: implemented · Issue: [BIN-12](https://linear.app/felipelrib/issue/BIN-12/natural-language-deal-verdict)

## Problem

The three scoring signals (statistical price analysis, visual condition assessment, and location sentiment) already exist but users must mentally combine them. The product's punchline — a single sentence explaining "why it's a deal" — was missing.

## Approach

**Template-with-optional-LLM** strategy:

1. **Deterministic template** (`template_deal_verdict()`) — always works, even with GPU paused. Combines the three signals into a PT-BR sentence using category-to-translation maps and red/green flag counting.
2. **Optional LLM synthesis** (`summarize_deal()`) — calls the configured text model (Ollama or LM Studio) with a specialized prompt that produces a more natural-sounding verdict. Falls back to template on any error.

The verdict is generated during `ai_enrich` Celery task execution, stored in the existing `metrics_scoring.meta` JSONB column under `deal_verdict`, and surfaced through the API and frontend.

## Changes

```
src/adapters/ai/client.py          — DealVerdictResult model, template_deal_verdict(), summarize_deal() on LocalAIClient + OllamaClient + LMStudioClient
src/adapters/ai/prompts.py         — build_deal_verdict_prompt() for LLM synthesis
src/adapters/queue/tasks.py        — Wire verdict generation into ai_enrich after scoring
src/api/properties.py              — Surface deal_summary in GET /properties and GET /properties/{id}
frontend/src/components/PropertyModal.jsx — Gradient verdict callout above score explanations
frontend/src/pages/Properties.jsx  — Verdict one-liner on property cards
src/tests/unit/test_deal_verdict.py — 19 unit tests (template, model, mocked LLM, prompt builder)
```

## New dependencies

None.

## How to test

1. `bash scripts/start.sh`
2. Run a scrape + AI enrichment cycle to generate verdicts for existing properties
3. Open the properties browser — cards should show a `💡` verdict one-liner
4. Click a property — modal should show a gradient callout with the deal verdict
5. `pytest src/tests/unit/test_deal_verdict.py -v` — all 19 tests pass

## Notes / follow-ups

- The verdict is only generated for properties that have been through AI enrichment (have visual + sentiment data). Properties with only stat scores will show a shorter template verdict.
- LLM quality depends on the loaded model — the template fallback is intentionally simpler but reliable.
- Future improvement: add a `POST /admin/verdict/recompute` endpoint to regenerate verdicts for all enriched properties after prompt tuning.
