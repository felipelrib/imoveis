# Linear Project Overview hygiene — align Overview doc with shipped milestones

> Feature branch: `feat/bin-39-hygiene-refresh-linear-project-overview` · Linear: `BIN-39` · Status: implemented

## Problem

The Linear document **Imoveis — Project Overview & Sprint Guide** still listed v0.1–v0.4 issues as Backlog/High priority even though those milestones were at 100%. Milestone strategy for the active planning wave (v0.5) vs the Future catch-all was unclear from the overview alone.

## Approach

- Refresh the Linear Overview in place (same document ID) so history and project resource links stay intact.
- Mark v0.1–v0.4 as shipped history; put **v0.5 — BMad Planning & Next Phase** front-and-centre as the only active planning + delivery milestone.
- Keep **Future / Beyond MVP** as an explicit parking lot for unprioritized ideas (not a delivery track).
- Reinforce milestone descriptions in Linear so agents/humans do not reopen closed MVP milestones for new scope.

## Changes

Files touched:

```
docs/features/24-linear-project-overview-hygiene.md | NEW — this feature doc
```

Linear (outside git):

```
Document: Imoveis — Project Overview & Sprint Guide | refreshed milestone strategy + v0.5 epic map
Milestone: v0.5 — BMad Planning & Next Phase       | marked ACTIVE + delivery exit criteria
Milestone: Future / Beyond MVP                      | clarified as catch-all parking lot
```

## New Dependencies

None.

## How to Test

1. Open [Project Overview & Sprint Guide](https://linear.app/felipelrib/document/imoveis-project-overview-and-sprint-guide-404a0b920f1b).
2. Confirm v0.1–v0.4 are labelled shipped, not backlog.
3. Confirm v0.5 lists planning track (BIN-31 children) and delivery epics BIN-19..23 with stories BIN-41..55.
4. Confirm Future / Beyond MVP is described as a catch-all, not an active sprint.

## Notes / Follow-ups

- Overview is the source of truth in Linear; this feature doc only records that the hygiene pass happened.
- After merge, mark BIN-39 Done in Linear (done as part of feature-pipeline close-out).
- Related: BIN-31 (BMad adoption parent), BIN-38 (semantic-search reconciliation still backlog).
