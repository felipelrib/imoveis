# Product i18n — epic close (pt-BR first, multi-locale ready)

> Feature branch: `feat/bin-103-multi-locale-extensibility` · Linear: `BIN-103` (epic `BIN-63`) · Status: implemented

## Problem

Epic 8 shipped `en` + `pt-BR` across catalogs, filters, AI display, and semantic query expansion, but NFR-7 still said second locales were deferred, and there was no single checklist for adding locale N without one-off `if locale == …` branches.

## Approach

- Publish a durable **Add a locale** checklist covering message catalogs, preference allowlist, filter synonym maps, AI display/template registries, embeddings lexicon, and tests.
- Refresh PRD / epics **NFR-7** to match shipped behaviour (English default + pt-BR; further locales via checklist; planning docs stay English; canonical wire stays EN).
- Remove remaining hardcoded PT/EN prose forks in the AI template path and locale switcher; lock with a light registry hygiene unit test.
- This ticket does **not** ship a third language.

## Changes

Files touched:

```
 docs/i18n/add-a-locale.md                                              | NEW — add-locale checklist
 docs/features/83-product-i18n.md                                       | NEW — epic close (this doc)
 docs/features/77-locale-foundation.md                                  | Point ADR at checklist
 mkdocs.yml                                                             | Nav: Add a locale
 _bmad-output/planning-artifacts/prds/.../prd.md                        | NFR-7 + exec summary
 _bmad-output/planning-artifacts/epics.md                               | NFR-7
 _bmad-output/planning-artifacts/implementation-readiness-report-*.md   | NFR-7
 _bmad-output/.../ARCHITECTURE-SPINE.md                                 | NFR-7 row
 _bmad-output/implementation-artifacts/sprint-status.yaml               | 8-7 → done
 frontend/src/i18n/index.js                                             | localeLabelKey()
 frontend/src/App.jsx                                                   | Registry-driven switcher labels
 src/adapters/ai/client.py                                              | Sentiment/neighbourhood template dicts
 src/tests/unit/test_locale_registry_hygiene.py                         | NEW — spot-check
```

## New Dependencies

None.

## How to Test

1. Unit hygiene + existing AI template coverage:
   ```bash
   bash scripts/agent/validate.sh fast
   ```
2. Full gate before merge:
   ```bash
   bash scripts/agent/validate.sh all
   ```
3. Manual: open [Add a locale](../i18n/add-a-locale.md) and walk the checklist against the current `en` / `pt-BR` tree; confirm NFR-7 in the PRD no longer says second locales are deferred.

## Notes / Follow-ups

- Checklist: [`docs/i18n/add-a-locale.md`](../i18n/add-a-locale.md).
- Story docs: `77` foundation · `78` audit · `79` full catalog · `80` filters · `81` semantic · `82` AI tags.
- Epic parent: [BIN-63](https://linear.app/felipelrib/issue/BIN-63). Optional retrospective: `epic-8-retrospective` in sprint-status.
- Scrapers may still send `Accept-Language: pt-BR` to platforms — that is site HTTP, not product UI locale.
