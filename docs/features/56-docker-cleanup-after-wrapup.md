# docker-cleanup-after-wrapup — Prune temp Docker resources after every feature finish

> Feature branch: `feat/docker-cleanup-after-wrapup` · Linear: n/a · Status: implemented

## Problem

Feature development leaves stopped containers, dangling images, and build cache on the
host. Agents finished tasks without a consistent cleanup step, so Docker disk usage grew
across sessions. Operators also risked reaching for `docker system prune --volumes`, which
wipes the primary Postgres volume (see feature 45 / BIN-60).

## Approach

- Add `scripts/agent/docker-cleanup.sh`: prune **stopped** containers, **dangling** images,
  and builder cache only — never named volumes, never a running Compose stack.
- Call it from `finish-feature.sh` after merge cleanup and from `teardown.sh` after compose
  down. Worktree teardowns also pass `--rmi local` so disposable project images go away.
- Document the gate in README / setup / ADR 0004 and in local feature-pipeline / babysit /
  core rules so manual wrap-ups still run the script.

## Changes

Files touched:

```
 scripts/agent/docker-cleanup.sh              | NEW — safe temp container/image prune
 scripts/agent/finish-feature.sh              | Call docker-cleanup after merge cleanup
 scripts/agent/teardown.sh                    | Worktree --rmi local + always docker-cleanup
 docs/adr/0004-parallel-agent-workspaces.md   | Document wrap-up Docker prune
 docs/setup.md / README.md                    | Day-to-day command + workflow note
 docs/features/56-docker-cleanup-after-wrapup.md | NEW — this doc
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/docker-cleanup.sh --dry-run
bash scripts/agent/validate.sh all
```

Manual:

1. Confirm `docker volume ls | grep postgres` is unchanged after a real (non-dry-run) cleanup.
2. Confirm a running primary stack is still up after `docker-cleanup.sh` (script does not `compose down`).

## Notes / Follow-ups

- Local Cursor rules/skills (`.cursor/`, gitignored) also encode this wrap-up step.
- Nuclear image wipe remains interactive via `./scripts/clean.sh --all` only.
- **Follow-up (feature 62):** also prune unused *tagged* feature/worktree Compose images
  (`feat-*`, `imoveis-wt-*`, …) while keeping the primary `imoveis-*` stack and base images.
