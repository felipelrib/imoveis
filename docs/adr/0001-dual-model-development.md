# ADR 0001: Dual-Model AI Development Strategy

**Status:** Superseded by [ADR 0002 — Cursor Single-Agent Workflow](0002-cursor-single-agent-workflow.md)
**Date:** 2026-07-20
**Context:** Development workflow for the Imoveis project

## Decision

~~All AI-assisted development uses a **Planner + Implementer** dual-model strategy.~~

This ADR is historical. The project now uses a single Cursor agent with Plan mode, `scripts/agent/` validation gates, and PR babysitting (see ADR 0002).

## Original decision (archived)

- **Planner** (strong model): produced a detailed `implementation_plan.md`. Did NOT write implementation code.
- **Implementer** (cheaper/faster model): executed the plan step by step.

## Context

Single-model development with a strong model was considered expensive; dual-model optimised cost while keeping planning quality.

## Consequences (historical)

- `.clinerules/rules.md` defined Planner vs Implementer roles.
- `feature-pipeline` had Phase 1 / Phase 2 handoff markers.

These artifacts were migrated to `.cursor/rules/` and `.cursor/skills/` under ADR 0002.
