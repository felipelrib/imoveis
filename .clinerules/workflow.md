---
paths:
  - "FEATURES.md"
  - "implementation_plan.md"
  - "docs/features/*"
---

# Feature Workflow — Cline CLI

Single unified workflow for planning, implementing, and validating features.
Read `.clinerules/guardrails.md` and `.clinerules/project.md` first.

## Reading the feature queue

1. Read `FEATURES.md` — the status table at the top is the ordered work queue.
2. Find the first `pending` feature (top-down = priority order).
3. Check its **Tier** and **Depends on** fields in the spec below the table.
4. If it has dependencies, verify they are `done` before proceeding.

## Dispatching a feature

### Full pipeline (recommended)

Say: `"Work on feature <slug> from FEATURES.md"`

This triggers:
1. Read the feature spec from FEATURES.md
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

1. **Read FEATURES.md** — find the feature row and its full spec.
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
6. **Update FEATURES.md** status from `pending` to `planned`.

## Implementation workflow

When asked to implement a feature:

1. **Confirm the plan exists** (`implementation_plan.md`). If not, plan first.
2. **Ensure services are running:**
   ```bash
   bash scripts/agent/run-services.sh
   ```
3. **Implement the plan step by step.** After each meaningful step:
   - Run relevant tests
   - `git commit` with a conventional message
4. **Add/extend pytest tests** for backend changes; keep the frontend building.
5. **Finish the feature:**
   ```bash
   bash scripts/agent/finish-feature.sh <slug>
   ```
   Handle exit codes: 0=done, 1=fix+re-run, 2=resolve conflicts+re-run.
6. **Push to remote** after merge:
   ```bash
   git push origin main
   ```
7. **Update FEATURES.md** status to `done` and commit.

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
- `price-history-tracking` depends on `property-listings-table`
- `configurable-ai-models` depends on `config-yaml-loader`
- `price-drop-alerts` depends on `price-history-tracking`
- `olx-scraper` depends on `property-listings-table`

## Tracking progress across sessions

If a session is interrupted:
1. Check `FEATURES.md` for the current status column.
2. If `in-progress`, check the worktree for `implementation_plan.md` and
   `git log --oneline` to see what's been committed.
3. Resume from the last committed step.