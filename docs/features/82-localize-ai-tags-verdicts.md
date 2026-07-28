# Localize AI tags, verdicts & score copy — closed codes + locale generation (BIN-101)

> Feature branch: `feat/localize-ai-tags-verdicts` · Linear: `BIN-101` · Status: implemented

## Problem

Deal verdicts, visual/sentiment categories, statistical band copy, and neighbourhood
risk flags were English-only (or raw snake_case) while the SPA can switch to `pt-BR`.
Operators flipping language still saw EN AI payload values unless they re-scraped
(which is out of scope).

## Approach

- **Hybrid Option C** (BIN-97 recommendation): stable machine codes + SPA display
  catalogs for closed vocab; free-text fields generated in the **active UI locale**.
- Stat / visual / sentiment **categories** persist as snake_case codes; legacy EN
  titles normalize on ingest and API read.
- Stat **reasoning** is owned by the catalog (empty on new score writes).
- Risk flags stay codes in the DB; UI maps `flood_zone` / `industrial_adjacent` / …
- Visual/sentiment prompts take `output_language` with a hard language rule (few-shots
  alone leaked PT into flags).
- Template deal-verdict phrases exist for `en` and `pt-BR`.
- Generation language = `resolve_ai_output_language()` (Redis `ui:locale` → `ui.locale`;
  falls back to `ai.output_language` if Redis is unavailable).
- Listing `title` / `description` remain as scraped — no bilingual scrape path.

## Changes

Files touched:

```
 src/core/ai_locale.py                         | NEW — category codes + legacy normalize
 src/infra/ui_locale.py                        | NEW — shared active locale + AI language
 src/api/admin.py                              | Import shared locale helpers
 src/adapters/metrics/scoring.py               | _stat_analysis returns codes
 src/adapters/ai/prompts.py                    | output_language + code enums
 src/adapters/ai/client.py                     | Localized template; normalize on parse
 src/adapters/queue/tasks.py                   | Pass active locale into prompts
 src/api/property_projection.py                | Normalize categories on read
 src/infra/config.py                           | UiConfig docstring (AI follows UI locale)
 frontend/src/i18n/locales/en.json             | ai.statBand / visual / sentiment / riskFlags
 frontend/src/i18n/locales/pt-BR.json          | Same keys in Portuguese
 frontend/src/i18n/index.js                    | labelStatBand, labelRiskFlag, …
 frontend/src/components/PropertyModal.jsx     | Localized closed-vocab display
 frontend/src/components/CompareView.jsx       | Localized risk flag labels
 frontend/tests/e2e/ai-locale-labels.spec.js   | NEW — EN + PT modal smoke
 src/tests/unit/test_ai_locale.py              | NEW
 src/tests/unit/test_ai_prompt_locale.py       | NEW
 src/tests/unit/test_ui_locale_ai.py           | NEW
 src/tests/unit/test_scoring_locale_catalog.py | Codes instead of EN titles
 src/tests/unit/test_deal_verdict.py           | Codes + pt-BR template
 docs/features/82-localize-ai-tags-verdicts.md | NEW — this note
```

## New Dependencies

None.

## How to Test

1. Unit / CI gate:
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Manual: set Language to Português, open a property modal — stat band, visual/sentiment
   categories, and risk flags should be PT; free-text verdict/flags stay as last enriched.
3. After a locale flip, re-run selective AI enrichment (`verdict_only` or full) via
   BIN-95 admin controls so free-text fields match the new language.

## Notes / Follow-ups

- **Operator:** closed-vocab labels flip immediately with the SPA locale. Free-text
  (`deal_summary`, reasonings, green/red flags, features/issues) requires a selective
  re-enrich (BIN-95) after changing language.
- `ai.output_language` remains in AppConfig as a fallback when Redis/UI locale
  resolution fails; normal enrichments follow the active UI preference.
- Related: BIN-63 epic · BIN-97 audit · BIN-98 locale foundation · BIN-95 re-enrich ·
  BIN-102 embeddings locale.
