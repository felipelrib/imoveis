# Session Lifecycle Rules — Pre & Post Task Automation

## Start of every session

> **FIRST ACTION (NON-NEGOTIABLE).** Before ANY `search_files`, `read_file`,
> `use_mcp_tool`, or other exploration, your VERY FIRST tool call MUST be:
> ```bash
> git rev-parse --abbrev-ref HEAD
> ```

**Branch verification rules:**

| Current branch | Action |
|---|---|
| `main` | **STOP immediately.** Run `bash scripts/agent/setup-branch.sh "<task-slug>"` before any file edits. If you already made changes on `main`, stash them first. Never edit files on `main` directly. |
| Feature branch from a past session | **Verify it matches the current task.** Read `git log --oneline -3` and the PR title/description (if any) to confirm the branch scope matches what the user is asking now. If it does not, stop and ask the user before proceeding. |
| Feature branch matching the task | **Proceed**, but first sync with origin (step 1.6 below). |

1.5 **Update Dependencies**. After checking out the correct branch, ensure dependencies are installed:
   ```bash
   pip install -r requirements.txt
   (cd frontend && npm install)
   ```

1.6 **Sync with origin**. Before doing any work, pull the latest changes so the local branch is up to date:
   ```bash
   git pull origin "$(git rev-parse --abbrev-ref HEAD)"
   ```

2. **Check context.** If there's an active Linear issue, read it via MCP.
   If resuming, check `git log --oneline -5` for recent commits and read `implementation_plan.md` if it exists.

3. **Load guardrails.** The `04-imoveis-specific.md` isolation rules are NON-NEGOTIABLE. Re-read the core principles table in `guardrails.md` at the start of every task.

## End of every task (MANDATORY ritual)

After every task, the agent MUST run through this checklist:

### 1. Verify git state
```bash
git status --porcelain
git rev-parse --abbrev-ref HEAD
```
- If there are uncommitted changes, commit them.
- If on `main`, create a branch and move changes there.
- NEVER leave uncommitted changes on `main`.

### 2. Commit remaining changes
```bash
git add -A
git commit -m "feat|fix|docs|chore: <description>"
```
Do NOT `git push` manually — `finish-feature.sh` handles pushing.

### 3. Validate
NEVER run raw `pytest` or `npm test` directly. ALWAYS use:
```bash
bash scripts/agent/validate.sh fast    # lint + unit (<60s, for bug fixes)
bash scripts/agent/validate.sh backend # lint + unit + integration + contract
bash scripts/agent/validate.sh all     # full CI gate (before PR)
```
`validate.sh` runs the SAME steps as CI (lint, tests, build) in the SAME order.
For simple bug fixes, `validate.sh fast` is sufficient before pushing.

### 4. Push and Create PR
NEVER manually `git push` or `gh pr create`. ALWAYS use:
```bash
bash scripts/agent/finish-feature.sh --pr
```
This script: validates → pushes → opens PR → waits for CI → reports result.
- Do NOT merge to main locally.
- Wait for user feedback or CI checks on the PR.
- STOP working.

### 5. Update Linear (if applicable)
Set issue to appropriate state via `linear_bulk_update_issues`.

### 6. Report
Produce a structured summary: branch pushed, features delivered, files changed, any issues or follow-ups.

## Pain points addressed by this file

- **Forgetting to branch** → §Start of every session, step 1.
- **Half-committed state on main** → §End of every task, step 1 (run before declaring done).
- **Skills not committed** → `.cline/skills/` is now tracked (only `.cline/memory/` and `.cline/kanban/` are gitignored).
- **validate.sh failing when tools aren't installed** → `validate.sh` now has `--soft` mode (warn but don't roll back). Use `--skip-docs` and `--skip-validate` flags on `finish-feature.sh` for rules/docs-only changes.
