# Epics & stories sync — v0.5 delivery backlog from PRD + architecture

> Feature branch: `feat/bin-35-epics-stories-sync` · Linear: `BIN-35` · Status: implemented

## Problem

v0.5 needed actionable epics/stories from the retrofit PRD + architecture, with Future backlog seeds (BIN-19..23) promoted instead of a parallel invented backlog. BIN-34’s architecture stack seed was also stale vs main (React 19 / Vite 8 / pgvector).

## Approach

- Ran `bmad-create-epics-and-stories` → `_bmad-output/planning-artifacts/epics.md`
- Five user-value epics (FR-18..22); FR-1..17 baseline; FR-23 deferred
- Refreshed architecture Stack seed before extraction
- Promoted BIN-19..23 to v0.5 epic parents; created 15 child story issues (BIN-41..55)

## Changes

```
_bmad-output/planning-artifacts/epics.md                 | NEW — FR inventory, 5 epics, 15 stories, Linear map
.../architecture-imoveis-2026-07-23/ARCHITECTURE-SPINE.md | Stack/SoR refresh (React 19, Vite 8, pgvector)
.../COMPANION-architecture-delta.md                      | Note stack refresh
.../architecture-imoveis-2026-07-23/.memlog.md           | BIN-35 prelude event
docs/architecture.md                                     | React 19 / Vite 8 / pgvector wording
```

## New Dependencies

None.

## How to Test

1. Open `_bmad-output/planning-artifacts/epics.md` — 5 epics, 15 stories, Linear Sync table.
2. In Linear v0.5: BIN-19..23 are epic parents; children BIN-41..55 present.

## Notes / Follow-ups

- Next planning: BIN-36 `bmad-check-implementation-readiness` (fresh chat)
- Then sprint planning / `bmad-create-story` + feature-pipeline for delivery stories
- Open product questions remain in the PRD (digest channel, auth profiles, polygon source, FR-23)
