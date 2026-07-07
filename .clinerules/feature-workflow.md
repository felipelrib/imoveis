---
paths:
  - "FEATURES.md"
  - "docs/features/*"
  - "implementation_plan.md"
---

# Feature Workflow — Orchestrator Logic for Cline

This rule encodes the orchestrator agent's behavior. When the user says something
like "implement the next feature", "work the FEATURES.md queue", "start feature X",
or "what's next?", follow this workflow.

## Reading the feature queue

1. Read `FEATURES.md` — the status table at the top is the ordered work queue.
2. Find the first `pending` feature (top-down = priority order).
3. Check its **Tier** and **Depends on** fields in the spec below the table.
4. If it has dependencies, verify they are `done` before proceeding. If not,
   skip to the next feature whose dependencies are met.

## Tiers and execution order

- **Tier 0 (Foundation)** — Do first, largely serial. These share critical files
  (`src/infra/config.py`, `alembic/`, `src/core/dedupe.py`, `src/adapters/db/models.py`).
- **Tier 1 (Core product)** — Can start after Tier 0 is partially done.
- **Tier 2 (AI depth)** — Depends on Tier 0/1 for config and data.
- **Tier 3 (Design/UX)** — Mostly frontend-isolated, can run in parallel with backend.
- **Tier 4 (Robustness)** — Opportunistic, land after the features they optimize.

## Dispatching a single feature

When the user picks a feature (or you pick the next one):

### Step 1 — Plan
```
Prompt: "Plan feature <slug> from FEATURES.md"
```
This triggers the planner workflow (see `.clinerules/planner.md`).
The feature status changes from `pending` to `planned` in FEATURES.md.

### Step 2 — Implement
```
Prompt: "Implement feature <slug> from FEATURES.md"
```
This triggers the coder workflow (see `.clinerules/coder.md`).
The feature status changes from `planned` to `in-progress` to `done`.

### Step 3 — Review (optional but recommended)
```
Prompt: "Review feature <slug> before merge"
```
This triggers the reviewer workflow (see `.clinerules/reviewer.md`).

## Batch planning (for GPU efficiency)

To avoid model thrashing on a 20 GB VRAM box, prefer planning ALL pending
features first (deepseek-r1 phase), then implementing them one by one (devstral phase):

1. For each pending feature: run the planner, then mark `planned`.
2. Then for each planned feature: run the coder, then mark `done`.

This keeps one model resident at a time.

## Updating FEATURES.md status

After each phase transition, update the status column in FEATURES.md:
- Feature created: `pending`
- Plan complete: `planned`
- Implementation started: `in-progress`
- Merged + validated + documented: `done`

Always commit the FEATURES.md status update as part of the feature's commit chain.

## Conflict awareness

Features in the same tier that share files should NOT be implemented in parallel
(this is moot for Cline single-agent, but important for session planning):
- Tier 0 features share: `config.py`, `dedupe.py`, `models.py`, `alembic/`
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