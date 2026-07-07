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

### Step 1 — Setup worktree

```bash
bash scripts/agent/setup-worktree.sh "<feature_slug>"
cd .worktrees/<feature_slug>
```

### Step 2 — Plan the feature

Read the feature spec from FEATURES.md, analyze affected code areas, then write
`implementation_plan.md` with these sections:
1. Goal (one paragraph)
2. Affected areas (files/modules)
3. Step-by-step implementation (ordered, committable)
4. Data / schema changes
5. Validation plan
6. Risks and conflict surface

Commit the plan:
```bash
git add implementation_plan.md && git commit -m "docs: plan <feature_slug>"
```

Update FEATURES.md: `<feature_slug>` status to `planned`.

### Step 3 — Start services

```bash
bash scripts/agent/run-services.sh
```

### Step 4 — Implement

Implement each step from `implementation_plan.md`, committing after each
meaningful step with conventional messages.

Update FEATURES.md: `<feature_slug>` status to `in-progress`.

### Step 5 — Validate

```bash
bash scripts/agent/validate.sh all
```

### Step 6 — Finish the feature

```bash
bash scripts/agent/finish-feature.sh "<feature_slug>"
```

Handle exit codes:
- **Exit 0** → merged, validated, cleaned up — proceed to Step 7
- **Exit 2** → merge conflicts — resolve, commit, re-run
- **Exit 1** → validation failed after merge — fix, commit, re-run

### Step 7 — Update status

Update FEATURES.md: `<feature_slug>` status to `done`.
```bash
git add FEATURES.md && git commit -m "docs: mark <feature_slug> done"
```

## Output

Report: merge result, validation status, docs path, final FEATURES.md status.