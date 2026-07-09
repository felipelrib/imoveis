---
name: feature-pipeline
description: Run the full feature pipeline (plan, implement, validate, merge, docs) for a feature from Linear. Use when the user says "run feature X" or "do the full pipeline".
---

# Full Feature Pipeline

This skill bundles the entire feature lifecycle into a single dispatch.

## Input

- `feature_slug`: kebab-case identifier matching the feature branch name
- `feature_title`: human-readable title (for docs)
- `linear_issue_id`: the Linear issue identifier (e.g., `BIN-7`)

## Pipeline steps

### Step 1 — Setup worktree

```bash
bash scripts/agent/setup-worktree.sh "<feature_slug>"
cd .worktrees/<feature_slug>
```

### Step 2 — Update Linear status

Set the Linear issue to "In Progress":

```bash
linear_bulk_update_issues --issueIds "<linear_issue_id>" --update '{"stateId": "7de50ed1-0de6-4f06-89f6-6816991f106f"}'
```

In Progress stateId: `7de50ed1-0de6-4f06-89f6-6816991f106f`

### Step 3 — Verify Linear project and milestone

1. Check the issue has `projectId: "2b293958-ee46-48f1-98aa-6d54abba468d"` (Imoveis — Deal Tracker).
2. Check the issue is assigned to the correct milestone. If not, assign it.
3. Reference `.clinerules/04-imoveis-specific.md` for the current milestone mapping and ticket hygiene rules.

### Step 4 — Plan the feature

Read the feature spec from the Linear issue via MCP, analyze affected code areas, then write
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

### Step 5 — Start services

```bash
bash scripts/agent/run-services.sh
```

### Step 6 — Implement

Implement each step from `implementation_plan.md`, committing after each
meaningful step with conventional messages.

### Step 7 — Validate

```bash
bash scripts/agent/validate.sh all
```

### Step 8 — Finish the feature

```bash
bash scripts/agent/finish-feature.sh "<feature_slug>"
```

Handle exit codes:
- **Exit 0** → merged, validated, cleaned up — proceed to Step 9
- **Exit 2** → merge conflicts — resolve, commit, re-run
- **Exit 1** → validation failed after merge — fix, commit, re-run

### Step 9 — Update Linear status to Done

After `finish-feature.sh` succeeds (exit 0), mark the Linear issue as Done:

```bash
linear_bulk_update_issues --issueIds "<linear_issue_id>" --update '{"stateId": "fa058318-6dde-441e-91cb-5939c33e4fb1"}'
```

Done stateId: `fa058318-6dde-441e-91cb-5939c33e4fb1`

### Step 10 — Push to remote

```bash
git push origin main
```

### Step 11 — Generate feature docs

```bash
bash scripts/agent/gen-docs.sh
```

### Step 12 — Return to main and clean up

After the feature is merged, return to the primary checkout and tear down the worktree:

```bash
cd /home/felipe/workfolder/imoveis
git worktree remove .worktrees/<feature_slug>
```

## Output

Report: merge result, validation status, docs path, Linear status updated to Done, worktree cleaned up.