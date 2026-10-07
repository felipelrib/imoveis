# ADR 0007: Tiered local gate, hook-enforced push, no merge script

**Status:** Accepted
**Date:** 2026-10-07
**Supersedes in part:** [ADR 0002](0002-cursor-single-agent-workflow.md) (the `finish-feature.sh` merge gate), [ADR 0004](0004-parallel-agent-workspaces.md) (sibling worktrees, port registry, teardown)
**Input:** `_bmad-output/planning-artifacts/research/harness-review-2026-10-07.md`

## Decision

1. **One gate, chosen by the diff.** `python scripts/agent/validate.py` classifies the change (`docs` / `fast` / `frontend` / `backend` / `full`, plus path-triggered scraper, AI and harness-test gates) and runs only that tier. It is Python, runs from any shell on any OS, and keeps the one invariant that earned its keep: validation never touches the primary compose project — DB/Redis come from the ephemeral `<workspace>-test` stack it builds itself. On success with a clean tree it writes a stamp `.run/validated/<tree-sha>.<tier>` in the primary checkout.
2. **Enforcement is hooks, not prose.** `.claude/hooks/guard.py` (PreToolUse, committed) denies: `git push` to `main` whose HEAD tree lacks a stamp for the required tier; any force push; `docker compose` lifecycle commands against the primary project, `docker system prune`, `docker volume rm`; edits to `.env.local` and `configs/anchors.local.yaml`. A hook decision holds in every permission mode, including the bypass mode bmad-loop sessions run in. `auto_push.py` (Stop) pushes a clean, stamped, ahead-and-not-behind `main`, so origin never lags a local merge again.
3. **Shipping is 150 lines, not 322.** `python scripts/agent/ship.py` = refuse dirty tree / `bmad-loop/*` branch → merge `origin/main` in → feature-doc check for story-key branches → `validate.py` → squash-merge → stamp re-check → push → delete branch. No Docker teardown, no image pruning, no worktree logic, no branch-type validation.
4. **Retired:** `finish-feature.sh`, `setup-branch.sh`, `setup-workspace.sh`, `setup-worktree.sh`, `workspace-status.sh`, `teardown.sh`, `run-services.sh`, `test-stack.sh`, `ensure-test-db.sh`, `validate-scrapers.sh`, `validate-ai.sh`, `lint.sh`, `setup-tools.sh`, `docker-compose.ci.yml`, the `.agent-workspaces` port registry and `lib.sh`'s worktree/port/branch helpers. History keeps them at `ef193e86`. Parallel work uses bmad-loop's own worktrees or Claude Code's native `--worktree`.
5. **Moved out of the merge path:** `scripts/ops/audit-deps.sh` runs in the nightly GitHub workflow; `scripts/ops/docker-cleanup.sh` is an occasional operator task.
6. **One instruction file.** `AGENTS.md` (committed, read natively by Claude Code, Codex, Cursor, Copilot) carries the rules; `CLAUDE.md` imports it and adds Claude-only mechanics. The Cursor mirror and `docs/ai/` mirrors are deleted.
7. **bmad-loop** keeps its own squash-merge; its `[verify]` runs the backend tier; the Stop hook and `ship.py` cover the push. `_bmad/custom/` overrides are reduced to the three enforced rules and renamed for BMAD ≥ 6.11 (`bmad-build`, `bmad-build-auto`), keeping the legacy copies while shims are installed.

## Context

The 2026-10-07 harness review measured the previous shape: 20 bash scripts (3,089 lines), 16% of all commits touching harness files, half of the commits on `scripts/agent/` fixing the harness itself, ≥30 of ~45 troubleshooting bullets caused by the harness, a docs-only finish spending ~75 s on Docker housekeeping, a 6–8 minute full gate for one-file changes, zero `PreToolUse` hooks (every "never" advisory), two merge machineries (script vs orchestrator) that had raced twice, and five hand-synced instruction files. None of Felipe's other projects has a merge script; Anthropic's and BMAD's guidance put enforcement in hooks and procedures in skills, and bmad-loop expects project-local verify commands but never a local merge/push script.

## Consequences

- Measured on the Windows host after the cut: docs tier ≈ 11 s, fast tier ≈ 75 s (pre-commit 17 s + unit 55 s under pytest-xdist, harness-marked script tests excluded), full gate dominated by the ~14 min serial harness tests that run only when scripts change.
- Unit tests that spawn shell scripts carry the `harness` marker; `validate.py` runs them when `scripts/`, `.claude/` or the gate tests change, and in the full tier.
- `src/tests/unit/test_claude_guard.py` is the mutation probe: every rule the guard enforces has a planted violation that must be denied and a benign neighbour that must pass.
- The primary-stack mutual exclusion for migrations (`migrate-primary.sh`, ADR 0006) is unchanged.
- The GitHub-platform hard stop (branch protection + PR + CI) was considered and not adopted: the repo is private on the Free plan (no branch protection), and the July CI era cost 20 CI-only fix commits before it was retired. It remains the fallback if hook enforcement proves insufficient.
