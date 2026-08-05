# ADR 0004: Parallel Agent Workspaces

**Status:** Accepted
**Date:** 2026-07-23
**Related:** [ADR 0002 — Cursor Single-Agent Workflow](0002-cursor-single-agent-workflow.md)

## Decision

> **Amended by the v0.13-fu1 harness surgery (2026-08-05):** still accepted, with three behavioural updates — (1) `validate.sh` no longer starts/migrates any primary services; each workspace's test DB/Redis come from its own ephemeral `<workspace>-test` compose project (`test-stack.sh`), so port pressure on the shared primary is gone during validation; (2) `teardown.sh` now **fails closed**: it reads `COMPOSE_PROJECT_NAME` from `.env.local` only and refuses ambiguous or primary identities (`--primary` = explicit operator override, volumes never wiped); (3) `finish-feature.sh` merges locally (squash) and pushes `main` — there is no PR step. The idle invariant, sibling-worktree layout, and port registry stand.

Multiple Cursor agents may work on **different features in parallel**. Isolation is **opt-in when needed**, not mandatory for every feature:

| Situation | Workspace |
|-----------|-----------|
| Primary checkout **idle** (on `main`/`master`, clean) | **Solo** — `setup-branch.sh` in the primary tree |
| Primary **busy** (feature branch checked out and/or dirty) | **Parallel** — sibling git worktree via `setup-worktree.sh` |
| Explicit | `--force-worktree` / `--force-branch` on `setup-workspace.sh` |

**Entry point:** `bash scripts/agent/setup-workspace.sh <slug>` (auto-detects).
**Status:** `bash scripts/agent/workspace-status.sh`.

**Idle invariant:** after `finish-feature.sh` on the primary checkout, return to `main` so the next agent can detect a free primary. Worktree finishes leave primary alone; use `teardown.sh --remove` to drop the worktree.

**Worktree location:** sibling directories `../<repo>-wt-<slug>` (not nested `.worktrees/`, which was root-owned and confused small agents). Port registry: `.agent-workspaces/registry.tsv` on the primary; allocation is race-safe via `flock` on `.agent-workspaces/.ports.lock` (mkdir lock fallback). Each worktree gets `.env.local` with unique Compose ports (`POSTGRES`/`REDIS`/`API`/`FRONTEND`) plus a distinct `PLAYWRIGHT_PORT` (5177–5299, not shared with Compose FE); start stack with `run-services.sh`. `validate.sh` / `finish-feature.sh` source `.env.local` and, if `PLAYWRIGHT_PORT` is unset, probe for a free port before E2E.

**Postgres persistence:** scraped data should live on the **primary** Compose project (`COMPOSE_PROJECT_NAME=imoveis`). `teardown.sh` keeps volumes for that project unless `--volumes` is passed; worktree projects still drop their private volumes by default (and remove Compose-built local images via `--rmi local`). Prefer `./scripts/stop.sh` / `./scripts/clean.sh` (no `--volumes`) over volume-wiping flags for routine stops. After wrap-up, `finish-feature.sh` / `teardown.sh` always run `scripts/agent/docker-cleanup.sh` to prune stopped containers, dangling images, unused feature/worktree tagged images (`feat-*`, `imoveis-wt-*`, …), and build cache — keeping the primary `imoveis-*` stack and third-party bases, and never named volumes.

After creating a worktree, agents must **`move_agent_to_root`** (or `cd`) into that path before editing.

**Harness (`.cursor/`):** worktrees symlink `.cursor/` from the primary checkout (same pattern as `.venv`), rather than copying it, so harness retrospect edits survive `teardown.sh --remove` and concurrent agents do not drift. Legacy real `.cursor/` directories under a worktree are replaced safely (`rm -rf` only when the path is exactly that worktree's `.cursor` directory, then `ln -sfn`).

This does **not** revive ADR 0001 dual-model Planner/Implementer. Each agent is still a single Plan→Implement session; parallelism is across *tasks*, not within one task.

## Context

Worktrees were removed (2026-07-10) because cheap Act models got lost across directories. Cursor agents are stronger and we already use sibling worktrees ad hoc (`imoveis-wt-vite-react`). Parallel product work (BMad planning + feature coding) needs a detectable, scripted path.

## Consequences

- Prefer `setup-workspace.sh` over calling `setup-branch.sh` directly for merge-bound work.
- Solo agents must not leave the primary parked on a feature branch after finish.
- Parallel stacks must not share default Compose project / ports (including `PLAYWRIGHT_PORT`; do not conflate with Compose `FRONTEND_PORT`).

## Alternatives considered

1. Always use worktrees — rejected (extra friction for solo; historically confused agents).
2. Nested `.worktrees/<slug>` — rejected (root ownership failures; harder mental model).
3. Shared checkout with careful file locking — rejected (git HEAD races are unrecoverable).
