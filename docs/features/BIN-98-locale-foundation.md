# Locale foundation — catalog + persisted preference

> Feature branch: `feat/bin-98` · Linear: `BIN-98` · Status: implemented

## Problem

Product UI chrome is hardcoded English while money/dates already use `pt-BR` formatting. There is no saved language preference and no additive string-catalog path for a second locale. Operators need a foundation so later stories can migrate strings (BIN-99), filters (BIN-100), and AI copy (BIN-101) without one-off edits.

## Approach

- Lightweight JSON message catalogs under `frontend/src/i18n/locales/` plus a thin `t(locale, key)` helper — no heavy i18n framework.
- AppConfig gains `ui.locale` / `ui.supported_locales` (YAML + `IMOVEIS_UI__LOCALE`). Install default is `en`.
- **`ui.locale` is independent of `ai.output_language`.** Chrome reads `ui.locale` (and Redis override); AI prompts keep `ai.output_language`. Preference POST does not mutate AI config. Operators may align them manually until BIN-101.
- Persistence mirrors `/admin/schedule`: Redis key `ui:locale` via `GET`/`POST /admin/locale` (YAML default when Redis miss / invalid).
- Seed only nav + system chrome + language switcher; full string migration is BIN-99.

### ADR: How to add a language

Canonical checklist (message catalog, filters, AI maps, embeddings, tests):
[`docs/i18n/add-a-locale.md`](../i18n/add-a-locale.md) (BIN-103 / epic close
[`BIN-103-product-i18n.md`](BIN-103-product-i18n.md)).

Seed steps (still valid):

1. Add `frontend/src/i18n/locales/<tag>.json` (copy `en.json`, translate values).
2. Register the catalog in `frontend/src/i18n/index.js` (`CATALOGS`).
3. Add the BCP-47 tag to `ui.supported_locales` in `configs/app_config.yaml` (and keep `UiConfig.locale` Literal in sync if the default set expands).
4. Extend switcher option labels in every catalog (`locale.*` keys) — use `localeLabelKey`, no hardcoded ternaries.
5. Follow the full checklist for synonym maps, AI template dicts, and semantic lexicon.

## Changes

Files touched:

```
 configs/app_config.yaml                              | ADD ui.locale + supported_locales
 src/infra/config.py                                  | ADD UiConfig on AppConfig
 src/api/admin.py                                     | ADD GET/POST /admin/locale (Redis ui:locale)
 src/tests/unit/test_config.py                        | ui parse / env / invalid / critical section
 src/tests/unit/test_admin_locale.py                  | NEW — resolve + preference round-trip
 src/tests/contract/test_api_contract.py              | GET /admin/locale shape
 frontend/src/i18n/locales/en.json                    | NEW — English catalog seed
 frontend/src/i18n/locales/pt-BR.json                 | NEW — pt-BR catalog seed
 frontend/src/i18n/index.js                           | NEW — catalogs + t()
 frontend/src/i18n/LocaleContext.jsx                  | NEW — LocaleProvider / useLocale
 frontend/src/api.js                                  | fetchLocale / updateLocale
 frontend/src/App.jsx                                 | seed chrome via t() + language switcher
 frontend/src/index.css                               | locale switcher styles
 frontend/index.html                                  | default lang=en (provider overrides)
 frontend/tests/e2e/helpers/apiMocks.js               | mockAdminLocale
 frontend/tests/e2e/locale-foundation.spec.js         | NEW — switch + reload persistence
 docs/features/BIN-98-locale-foundation.md                | NEW — this doc
```

## New Dependencies

None.

## How to Test

1. Unit / contract:
   ```bash
   bash scripts/agent/validate.sh backend
   ```
2. Full gate (includes Playwright locale e2e):
   ```bash
   bash scripts/agent/validate.sh all
   ```
3. Manual: set API credential → change Language in the sidebar → reload → chrome stays in the chosen locale. Confirm `GET /admin/locale` reflects Redis override without changing `ai.output_language` in YAML.

## Notes / Follow-ups

- BIN-99: migrate remaining SPA strings into the catalogs.
- BIN-100 / BIN-101: filters and AI user-visible fields; may optionally link UI locale to AI generation later without merging the config keys.
- Money/date formatters: centralized on active UI locale in BIN-99 (`format.js`); follow-up ticket BIN-116 closed with regression locks — see `BIN-116-locale-aware-moneydate-formatters.md`.
- Redis preference is process/cluster shared (single-operator first); owner-scoped prefs table deferred per epic non-goals.
