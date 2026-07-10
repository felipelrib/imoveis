# Session Lifecycle Rules — Pre & Post Task Automation

## Start of every session

1. **Verify branch.** Run `git rev-parse --abbrev-ref HEAD`. If it says `main`, STOP and:
   ```bash
   bash scripts/agent/setup-branch.sh "<task-slug>"
   ```
   Never edit files on `main` directly. If you already made changes on `main`, stash them before branching.

1.5 **Update Dependencies**. After checking out the branch, ensure dependencies are installed:
   ```bash
   pip install -r requirements.txt
   (cd frontend && npm install)
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
git push origin <branch>
```

### 3. Update Linear (if applicable)
Set issue to appropriate state via `linear_bulk_update_issues`.

### 4. Push and Create PR
Use `finish-feature` skill or:
```bash
bash scripts/agent/finish-feature.sh --pr
```
- Do NOT merge to main locally.
- Wait for user feedback or CI checks on the PR.
- STOP working.

### 5. Report
Produce a structured summary: branch pushed, features delivered, files changed, any issues or follow-ups.

## Pain points addressed by this file

- **Forgetting to branch** → §Start of every session, step 1.
- **Half-committed state on main** → §End of every task, step 1 (run before declaring done).
- **Skills not committed** → `.cline/skills/` is now tracked (only `.cline/memory/` and `.cline/kanban/` are gitignored).
- **validate.sh failing when tools aren't installed** → `validate.sh` now has `--soft` mode (warn but don't roll back). Use `--skip-docs` and `--skip-validate` flags on `finish-feature.sh` for rules/docs-only changes.
