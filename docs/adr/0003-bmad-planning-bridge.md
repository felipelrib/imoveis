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

## Consequences

- Commit `_bmad/`, `.agents/skills/`, and `_bmad-output/` planning artifacts; gitignore personal `*.user.toml`.
- Run each major BMad workflow in a **fresh chat**.
- After epics exist, sync stories to Linear before coding; do not invent a parallel backlog ahead of the PRD.
- Optional `bmad-dev-story` / `bmad-code-review` may assist implementation, but cannot skip `validate.sh` or CI.

## Alternatives considered

1. Replace feature-pipeline with BMad story cycle only — rejected (loses project-specific scraper/AI/CI gates).
2. Skip BMad; keep Linear-only planning — rejected (no PRD/architecture cohesion for v0.5+).
3. Enterprise BMad track — deferred; Method track is enough for current scope.
