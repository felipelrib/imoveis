# Sprint planning + harness bridge — BMad ↔ feature-pipeline

> Feature branch: `feat/bin-37-sprint-planning-harness-bridge` · Linear: `BIN-37` · Status: implemented

## Problem

After readiness (BIN-36), v0.5 needed a sprint-status tracker and an explicit handoff from BMad planning workflows into Imoveis execution gates (`feature-pipeline` / `validate.sh` / `finish-feature.sh`), including fresh-chat-per-workflow discipline.

## Approach

- Ran `bmad-sprint-planning` over `_bmad-output/planning-artifacts/epics.md` → `sprint-status.yaml`
- Encoded delivery order from readiness: Epic 1 → 2 → 3|5 → 4 (AD-12 projection before export)
- Extended ADR 0003 with story→ship steps; restored/updated local `.cursor` skills (`feature-pipeline`, bridge, core rule)
- Did not replace shared scripts — BMad plans; Linear + `scripts/agent/` ship

## Changes

```
_bmad-output/implementation-artifacts/sprint-status.yaml | NEW — 5 epics, 15 stories, retros
docs/adr/0003-bmad-planning-bridge.md                    | Story→ship handoff + sprint-status
docs/features/23-sprint-planning-harness-bridge.md       | NEW — this feature doc
.cursor/skills/feature-pipeline/SKILL.md                 | LOCAL — restored + BMad bridge
.cursor/skills/imoveis-planning-bridge/SKILL.md          | LOCAL — sprint-status / workspace
.cursor/rules/imoveis-core.mdc                           | LOCAL — BMad vs execution split
```

## New Dependencies

None.

## How to Test

1. Open `_bmad-output/implementation-artifacts/sprint-status.yaml` — 5 epics, 15 stories, all `backlog` (no story files yet), retrospectives `optional`.
2. Confirm ADR 0003 has the Story → ship section and points at `feature-pipeline`.
3. Confirm local skills exist under `.cursor/skills/{feature-pipeline,imoveis-planning-bridge}/`.

## Notes / Follow-ups

- Next: story cycle — `bmad-create-story` (fresh chat) for `1-1-canonical-property-projection-for-decisioning` → implement via feature-pipeline (Linear BIN-41).
- Before Epic 2 Story 2.3: split/sequence owner migration (BIN-20 follow-up from readiness).
- Optional thin `bmad-ux` if Compare UI blocks Epic 1 (BIN-19).
- PR: https://github.com/felipelrib/imoveis/pull/22
