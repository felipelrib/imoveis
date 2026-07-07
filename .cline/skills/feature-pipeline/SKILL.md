---
name: feature-pipeline
description: Run the full feature pipeline (plan, implement, validate, merge, docs) for a feature from FEATURES.md. Use when the user says "run feature X" or "do the full pipeline".
---

# Full Feature Pipeline

This skill bundles the entire feature lifecycle into a single dispatch.

## Input

- `feature_slug`: kebab-case identifier matching a row in FEATURES.md
- `feature_title`: human-readable title (for docs)

## Pipeline steps

### Step 1 — Setup worktree (if not exists)

```bash
bash scripts/agent/setup-worktree.sh "<feature_slug>"
cd .worktrees/<feature_slug>
```

### Step 2 — Check/create plan

If `implementation_plan.md` does not exist in the worktree, switch to planner mode
(see `.clinerules/planner.md`) and create it. Then return to this pipeline.

Verify the plan is committed:
```bash
git log --oneline -1
```

Update FEATURES.md: `<feature_slug>` status to `planned`.

### Step 3 — Start services

```bash
bash scripts/agent/run-services.sh
```

### Step 4 — Implement

Switch to coder mode (see `.clinerules/coder.md`). Implement each step from
`implementation_plan.md`, committing after each meaningful step.

Update FEATURES.md: `<feature_slug>` status to `in-progress`.

### Step 5 — Finish the feature

When implementation and docs are complete, run:
```bash
bash scripts/agent/finish-feature.sh "<feature_slug>"
```

This single script:
- Merges the feature branch into main
- Runs post-merge validation (`validate.sh all`)
- Tears down the worktree and containers
- Deletes the feature branch

Handle exit codes:
- **Exit 0** → merged, validated, cleaned up — proceed to Step 6
- **Exit 2** → merge conflicts — resolve, commit, re-run
- **Exit 1** → validation failed after merge — fix, commit, re-run

### Step 6 — Update status

Update FEATURES.md: `<feature_slug>` status to `done`.
```bash
git add FEATURES.md && git commit -m "docs: mark <feature_slug> done"
```

## Output

Report: merge result, validation status, docs path, final FEATURES.md status.