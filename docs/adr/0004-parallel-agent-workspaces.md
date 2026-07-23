# ADR 0004: Parallel Agent Workspaces

**Status:** Accepted  
**Date:** 2026-07-23  
**Related:** [ADR 0002 — Cursor Single-Agent Workflow](0002-cursor-single-agent-workflow.md)

## Decision

Multiple Cursor agents may work on **different features in parallel**. Isolation is **opt-in when needed**, not mandatory for every feature:

| Situation | Workspace |
|-----------|-----------|
| Primary checkout **idle** (on `main`/`master`, clean) | **Solo** — `setup-branch.sh` in the primary tree |
| Primary **busy** (feature branch checked out and/or dirty) | **Parallel** — sibling git worktree via `setup-worktree.sh` |
| Explicit | `--force-worktree` / `--force-branch` on `setup-workspace.sh` |

**Entry point:** `bash scripts/agent/setup-workspace.sh <slug>` (auto-detects).  
**Status:** `bash scripts/agent/workspace-status.sh`.

**Idle invariant:** after `finish-feature.sh` on the primary checkout, return to `main` so the next agent can detect a free primary. Worktree finishes leave primary alone; use `teardown.sh --remove` to drop the worktree.

**Worktree location:** sibling directories `../<repo>-wt-<slug>` (not nested `.worktrees/`, which was root-owned and confused small agents). Port registry: `.agent-workspaces/registry.tsv` on the primary. Each worktree gets `.env.local` with unique ports + `COMPOSE_PROJECT_NAME`; start stack with `run-services.sh`.

After creating a worktree, agents must **`move_agent_to_root`** (or `cd`) into that path before editing.

This does **not** revive ADR 0001 dual-model Planner/Implementer. Each agent is still a single Plan→Implement session; parallelism is across *tasks*, not within one task.

## Context

Worktrees were removed (2026-07-10) because cheap Act models got lost across directories. Cursor agents are stronger and we already use sibling worktrees ad hoc (`imoveis-wt-vite-react`). Parallel product work (BMad planning + feature coding) needs a detectable, scripted path.

## Consequences

- Prefer `setup-workspace.sh` over calling `setup-branch.sh` directly for merge-bound work.
- Solo agents must not leave the primary parked on a feature branch after finish.
- Parallel stacks must not share default Compose project / ports.

## Alternatives considered

1. Always use worktrees — rejected (extra friction for solo; historically confused agents).
2. Nested `.worktrees/<slug>` — rejected (root ownership failures; harder mental model).
3. Shared checkout with careful file locking — rejected (git HEAD races are unrecoverable).
