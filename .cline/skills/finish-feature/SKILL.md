---
name: finish-feature
description: Finish a feature by merging the branch into main, validating, tearing down the worktree, and cleaning up. Use when the user says "finish the feature", "merge and clean up", or "close out the feature".
---

# Finish Feature

This skill wraps `finish-feature.sh` — a single script that merges the feature
branch into main, validates, tears down the worktree/containers, and deletes
the branch.

## Input

- `feature_slug` (optional): if not provided, detect from the current git branch name.

## Steps

### Step 1 — Detect current branch (if slug not provided)

```bash
git rev-parse --abbrev-ref HEAD
```

Extract the slug from `feat/<slug>` if on a feature branch.

### Step 2 — Pre-flight

Ensure the working tree is clean (no uncommitted changes):
```bash
git status --porcelain
```

If dirty, commit or stash before proceeding.

### Step 3 — Run finish-feature.sh

```bash
bash scripts/agent/finish-feature.sh "<feature_slug>"
```

**Flags:**
- `--validate-only` — sync with main and re-validate without merging
- `--skip-docs` — skip the gen-docs step
- `--dry-run` — preview what would happen

Handle exit codes:
- **Exit 0** → merged, validated, cleaned up — proceed to Step 4
- **Exit 2** → merge conflicts — resolve each file, `git add` + `git commit --no-edit`, then re-run
- **Exit 1** → validation failed after merge — the script rolls back the merge automatically; fix the feature on the branch and re-run

### Step 4 — Update FEATURES.md

Update the feature status to `done`:
```bash
git add FEATURES.md && git commit -m "docs: mark <feature_slug> done"
```

### Step 5 — Report

Report: merge result, validation status, docs path, final FEATURES.md status.

## What finish-feature.sh does

1. Syncs with latest main before merge (prevents unnecessary conflicts)
2. Switches to `main` in the primary checkout
3. Merges the feature branch (`feat/<slug>`) into `main`
4. Runs `validate.sh all` post-merge
5. If validation fails, rolls back the merge (`git reset --hard HEAD~1`) and switches back to the feature branch
6. Optionally runs `gen-docs.sh` for feature docs
7. Tears down Docker containers and removes the worktree
8. Removes the branch from the registry
9. Deletes the feature branch (`git branch -D`)

## Validate-only mode

To sync with main and re-validate without merging:
```bash
bash scripts/agent/finish-feature.sh --validate-only
```

This is useful for checking if a feature branch is ready for merge.