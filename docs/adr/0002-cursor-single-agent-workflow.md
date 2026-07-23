# ADR 0002: Cursor Single-Agent Development Workflow

**Status:** Accepted  
**Date:** 2026-07-23  
**Supersedes:** [ADR 0001 — Dual-Model Development](0001-dual-model-development.md)

## Decision

AI-assisted development for Imoveis uses a **single Cursor agent** that plans and implements in one flow, gated by project scripts and PR babysitting:

1. **Plan** — Cursor Plan mode for non-trivial work (optional `implementation_plan.md` for long tasks).
2. **Implement** — Same agent executes with TDD.
3. **Validate** — `bash scripts/agent/validate.sh all` (mirrors CI).
4. **PR** — `bash scripts/agent/finish-feature.sh --pr`.
5. **Babysit** — `.cursor/skills/babysit-pr` until CI is green and comments are triaged.
6. **Close out** — Linear Done + numbered `docs/features/` doc.

## Context

ADR 0001 split Planner and Implementer across two models for cost. Cursor’s Plan mode + Agent mode covers the same quality bar without a dual-model handoff. The expensive failure mode was skipping validation and not watching CI — fixed by mandatory `scripts/agent/` gates and the babysit skill.

## Consequences

- Rules live in `.cursor/rules/`; skills in `.cursor/skills/`.
- Global agent hygiene lives in `~/.cursor/rules/agent-hygiene.mdc`.
- Cline `.clinerules/` / `.cline/` are removed.
- Critical paths are covered by scraper HTML cassettes **and** a merge-blocking live dry-run (`scrapers` CI job). When live HTML drifts, the agent refreshes cassettes with `scripts/dev/record_scraper_cassettes.py` during babysit — there is no scheduled refresh job.

## Alternatives considered

1. Keep dual-model Planner/Implementer roles in Cursor rules — rejected as redundant with Plan mode.
2. Delete `scripts/agent/` and rely on ad-hoc commands — rejected; shared gates stay reliable.
