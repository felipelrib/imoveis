---
name: feature-pipeline
description: Run the full feature pipeline (plan, implement, validate, PR, docs) for a Linear issue. Use when the user says "work on the next ticket", "run feature X", or "do the full pipeline".
---

# Full Feature Pipeline

End-to-end lifecycle for delivering a feature from Linear.

## Input

- `feature_slug`: kebab-case identifier for the branch name
- `linear_issue_id`: the Linear issue identifier (e.g., `BIN-7`)

If not provided, detect from milestone ordering (see rules.md).

## Phase 1 — Issue Selection (Planner)

### Step 1 — Select the next issue

Follow milestone ordering from `.clinerules/rules.md`:

1. `linear_get_project_milestones` for project `2b293958-ee46-48f1-98aa-6d54abba468d`.
2. Find earliest uncompleted milestone (lowest `sortOrder`, `status != done`).
3. `linear_search_issues` scoped to that milestone — pick highest priority (lowest number).

### Step 2 — Update Linear to In Progress

```
linear_bulk_update_issues --issueIds "<linear_issue_id>" --update '{"stateId": "7de50ed1-0de6-4f06-89f6-6816991f106f"}'
```

### Step 3 — Setup branch

```bash
bash scripts/agent/setup-branch.sh "<feature_slug>"
```

### Step 4 — Plan the feature

Read the Linear issue spec via MCP. Analyse affected code. Write `implementation_plan.md`
with ALL mandatory sections (see `.clinerules/rules.md` § `implementation_plan.md` Format).

Commit:
```bash
git add implementation_plan.md && git commit -m "docs: plan <feature_slug>"
```

**STOP HERE if using Planner + Implementer mode.** Hand off to Implementer.

---

## Phase 2 — Implementation (Implementer)

### Step 5 — Start services

```bash
docker-compose up -d
```

### Step 6 — Implement

Read `implementation_plan.md` and execute each step in order.

Rules for Implementer:
- Follow the plan EXACTLY. Do not refactor beyond scope.
- Commit after each meaningful step with conventional messages.
- If something is unclear, STOP and ask — do not guess.
- If you need to touch >3 files not in the plan, STOP.

### Step 7 — Validate

```bash
bash scripts/agent/validate.sh all
```

Must pass before proceeding. Fix any failures, commit fixes, re-validate.

### Step 8 — Push & PR

```bash
bash scripts/agent/finish-feature.sh --pr
```

Handle exit codes:
- **Exit 0** → pushed, ready for PR. Proceed to Step 9.
- **Exit 1** → validation/CI failed. Fix, commit, re-run.

### Step 9 — Update Linear to Done

```
linear_bulk_update_issues --issueIds "<linear_issue_id>" --update '{"stateId": "fa058318-6dde-441e-91cb-5939c33e4fb1"}'
```

### Step 10 — Write feature documentation (MANDATORY)

Every completed feature **must** have a numbered markdown file in `docs/features/`.

#### 10a — Determine the next sequential number

```bash
ls docs/features/ | grep -E '^[0-9]' | sort | tail -1
# e.g. "19-system-status-and-pipeline-telemetry.md" → next number is 20
```

#### 10b — Create the file

Name: `docs/features/<NN>-<feature-slug>.md`
where `<NN>` is zero-padded to 2 digits (e.g. `20`, `21`).

**Follow `docs/features/_template.md` EXACTLY.** All six sections are mandatory:

```markdown
# <feature-name> — <one-line description>

> Feature branch: `feat/<slug>` · Linear: `BIN-XX` · Status: implemented

## Problem

What user pain or technical gap does this feature address?

## Approach

- Bullet points describing the high-level design decisions.
- Why this approach was chosen over alternatives.

## Changes

Files touched:

```
 path/to/file.py       | WHAT CHANGED — short description
 path/to/other/file.py | NEW — new file description
```

## New Dependencies

Any new packages added to `requirements.txt` or `package.json`? Or "None".

## How to Test

1. Steps to manually verify the feature works.
2. Or the test command:
   ```bash
   bash scripts/agent/validate.sh backend
   ```

## Notes / Follow-ups

- Any known limitations, tech debt, or follow-up work.
- **BUG**: flag every confirmed bug found during review with severity.
```

#### Rules for the doc

- **Problem**: 2–4 sentences maximum — no padding.
- **Approach**: bullet list only; explain *why*, not just *what*.
- **Changes table**: list every file touched with a short description. Mark new files `NEW —`.
- **Notes / Follow-ups**: document ALL bugs found during implementation and review here,
  formatted as `**BUG (Severity)**: description — fix hint.`
- Do **NOT** write freeform narrative docs or use the old plain-markdown format.
- Do **NOT** omit any section, even if it is `None` or `N/A`.

#### 10c — Commit

```bash
git add docs/features/<NN>-<feature-slug>.md
git commit -m "docs: <NN>-<feature-slug> feature doc"
git push
```

## Output

Report: branch name, PR URL, validation status, Linear status updated, docs path.
