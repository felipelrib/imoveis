# semantic-search-reconcile — Close BIN-18 status / docs / scope drift

> Feature branch: `feat/bin-38-reconcile-bin-18-semantic-search` · Linear: `BIN-38` · Status: implemented

## Problem

BIN-18 (free-text search via embeddings) was marked In Progress with partial implementation and no `docs/features/` entry when BIN-38 was filed. After the retrofit PRD, planning artifacts still referenced drift (partial / In Progress), and FR-15 hygiene needed an explicit ship-or-split decision.

## Approach

- Audited main after PR [#16](https://github.com/felipelrib/imoveis/pull/16): pgvector migration, embed pipeline, `GET /properties?q=`, admin backfill, Properties search box, unit/integration tests, and `docs/features/20-semantic-search.md` are all present.
- Compared against PRD FR-15 / epics baseline: no remaining product scope to promote into a v0.5 delivery story.
- Chose **mark complete + close hygiene** (not split) — Linear BIN-18 already Done; remaining work is doc/status reconcile only.

## Changes

```
docs/features/24-semantic-search-reconcile.md                              | NEW — this feature doc
docs/features/20-semantic-search.md                                        | Note BIN-38 reconcile closed
_bmad-output/planning-artifacts/prds/prd-imoveis-2026-07-23/prd.md         | FR-15 / §6.2 reconcile Done
_bmad-output/planning-artifacts/prds/prd-imoveis-2026-07-23/addendum.md    | FR-15 mapping updated
_bmad-output/planning-artifacts/epics.md                                   | FR-15 hygiene closed
_bmad-output/planning-artifacts/implementation-readiness-report-2026-07-23.md | BIN-38 Done notes
_bmad-output/planning-artifacts/bmad-help-session.md                       | Superseded backlog line
_bmad-output/planning-artifacts/NEXT-bmad-prd-prompt.md                    | Historical BIN-18 drift note
```

## New Dependencies

None.

## How to Test

1. Confirm `docs/features/20-semantic-search.md` and this doc exist.
2. Confirm Linear BIN-18 is Done and description reflects shipped FR-15 (not the old “idea” text).
3. Grep planning artifacts: no live “BIN-18 In Progress / partially implemented” claims outside historical hand-off context.

## Notes / Follow-ups

- **Decision:** No new Linear story for semantic-search gaps. Known limits stay in `20-semantic-search.md` (null embeddings excluded from `q=`, re-embed on non-noop scrape).
- UX polish beyond the existing Search control was not required for FR-15; readiness WARNING (Low) about missing UX artifact is accepted for brownfield baseline.
- Related: BIN-18, PR [#16](https://github.com/felipelrib/imoveis/pull/16), FR-15 in retrofit PRD.
