# Full UI string catalog — en + pt-BR

> Feature branch: `feat/bin-99-full-ui-string-catalog` · Linear: `BIN-99` · Status: implemented

## Problem

After the locale foundation (BIN-98), only nav/system chrome used catalogs. Properties, Dashboard, Scraper Control, Compare, PropertyModal, credential gate, and related chrome stayed hardcoded English while number/date helpers forced `pt-BR` — a mixed experience for operators who prefer Portuguese product UI.

## Approach

- Expand nested JSON catalogs (`en` + `pt-BR`) under `frontend/src/i18n/locales/` (~429 leaf keys) covering brand, common, labels, attr, properties, dashboard, scraper, compare, modal, map, credential, and errors.
- Keep the thin `t()` / `useLocale()` stack from BIN-98; no new i18n framework.
- Locale-aware `labels.js` property-type options (`labelKey` → catalog); platform brand names stay untranslated.
- Central `i18n/format.js` helpers so currency/number/date formatting follows the active UI locale (BRL currency code unchanged).
- `activeLocale.js` synced from `LocaleProvider` so `api.js` user-facing throws resolve through `errors.*` without React context.
- Shared `attr.*` keys for Compare + PropertyModal detail labels.
- Playwright: default `mockAdminLocale` inside `installCommonMocks`; PT smoke on Dashboard / Properties / modal.

## Changes

Files touched:

```
 frontend/src/i18n/locales/en.json                 | EXPAND full chrome catalog
 frontend/src/i18n/locales/pt-BR.json              | EXPAND full chrome catalog
 frontend/src/i18n/format.js                       | NEW — locale number/date helpers
 frontend/src/i18n/activeLocale.js                 | NEW — module locale for api.js
 frontend/src/i18n/LocaleContext.jsx               | sync setActiveLocale on boot/change
 frontend/src/labels.js                            | locale-aware property type labels
 frontend/src/api.js                               | errors.* via active locale
 frontend/src/App.jsx                              | brand tagline via t()
 frontend/src/pages/Properties.jsx                 | full chrome + formatters
 frontend/src/pages/Dashboard.jsx                  | full chrome + formatters
 frontend/src/pages/ScraperControl.jsx             | UI + log templates
 frontend/src/components/PropertyModal.jsx         | chrome + attr.* + formatters
 frontend/src/components/CompareView.jsx           | ATTR_ROWS labelKey + formatters
 frontend/src/components/MapView.jsx               | popup chrome + formatters
 frontend/src/components/CredentialGate.jsx        | credential.* keys
 frontend/src/components/ErrorBoundary.jsx         | errors.* via active locale
 frontend/src/components/SearchableMultiSelect.jsx | common.* defaults
 frontend/tests/e2e/helpers/apiMocks.js            | mockAdminLocale in installCommonMocks
 frontend/tests/e2e/locale-full-ui.spec.js         | NEW — PT chrome smoke
 frontend/tests/e2e/property-modal-listings.spec.js| EN digit grouping assert
 frontend/tests/e2e/dashboard.spec.js              | EN digit grouping assert
 docs/features/79-full-ui-string-catalog.md        | NEW — this doc
 _bmad-output/.../sprint-status.yaml               | 8-3 → done
```

## New Dependencies

None.

## How to Test

1. Full gate (includes Playwright locale specs):
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Manual: set API credential → switch Language to Português (Brasil) → confirm Dashboard title **Painel**, Properties **Imóveis** / **Filtros avançados**, and modal **Veredito do negócio** without reload hacks. Switch back to English; money uses active-locale digit grouping.

## Notes / Follow-ups

- BIN-100: locale-aware filter labels + PT synonym → EN wire — see `docs/features/80-locale-aware-filters.md`.
- BIN-101: localize AI tags / verdicts / score *payload* copy (only chrome labels shipped here).
- BIN-116: money/date formatter follow-up from feature 77 — already shipped here; closed with dedicated regression specs in `90-locale-aware-moneydate-formatters.md`.
- Scraped listing bodies and neighbourhood proper nouns remain untranslated by design.
- Map popup click handlers register once per map source create; rare mid-session locale switch may need a map remount to refresh popup chrome (acceptable for single-operator preference change).
