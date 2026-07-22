# ADR 0001: Dual-Model AI Development Strategy

**Status:** Accepted
**Date:** 2026-07-20
**Context:** Development workflow for the Imoveis project

## Decision

All AI-assisted development uses a **Planner + Implementer** dual-model strategy:

- **Planner** (strong model, e.g. DeepSeek v4 Pro, Claude 3.5 Sonnet): Reads the Linear issue and codebase, produces a detailed `implementation_plan.md`. Does NOT write implementation code.
- **Implementer** (cheaper/faster model): Reads the plan and executes it step by step. Does NOT make architectural decisions or refactor beyond scope.

## Context

Single-model development with a strong model is expensive and wastes tokens on mechanical implementation. Single-model with a cheap model produces poor architectural decisions and scope creep.

The dual-model approach optimises cost while maintaining quality:
- Planning consumes ~5-10% of total tokens but determines 90% of the outcome quality.
- Implementation is mechanical enough for a cheaper model when the plan is sufficiently detailed.

## Consequences

### Rules Structure
- `.clinerules/rules.md` contains explicit role definitions and the mandatory `implementation_plan.md` format.
- The plan format must be detailed enough that the Implementer never needs to make architectural decisions (exact file paths, function signatures, test names).

### Skill Design
- `feature-pipeline` skill has explicit Phase 1 (Planner) and Phase 2 (Implementer) markers.
- Phase 1 ends with "STOP HERE if using Planner + Implementer mode" to support handoff.

### Validation
- Implementer must run `validate.sh` after implementation — no skipping.
- If validation fails, Implementer fixes and re-runs (does not escalate to Planner unless the issue is architectural).

## Alternatives Considered

1. **Single strong model for everything**: Too expensive for a personal project.
2. **Single cheap model**: Poor planning leads to scope creep and rework.
3. **MCP-only automation (no skills)**: Skills provide reusable workflows that reduce model errors.
