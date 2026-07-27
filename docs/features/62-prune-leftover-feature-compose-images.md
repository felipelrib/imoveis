# prune-leftover-feature-compose-images — Remove unused feat/worktree images after wrap-up

> Feature branch: `feat/docker-temp-cleanup-harness` · Linear: n/a · Status: implemented

## Problem

Feature 56 already pruned stopped containers, dangling images, and build cache at wrap-up.
That was not enough: Compose leaves **tagged** images named after feature/worktree projects
(`feat-bin-*`, `fix-*`, `imoveis-wt-*`). Those sat unused for days and ate multi‑GB of disk
while the fixed primary stack (`imoveis-*`) and base images (`redis`, …) must stay.

## Approach

- Extend `docker-cleanup.sh` to delete unused temporary tagged Compose images.
- Keep primary `imoveis-*` (except `imoveis-wt-*`), third-party bases, and any image belonging
  to a Compose project that still has running containers (so parallel agents are safe).
- Extract classification helpers to `docker-cleanup-lib.sh` and lock them with a unit test.
- Reaffirm the wrap-up gate in docs + local Cursor skills/rules.

## Changes

Files touched:

```
 scripts/agent/docker-cleanup.sh                 | Also prune unused feat/wt tagged images
 scripts/agent/docker-cleanup-lib.sh             | NEW — temp vs primary image classification
 src/tests/unit/test_docker_cleanup.py           | NEW — regression for keep/remove rules
 docs/features/62-prune-leftover-feature-compose-images.md | NEW — this doc
 docs/features/56-docker-cleanup-after-wrapup.md | Point follow-up at this enhancement
 README.md / docs/setup.md / docs/adr/0004-…     | Clarify temp tagged-image prune
 scripts/agent/finish-feature.sh                 | Comment: includes tagged temp images
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh fast
bash scripts/agent/docker-cleanup.sh --dry-run
```

Manual:

1. Confirm dry-run lists `feat-*` / `imoveis-wt-*` leftovers and does **not** list `imoveis-api` / `redis`.
2. With a parallel worktree stack up, confirm that project's images are kept (`kept_for_active_projects`).
3. Confirm `docker volume ls` is unchanged after a real (non-dry-run) cleanup.
4. Confirm the primary `imoveis` stack stays up (script never `compose down`).

## Notes / Follow-ups

- Local Cursor rules/skills (`.cursor/`, gitignored) updated to describe tagged temp-image prune.
- Nuclear wipe of the primary project remains interactive via `./scripts/clean.sh --all` only.
