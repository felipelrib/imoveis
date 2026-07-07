# Feature Queue

!!! info "Linear is the source of truth"
    Feature tracking, specs, and status live in **[Linear](https://linear.app/felipelrib/)**.
    This file only describes how to dispatch features in Cline/Cursor.

## Working on Features

### Find the next feature

Check the [Linear board](https://linear.app/felipelrib/) — the first issue in **Todo** or **Backlog** with met dependencies is next.

### Dispatch in Cline

| Action | Prompt |
|--------|--------|
| Full pipeline | `"Work on feature <slug> from Linear"` |
| Plan only | `"Plan feature <slug>"` |
| Implement only | `"Implement feature <slug>"` |
| Validate | `"Validate the current feature"` |
| Finish | `"Finish the feature"` |

### Feature lifecycle

1. **Linear** → issue exists with spec, status, and labels
2. **Worktree** → `bash scripts/agent/setup-worktree.sh <slug>`
3. **Implement** → Cline writes code, commits to feature branch
4. **Validate** → `bash scripts/agent/validate.sh [backend|frontend|all]`
5. **Finish** → `bash scripts/agent/finish-feature.sh <slug>` (merges, validates, cleans up)
6. **Docs** → `gen-docs.sh` scaffolds implementation notes in `docs/features/`
7. **Linear** → update issue status to Done

### Tiers (for prioritisation)

| Tier | Focus | Notes |
|------|-------|-------|
| **0 — Foundation** | Config, DB, dedup, price history | Do first, mostly serial (shared files) |
| **1 — Core Product** | Scrapers, alerts, saved searches | After foundation |
| **2 — AI & Insights** | Model config, deal summaries | After config is stable |
| **3 — UX Polish** | Map, charts, toasts | Mostly frontend, parallel-safe |
| **4 — Robustness** | Circuit breakers, skip unchanged AI | After the code they optimize |

### Key commands

| Task | Command |
|------|---------|
| Create worktree | `bash scripts/agent/setup-worktree.sh <slug>` |
| Start services | `bash scripts/agent/run-services.sh` |
| Validate | `bash scripts/agent/validate.sh [backend\|frontend\|all]` |
| Finish feature | `bash scripts/agent/finish-feature.sh [slug] [--validate-only]` |
| Dry run | `bash scripts/agent/finish-feature.sh --dry-run` |