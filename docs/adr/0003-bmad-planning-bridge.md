# ADR 0003: BMad Method Planning Bridge

**Status:** Accepted
**Date:** 2026-07-23
**Related:** [ADR 0002 — Cursor Single-Agent Workflow](0002-cursor-single-agent-workflow.md)

## Decision

Imoveis uses **BMad Method** for product planning and solutioning (PRD, architecture spine, epics/stories, implementation readiness, sprint planning). **Implementation and merge gates stay on ADR 0002**: single Cursor agent, Linear as execution tracker, committed `scripts/agent/` validate / finish-feature / babysit.

| Concern | Owner |
|---------|--------|
| What / why / architecture spine / epic breakdown | BMad (`_bmad/`, `_bmad-output/`, `.agents/skills/`) |
| Ticket status, branch, TDD, CI, PR | Linear + feature-pipeline + `scripts/agent/` |
| Local agent habits | `.cursor/` rules/skills (gitignored), including `imoveis-planning-bridge` |

BMad agent personas (PM, Architect, Dev, etc.) are **workflow skills**, not a return to ADR 0001 dual-model Planner/Implementer.

## Context

MVP milestones v0.1–v0.4 shipped without an in-repo PRD. Beyond-MVP work needed a durable planning spine. BMad Method track fits a brownfield product: retrofit requirements, ratify architecture, then epic delivery.

## Story → ship (execution handoff)

After readiness + sprint planning:

1. Optional `bmad-create-story` (fresh chat) → story file under `_bmad-output/implementation-artifacts/`.
2. Ensure Linear child exists (v0.5: BIN-41..55 under epic parents BIN-19..23).
3. Local `feature-pipeline`: `setup-workspace.sh` → TDD → `validate.sh` (+ scraper/AI gates when relevant) → `finish-feature.sh --pr` → babysit → Linear Done → `docs/features/`.
4. Keep `_bmad-output/implementation-artifacts/sprint-status.yaml` in sync (never downgrade statuses).

Recommended v0.5 delivery order (from readiness): **Epic 1 → 2 → 3|5 → 4** so AD-12 property projection lands before export/digest.

## Consequences

- Commit `_bmad/`, `.agents/skills/`, and `_bmad-output/` planning **and** implementation artifacts (`sprint-status.yaml`); gitignore personal `*.user.toml` and local `.cursor/`.
- Run each major BMad workflow in a **fresh chat**.
- After epics exist, sync stories to Linear before coding; do not invent a parallel backlog ahead of the PRD.
- Optional `bmad-dev-story` / `bmad-code-review` may assist implementation, but cannot skip `validate.sh` or CI.
- Local bridge skill: `.cursor/skills/imoveis-planning-bridge`; execution skill: `.cursor/skills/feature-pipeline`.

## Alternatives considered

1. Replace feature-pipeline with BMad story cycle only — rejected (loses project-specific scraper/AI/CI gates).
2. Skip BMad; keep Linear-only planning — rejected (no PRD/architecture cohesion for v0.5+).
3. Enterprise BMad track — deferred; Method track is enough for current scope.
