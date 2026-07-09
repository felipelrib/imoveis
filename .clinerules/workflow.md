---
paths:
  - ".clinerules/workflow.md"
  - "docs/features/*"
---

# Feature Workflow — Cline CLI

Single unified workflow for planning, implementing, and validating features.
Read `.clinerules/guardrails.md` and `.clinerules/project.md` first.

## Reading the feature queue

1. Use `linear_search_issues` MCP tool to find issues in the Bino team.
2. Find the first issue in **Todo** or **Backlog** state with met dependencies.
3. Check its **labels** and **priority** for context.
4. If it has dependencies (mentioned in the description), verify they are `Done` in Linear before proceeding.

## Dispatching a feature

### Full pipeline (recommended)

Say: `"Work on feature <slug> from Linear"`

This triggers:
1. Read the feature spec from the Linear issue via MCP
2. Analyze affected codebase areas
3. Write `implementation_plan.md` in the worktree
4. Commit the plan
5. Implement step by step with tests
6. Commit after each meaningful step
7. Run validation
8. Finish the feature (merge + teardown)

### Individual steps

| Step | Prompt | What happens |
|------|--------|--------------|
| Plan | `"Plan feature <slug>"` | Creates `implementation_plan.md` |
| Implement | `"Implement feature <slug>"` | Codes from the plan |
| Validate | `"Validate the current feature"` | Runs `validate.sh` |
| Finish | `"Finish the feature"` | Runs `finish-feature.sh` |

## Planning workflow

When asked to plan a feature:

1. **Read the Linear issue** via `linear_search_issues` MCP tool — get the full description and acceptance criteria.
2. **Create the worktree** (if not already done):
   ```bash
   bash scripts/agent/setup-worktree.sh "<feature-slug>"
   ```
   Then `cd` into `.worktrees/<feature-slug>`.
3. **Analyze affected areas** of the codebase.
4. **Write `implementation_plan.md`** with these sections:
   - **Goal** — one paragraph on what and why.
   - **Affected areas** — concrete files/modules.
   - **Step-by-step implementation** — ordered, each step small and committable.
   - **Data / schema changes** — new tables, migrations, indexes.
   - **Validation plan** — tests to add and how to exercise the feature.
   - **Risks and conflict surface** — files likely to collide.
5. **Commit the plan:**
   ```bash
   git add implementation_plan.md && git commit -m "docs: plan <feature-slug>"
   ```
6. **Update Linear issue** status from Backlog to Todo (or In Progress when starting).

## Implementation workflow

When asked to implement a feature:

1. **Confirm the plan exists** (`implementation_plan.md`). If not, plan first.
2. **Update Linear issue** to `In Progress` via `linear_search_issues` + `linear_bulk_update_issues`.
3. **Ensure services are running:**
   ```bash
   bash scripts/agent/run-services.sh
   ```
4. **Implement the plan step by step.** After each meaningful step:
   - Run relevant tests
   - `git commit` with a conventional message
5. **Add/extend pytest tests** for backend changes; keep the frontend building.
6. **Finish the feature:**
   ```bash
   bash scripts/agent/finish-feature.sh <slug>
   ```
   Handle exit codes: 0=done, 1=fix+re-run, 2=resolve conflicts+re-run.
7. **Push to remote** after merge:
   ```bash
   git push origin main
   ```
8. **Update Linear issue** status to Done via `linear_bulk_update_issues`.
9. **Generate feature docs** in `docs/features/` (via `gen-docs.sh` or manually).

## Validation workflow

When asked to validate:

```bash
bash scripts/agent/validate.sh [backend|frontend|all]
```

Report results explicitly. If validation fails:
1. Check the specific failure (test name, error message)
2. Fix the issue in the worktree
3. Re-run validation
4. Report the outcome

## Conflict awareness

Features in the same tier that share files should NOT be implemented in parallel
(important when pausing/resuming):
- Foundation features share: `config.py`, `dedupe.py`, `models.py`, `alembic/`
- Check dependency relationships in Linear issue descriptions before starting
- Dependencies are tracked in the issue description, not in a local file

## Tracking progress across sessions

If a session is interrupted:
1. Check Linear for the current issue status (use `linear_search_issues`).
2. If `In Progress`, check the worktree for `implementation_plan.md` and
   `git log --oneline` to see what's been committed.
3. Resume from the last committed step.

## Task completion checklist

After EVERY task is complete — whether a feature, a config change, or a documentation
update — run this checklist before declaring "done":

1. **Commit all changes.** No uncommitted files should remain. Use conventional
   commit messages (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`).
2. **Close the worktree.** Tear down the isolated workspace:
   ```bash
   cd /home/felipe/workfolder/imoveis
   git worktree remove .worktrees/<feature-slug>
   ```
3. **Return to main** in the primary checkout. Never leave a dirty or orphaned
   worktree behind.

## Linear ticket hygiene

### 1. Always mark Done when done

After `finish-feature.sh` exits with code 0, the feature is complete. You MUST
immediately update the Linear issue to "Done" using `linear_bulk_update_issues`.
Never leave a completed feature in "In Progress" or "In Review."

```bash
# After finish-feature.sh succeeds:
# Update Linear issue status
linear_bulk_update_issues --issueIds "<issue-id>" --update '{"stateId": "<done-state-id>"}'
```

done-state-id for Bino: `fa058318-6dde-441e-91cb-5939c33e4fb1`

> **Note on tool limitations:** The `linear_bulk_update_issues` MCP tool only
> supports updating `stateId`, `assigneeId`, `priority`, and `estimate`. It
> cannot set a project or milestone. For project/milestone assignment, use the
> Linear web UI at https://linear.app/felipelrib/ and assign manually, then
> continue with the next step.

### 2. Always assign tickets to a project

Every issue in the Bino team MUST be assigned to a project. When creating a new
issue via `linear_create_issue` or `linear_create_issues`, always include the
`projectId` parameter. When picking up an existing issue that lacks a project,
assign it before starting work.

projectId for "Imoveis — Deal Tracker": `2b293958-ee46-48f1-98aa-6d54abba468d`

### 3. Always assign tickets to a milestone

Every issue should live within a milestone that groups related work. Before
starting a feature:

1. Check the current milestones via `linear_search_project_milestones` with
   `projectId: "2b293958-ee46-48f1-98aa-6d54abba468d"`.
2. Assign the issue to the best-fitting milestone based on the issue's tier/theme.
3. If no existing milestone fits, create a new one via
   `linear_create_project_milestone`.
4. Backlog ideas and future-tier features go under "Future / Beyond MVP"
   (create it if it doesn't exist).

**Current milestone mapping:**

| Milestone | Tier | Theme |
|-----------|------|-------|
| v0.1 — Foundation & Pipeline | Foundation | Config, DB, dedup, price history, scrapers, beat |
| v0.2 — Deal Intelligence | AI & Insights | Alerts, configurable AI, deal verdicts |
| v0.3 — User Experience | UX Polish | Saved searches, map, charts, toasts |
| v0.4 — Production Hardening | Robustness | Circuit breakers, skip unchanged AI |
| Future / Beyond MVP | Future | Backlog ideas not yet prioritized |
