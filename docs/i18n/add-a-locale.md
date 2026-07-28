# Add a locale

Checklist for shipping a **third** (or Nth) product locale without one-off `if locale == …` branches.
Canonical **DB / API wire values stay English**. This guide does **not** cover bilingual scraping or translating neighbourhood proper nouns.

**Shipped today:** `en` (default) + `pt-BR`. Preference: Redis `ui:locale` via `GET`/`POST /admin/locale`, allowlisted by `ui.supported_locales`.

Epic close: [Product i18n](../features/83-product-i18n.md) (BIN-63 / BIN-103). Seed ADR: [Locale foundation](../features/77-locale-foundation.md).

---

## 1. Message catalog

1. Copy `frontend/src/i18n/locales/en.json` → `frontend/src/i18n/locales/<BCP-47>.json` (e.g. `es.json`, `pt-PT.json`).
2. Translate **values** only — keep the nested key tree byte-identical to `en` (same leaf count).
3. Register in `frontend/src/i18n/index.js`:

   ```js
   import es from './locales/es.json'
   export const CATALOGS = { en, 'pt-BR': ptBR, es }
   ```

4. Add switcher labels under `locale.*` in **every** catalog. Key convention: BCP-47 with hyphens stripped for the catalog segment (`pt-BR` → `locale.ptBR`, `en` → `locale.en`). The SPA uses `localeLabelKey(code)` — do not hardcode `code === '…'` in `App.jsx`.
5. Confirm `SUPPORTED_LOCALES = Object.keys(CATALOGS)` picks up the new tag.

## 2. Preference enum / allowlist

1. Add the tag to `ui.supported_locales` in `configs/app_config.yaml`.
2. Widen `UiConfig.locale` `Literal[...]` in `src/infra/config.py` to include the new tag (keep default `en`).
3. No change needed in `resolve_active_locale` / admin POST beyond the allowlist — unknown values already 400.
4. SPA intersects API `supported` with local `CATALOGS` keys; a backend-only locale will not drive missing catalogs.

## 3. Filter synonym maps

Wire values stay English (`apartment`, `rent`, …). UI labels come from the catalog (`labels.propertyType.*`, `properties.rentOnly`, …).

1. Extend shared fold→canonical maps (append aliases; do **not** add `if locale ==`):
   - `src/core/property_type.py` — `_ALIAS_TO_CANONICAL`
   - `src/core/listing_type.py` — `_LISTING_ALIAS_TO_CANONICAL` / `_PRICE_ALIAS_TO_CANONICAL`
2. Translate filter chrome keys in the new catalog only.
3. Amenity toggles (furnished / pets) are catalog strings; pets still matches platform amenity keys internally — no per-locale synonym file required unless you add new human aliases.
4. Saved-search JSON remains snake_case EN; server normalizes aliases on write.

Optional later: extract per-locale alias modules if maps grow large — keep one resolve entrypoint.

## 4. AI output / display maps

### Closed vocab (codes in DB)

1. Add `ai.statBand.*`, `ai.visualCategory.*`, `ai.sentimentCategory.*`, `ai.riskFlags.*` strings to the new catalog (same keys as `en`).
2. SPA helpers (`labelStatBand`, `labelRiskFlag`, …) already read the active catalog — no code change if keys match.
3. Canonical codes live in `src/core/ai_locale.py` — locale-invariant; do not invent parallel code sets.

### Free-text generation + template fallbacks

1. Active UI locale drives generation via `resolve_ai_output_language()` (Redis → `ui.locale` → `ai.output_language` fallback).
2. Extend **dict registries** in `src/adapters/ai/client.py` (`_TEMPLATE_STAT`, `_TEMPLATE_VISUAL`, `_TEMPLATE_EMPTY`, sentiment/neighbourhood phrase maps). Prefer new locale keys on those dicts — **never** new `if locale == "…"` branches.
3. Prompt builders already interpolate `output_language`; smoke that the new language name appears in prompts (`test_ai_prompt_locale.py`).
4. After flipping preference, re-run selective AI enrichment so stored free-text verdicts match the new locale.

## 5. Embeddings & semantic search

1. Index text stays scraped title+description (usually PT for BH). No re-embed for chrome-only locales.
2. Extend `_SYNONYM_GROUPS` in `src/core/semantic_query.py` with housing pairs for the new language ↔ PT (or ↔ EN) when operators will type `q=` in that language.
3. Prefer queries in listing language; EN already expands via the lexicon (BIN-102).
4. Optional: re-run `scripts/dev/probe_pt_en_locale_audit.py --normalize` patterns for the new pairs.

## 6. Tests to extend

| Layer | Paths |
|---|---|
| Config / admin | `test_config.py`, `test_admin_locale.py`, contract `test_locale_get_returns_shape` |
| AI templates / prompts | `test_deal_verdict.py`, `test_ai_prompt_locale.py`, `test_ui_locale_ai.py` |
| Filter aliases | `test_property_type.py`, `test_listing_type.py` |
| Semantic lexicon | `test_semantic_query.py` |
| Catalog hygiene | key-parity `en` vs new locale (leaf paths identical) |
| Registry spot-check | `test_locale_registry_hygiene.py` — no `if locale ==` / switcher ternaries outside registries |
| E2E | `locale-foundation`, `locale-full-ui`, `locale-filters`, `ai-locale-labels`; update `mockAdminLocale` `supported` |
| Default EN copy | Keep default-locale catalog values byte-identical to existing Playwright asserts when touching `en.json` |

## 7. Docs & product artifacts

1. Feature note under `docs/features/` if the locale ships as a ticket.
2. Keep planning docs (PRD / epics / ADRs) in **English** (NFR-7).
3. Link this checklist from the epic close doc and any foundation ADR.

## 8. Explicit non-goals

- Re-scraping platforms or storing bilingual listing bodies.
- Translating neighbourhood / city proper nouns.
- Dual-storing AI codes per locale (codes stay EN/snake_case; display is catalog-only).
- Changing numeric scoring math for language reasons.

## Done when

- [ ] Catalog registered + key tree matches `en`
- [ ] YAML + `Literal` allowlist updated
- [ ] Switcher uses `localeLabelKey` / catalog keys (no hardcoded ternary)
- [ ] Filter aliases appended (if needed) + UI labels translated
- [ ] AI template **dicts** + catalog `ai.*` keys extended
- [ ] Semantic synonym groups extended (if operators search in the new language)
- [ ] Unit + at least one Playwright smoke for the new locale
- [ ] `test_locale_registry_hygiene` still green
