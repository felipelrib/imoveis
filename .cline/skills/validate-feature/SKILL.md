---
name: validate-feature
description: Validate a feature branch by running tests, checking build, and optionally reviewing the diff against main. Use when the user says "validate the current feature" or "run validation".
---

# Validate Feature

When the user says "validate the current feature" or "run validation", follow this skill.

## Input

- `feature_slug` (optional): if not provided, detect from the current git branch name.

## Steps

### Step 1 — Detect current branch (if slug not provided)

```bash
git rev-parse --abbrev-ref HEAD
```

Extract the slug from `feat/<slug>` if on a feature branch.

### Step 2 — Run the validation gate

```bash
bash scripts/agent/validate.sh all
```

Report results clearly:
- Backend: pytest pass/fail
- Backend: /health endpoint check
- Frontend: npm build pass/fail

If `all` scope is not needed, allow `backend` or `frontend` only.

### Step 3 — Quick review (optional)

If the user wants a review too, switch to reviewer mode
(see `.clinerules/reviewer.md`) and run the review workflow.

### Step 4 — Merge check (optional)

```bash
bash scripts/agent/merge-revalidate.sh
```

Handle exit codes as documented in `.clinerules/coder.md`.

## Output

Report: validation status (pass/fail), any failures with file:line references,
and whether the branch is ready for merge.