# ADR 0002: Cursor Single-Agent Development Workflow

**Status:** Accepted
**Date:** 2026-07-23
**Supersedes:** [ADR 0001 — Dual-Model Development](0001-dual-model-development.md)

## Decision

AI-assisted development for Imoveis uses a **single Cursor agent** that plans and implements in one flow, gated by committed `scripts/agent/` tooling:

1. **Plan** — Cursor Plan mode for non-trivial work.
2. **Implement** — Same agent executes with TDD.
3. **Validate** — `bash scripts/agent/validate.sh …`
4. **PR + babysit** — only for **feature / merge-bound** work (`finish-feature.sh --pr`).
5. **Close out** — Linear Done + `docs/features/` for shipped features.
6. **Harness retrospect** — update **local** Cursor rules/skills when a session exposes a durable gap.

**Punctual asks** (tiny fixes, harness tweaks, questions) do **not** require a PR.

Cursor rules/skills stay **local** (workspace `.cursor/`, gitignored). Global hygiene: `~/.cursor/rules/agent-hygiene.mdc`. Shared, reviewable gates stay in git under `scripts/agent/` and `.github/workflows/`.

## Context

ADR 0001 used Planner + Implementer dual-model. Cursor Plan/Agent mode replaces that. Committing `.cursor/` to the remote is optional for teams; for this solo harness, local config avoids PR noise for process tweaks.

CI suites (`lint`, `unit`, `integration`, `contract`, `scrapers`, `e2e`, `security-scan`) run **independently in parallel**. They test different layers; serial `needs:` chains only slowed feedback. Merge still requires all required checks green.

## Consequences

- Cline `.clinerules/` / `.cline/` removed.
- Scraper HTML cassettes + merge-blocking live dry-run (`scrapers` job); agents refresh cassettes on HTML drift.
- Harness wording iterates locally via `harness-retrospect` without forcing PRs.

## Related

Product planning / solutioning (PRD, architecture, epics) may use **BMad Method**; see [ADR 0003 — BMad Planning Bridge](0003-bmad-planning-bridge.md). That does **not** revive dual-model implementation — merge gates remain this ADR.

## Alternatives considered

1. Dual-model Planner/Implementer in Cursor — rejected (redundant with Plan mode).
2. Commit `.cursor/` to the repo — rejected for this project (local is enough; scripts/CI stay shared).
3. Keep lint as a hard prerequisite for all jobs — rejected (unnecessary serialization).
