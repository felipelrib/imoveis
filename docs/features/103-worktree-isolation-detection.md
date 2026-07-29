# Worktree Isolation Detection — stop scripts/agent from creating redundant nested worktrees

> Feature branch: `fix/worktree-isolation-detection` · Linear: N/A (harness infra, discovered during BIN-128 tech-debt epic parallel execution) · Status: implemented

## Problem

`scripts/agent/lib.sh` resolves `PRIMARY_ROOT` via `git rev-parse --git-common-dir`, which always points at the *original* checkout regardless of the current working tree. `setup-workspace.sh`'s solo-vs-parallel decision only ever checked `PRIMARY_ROOT`'s busy/idle state — it never checked whether the *current* session was already inside a dedicated, isolated worktree.

Concretely: a session already isolated by the calling product's own native mechanism (Claude Code's `EnterWorktree` tool / `Agent` tool `isolation: "worktree"`, or Cursor's background-agent dispatch) — i.e. already running inside its own worktree, on its own branch, before `scripts/agent/*` ever ran — would still see "primary busy" (true whenever other parallel agents are active, which is the normal case) and try to `git worktree add` a **second, sibling** worktree relative to primary. This is redundant (the session was already isolated) and, for Claude Code specifically, tries to relocate the session outside the product's own sanctioned worktree root (`.claude/worktrees/`), which requires an explicit permission prompt for every single invocation (`"a model-supplied worktree outside .claude/worktrees/"`).

Reproduced directly: running `bash scripts/agent/setup-workspace.sh <slug>` from inside a `.claude/worktrees/<name>` session created a brand-new `../imoveis-wt-<slug>` sibling worktree instead of recognizing the session was already isolated.

## Approach

- `lib.sh` already had `in_linked_worktree()` (true when `REPO_ROOT != PRIMARY_ROOT`) but nothing used it for this decision.
- `setup-workspace.sh` now short-circuits to `setup-worktree.sh` immediately when `in_linked_worktree()` is true (unless `--force-branch` is explicitly passed), instead of computing solo/parallel MODE from the primary's state.
- `setup-worktree.sh` itself detects the same condition: when already in a linked worktree, it skips `git worktree add` entirely, sets `WORKTREE="$REPO_ROOT"`, and (if the current branch isn't already Conventional-Branch-compliant and doesn't collide with an existing branch) renames it in place to match the requested slug. Port allocation, `.env.local` writing, and `.venv`/`.cursor`/`.claude` symlinking then proceed exactly as before, just targeting the current directory instead of a new sibling path.
- When NOT already isolated (the original, still-common case — a primary session choosing to fan out into a new worktree), behavior is unchanged: a sibling worktree is created exactly as before.

## Changes

Files touched:

```
scripts/agent/setup-workspace.sh                | short-circuits to setup-worktree.sh when already in a linked worktree
scripts/agent/setup-worktree.sh                  | skips git worktree add + branch rename logic when already isolated; conditional "next steps" hint
src/tests/unit/test_setup_worktree_isolation.py  | NEW — regression coverage: already-isolated (no nested worktree, .env.local written, branch renamed) vs not-isolated (unchanged sibling-creation behavior)
docs/harness-troubleshooting.md                  | documents the already-isolated behavior under Workspace setup
.claude/skills/feature-pipeline/SKILL.md         | step 3 updated (local, gitignored — not part of this PR diff)
.cursor/skills/feature-pipeline/SKILL.md         | step 3 updated (local, gitignored — not part of this PR diff)
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
```

`test_setup_worktree_isolation.py` builds real temporary git repos + linked worktrees (no mocking of git itself) and exercises both code paths: already-isolated (no new worktree created, `.env.local` written in place, branch renamed) and not-isolated (unchanged sibling-worktree creation, matching prior behavior byte-for-byte).

Also dogfooded live: ran `bash scripts/agent/setup-workspace.sh` from inside this very Claude-native worktree (which had no `.venv`/`.env.local` since it was created directly via `EnterWorktree`, bypassing the setup scripts) — confirmed it configured the environment in place with no nested worktree and no permission prompt.

## Notes / Follow-ups

- Discovered while parallelizing work on the BIN-128 tech-debt remediation epic (v0.10 milestone) — background agents dispatched via `Agent` `isolation: "worktree"` hit a permission prompt each time their own `setup-workspace.sh` call tried to create a redundant sibling worktree.
- Cursor's background-agent dispatch mechanics were not directly testable from this session (no Cursor tooling available here); the fix is conservative — it only changes behavior when `in_linked_worktree()` is true, which is a pure git-state check independent of which tool created the worktree, so it should behave correctly under Cursor's dispatch model too if a background agent lands in its own worktree the same way.
