# deal-summary-enrichment — LLM-generated deal verdict synthesising all three scoring signals

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
   - Maps stat / visual / sentiment signals into locale-aware punchline fragments
   - Default generation language is **English** (`en`); `pt-BR` phrases exist for the
     active UI locale (see [82-localize-ai-tags-verdicts.md](82-localize-ai-tags-verdicts.md)
     / [BIN-101](https://linear.app/felipelrib/issue/BIN-101))
   - Counts ad-claim flags from sentiment and optional neighbourhood-quality snippets
   - Joins with em-dash and commas into a single sentence
   - Zero dependencies, zero latency

2. **Optional LLM synthesis** (`summarize_deal()` on `LocalAIClient`):
   - `build_deal_verdict_prompt()` feeds all three signals + neighbourhood name to the LLM
   - Expects a strict JSON `{"verdict": "<sentence>", "confidence": <float>}` response in
     the active output language (`resolve_ai_output_language()` → Redis `ui:locale` /
     `ui.locale`, falling back to `ai.output_language`)
   - Falls back to the template on any exception (timeout, parse error, model unavailable)

The verdict is generated at the **`ai_enrich` task integration** (`adapters/queue/tasks.py`):
  - Added a third VLM call `client.summarize_deal(...)` passing the `stat_analysis`,
    `visual` result, `sentiment` result, and `neighborhood_name`.
  - The human-readable neighbourhood name is resolved via a JOIN query on the `neighborhoods`
    table using the property's `neighborhood_id` FK.
  - The verdict string and confidence score are saved to `metrics_scoring.meta["deal_verdict"]`
    and surfaced as `deal_summary` on property API responses.
  - It handles empty/missing inputs gracefully (e.g. if the property has no photos, the
    visual payload is empty).

**Locale source of truth:** closed-vocab labels and free-text AI generation language are
owned by [82-localize-ai-tags-verdicts.md](82-localize-ai-tags-verdicts.md) (BIN-101).
This note documents the original deal-verdict pipeline; do not treat the historical
PT-only wording as current behaviour. English product baseline landed in
[48-english-listing-accuracy.md](48-english-listing-accuracy.md) (BIN-64).

## Changes

Files touched:

```
 src/adapters/ai/client.py                     | DealVerdictResult model, template_deal_verdict(), summarize_deal() on LocalAIClient, OllamaClient._llm_verdict(), LMStudioClient._llm_verdict()
 src/adapters/ai/prompts.py                    | NEW build_deal_verdict_prompt() three-signal LLM prompt
 src/adapters/queue/tasks.py                   | Wired verdict generation into ai_enrich after stat scoring
 src/api/properties.py                         | Surfaced deal_summary in GET /properties and GET /properties/{id}
 frontend/src/components/PropertyModal.jsx     | Gradient verdict callout card above score explanations
 frontend/src/pages/Properties.jsx             | Verdict one-liner on property cards (💡 prefix)
 src/tests/unit/test_deal_verdict.py           | NEW — unit tests (template, model, mocked LLM, prompt builder; EN + locale)
```

## New Dependencies

None.

## How to Test

1. Start the stack: `bash scripts/start.sh`
2. Run a scrape and allow AI enrichment to complete:
   ```bash
   curl -X POST http://localhost:8000/scrape -d '{"platform":"olx"}'
   ```
3. Open **Properties** — each card should show a `💡` verdict one-liner below the score
   (English by default; Portuguese after SPA language flip + selective re-enrich).
4. Click a property — modal should show a coloured verdict callout at the top.
5. Verify template fallback:
   ```bash
   bash scripts/agent/validate.sh fast
   ```
   (or `pytest src/tests/unit/test_deal_verdict.py -v` when iterating locally).

## Notes / Follow-ups

- **AI locale SoT:** [82-localize-ai-tags-verdicts.md](82-localize-ai-tags-verdicts.md) /
  [BIN-101](https://linear.app/felipelrib/issue/BIN-101). Free-text `deal_summary` follows
  the active UI locale at enrich time; flip language then re-run `verdict_only` (BIN-95)
  to refresh stored copy.
- Doc refresh (remove stale PT-BR-only claims): [BIN-126](https://linear.app/felipelrib/issue/BIN-126)
  / [84-refresh-deal-summary-feature-doc.md](84-refresh-deal-summary-feature-doc.md).
- Related: BIN-12 (original) · BIN-64 English baseline · BIN-95 selective re-enrich ·
  BIN-101 AI locale.
