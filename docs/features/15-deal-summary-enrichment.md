# deal-summary-enrichment — LLM-generated Portuguese deal verdict synthesising all three scoring signals

> Feature branch: `feat/deal-verdict` · Linear: `BIN-12` · Status: implemented

## Problem

Three separate scoring signals (statistical price positioning, visual condition, location
sentiment) were computed but presented in isolation. Users had to mentally combine them to
reach a deal judgement. A single natural-language punchline — the "deal verdict" — was
missing from both property cards and the detail modal.

## Approach

**Template-with-optional-LLM** strategy to ensure the verdict is always available even
when GPU/AI workers are paused:

1. **Deterministic template** (`template_deal_verdict()` in `adapters/ai/client.py`):
   - Maps stat category → PT-BR string (e.g. `"Highly Undervalued"` → `"Altamente subvalorizado"`)
   - Maps visual category → PT-BR label
   - Counts `red_flags` and `green_flags` from sentiment
   - Joins with em-dash and commas into a single sentence
   - Zero dependencies, zero latency

2. **Optional LLM synthesis** (`summarize_deal()` on `LocalAIClient`):
   - `build_deal_verdict_prompt()` feeds all three signals + neighbourhood name to the LLM
   - Expects a strict JSON `{"verdict": "<PT-BR sentence>", "confidence": <float>}` response
   - Falls back to the template on any exception (timeout, parse error, model unavailable)

The verdict is generated at the **`ai_enrich` task integration** (`adapters/queue/tasks.py`):
  - Added a third VLM call `client.summarize_deal(...)` passing the `stat_analysis`,
    `visual` result, `sentiment` result, and `neighborhood_name`.
  - The human-readable neighbourhood name is resolved via a JOIN query on the `neighborhoods`
    table using the property's `neighborhood_id` FK.
  - The verdict string and confidence score are saved to `metrics_scoring.meta["deal_verdict"]`.
  - It handles empty/missing inputs gracefully (e.g. if the property has no photos, the
    visual payload is empty).

## Changes

Files touched:

```
 src/adapters/ai/client.py                     | DealVerdictResult model, template_deal_verdict(), summarize_deal() on LocalAIClient, OllamaClient._llm_verdict(), LMStudioClient._llm_verdict()
 src/adapters/ai/prompts.py                    | NEW build_deal_verdict_prompt() three-signal LLM prompt
 src/adapters/queue/tasks.py                   | Wired verdict generation into ai_enrich after stat scoring
 src/api/properties.py                         | Surfaced deal_summary in GET /properties and GET /properties/{id}
 frontend/src/components/PropertyModal.jsx     | Gradient verdict callout card above score explanations
 frontend/src/pages/Properties.jsx             | Verdict one-liner on property cards (💡 prefix)
 src/tests/unit/test_deal_verdict.py           | NEW — 19 unit tests (template, model, mocked LLM, prompt builder)
```

## New Dependencies

None.

## How to Test

1. Start the stack: `bash scripts/start.sh`
2. Run a scrape and allow AI enrichment to complete:
   ```bash
   curl -X POST http://localhost:8000/scrape -d '{"platform":"olx"}'
   ```
3. Open **Properties** — each card should show a `💡` verdict one-liner below the score.
4. Click a property — modal should show a coloured verdict callout at the top.
5. Verify template fallback:
   ```bash
   pytest src/tests/unit/test_deal_verdict.py -v
   ```
   All 19 tests should pass.

## Notes / Follow-ups

- ~~**Token usage limits**~~ — FIXED (added config `ai.max_description_chars`)
- ~~**Latency impact**~~ — FIXED (parallelized `analyze_visuals` and `analyze_text` with `asyncio.gather`)
- ~~**Language configuration**~~ — FIXED (added config `ai.output_language`)
- ~~Future: `POST /admin/verdict/recompute`~~ — FIXED (added endpoint)
