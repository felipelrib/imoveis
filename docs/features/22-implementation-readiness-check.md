# Implementation readiness check — planning cohesion before v0.5 delivery

> Feature branch: `feat/bin-36` · Linear: `BIN-36` · Status: implemented

## Problem

After PRD, architecture, and epics/stories existed, v0.5 still needed a formal readiness pass so gaps in FR coverage, UX alignment, and epic quality were either fixed or tracked before sprint planning and implementation.

## Approach

- Ran `bmad-check-implementation-readiness` end-to-end → readiness report under planning artifacts
- Confirmed assessment set: PRD + addendum, architecture spine + companion, `epics.md` (no UX contract — brownfield)
- Extracted FR-1..23 / NFR-1..7; validated 100% FR coverage (baseline + five delivery epics + deferred FR-23)
- Tracked non-blocking majors on BIN-20 / BIN-37 / BIN-19; numbered NFR-8 in PRD §8 to match epics

## Changes

```
_bmad-output/planning-artifacts/implementation-readiness-report-2026-07-23.md | NEW — full readiness assessment
_bmad-output/planning-artifacts/prds/prd-imoveis-2026-07-23/prd.md            | Numbered NFR-1..8 (add NFR-8)
docs/features/22-implementation-readiness-check.md                           | NEW — this feature doc
```

## New Dependencies

None.

## How to Test

1. Open `_bmad-output/planning-artifacts/implementation-readiness-report-2026-07-23.md` — status **READY**, FR coverage 100%, no critical epic defects.
2. Confirm Linear comments on BIN-19, BIN-20, BIN-37 carry the follow-ups.
3. Confirm PRD §8 lists NFR-1..NFR-8.

## Notes / Follow-ups

- **Next required:** BIN-37 / `[SP]` `bmad-sprint-planning` (fresh chat) — honour Epic 1 before Epic 4 for AD-12 projection.
- Before Epic 2 Story 2.3: split/sequence owner migration vs personalization surfaces (comment on BIN-20).
- Optional focused `bmad-ux` if Compare UI ambiguity blocks Epic 1 (comment on BIN-19).
- **BUG (Low):** Epic 2 Linear child id order lists BIN-46 before BIN-45 — verify titles match stories 2.1–2.3.

