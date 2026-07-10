# UNIVERSAL RULES — Portable Across Any Cline Project

Copy this file to any Cline project. No project-specific details here.

## Commit Discipline

- Commit messages MUST use conventional format: `feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`
- NEVER commit with messages like "update", "WIP", "asdf", "fixes"
- One logical change per commit — don't batch unrelated changes
- Commit after each meaningful step; never leave a dirty tree for long

## Code Quality Gate (Pre-Commit)

Before every commit, verify:
- No `print()` statements in production code (use `logger.info()` instead)
- No `.only()` or `.skip()` in test files without an explanatory comment
- No hardcoded secrets, API keys, passwords, or tokens in source code
- No hardcoded ports (5432, 6379, 8000, 5173) or localhost URLs — use env vars
- Run linter (isort, flake8, eslint) and fix issues before committing
- Check the diff: no `.env` files, no `.env.local`, no credentials

## Scoping

- NEVER refactor code outside the feature scope defined in the plan
- If you touch >3 files not in the implementation plan, STOP and update the plan first
- Do not optimize code that isn't causing a measurable problem

## Safety

- NEVER `git push --force`
- NEVER `git push --force-with-lease` unless you understand the consequences
- NEVER delete another developer's branch or worktree
- NEVER run destructive Docker commands (`docker system prune`, `docker volume rm`) without explicit user approval
- NEVER delete remote branches without confirmation

## Security Rules

- NEVER hardcode default passwords in source code. Defaults must be empty string `""` or read from environment variables.
- NEVER hardcode API keys, even as fallback defaults. Use `os.getenv("KEY")` without a default, or raise a clear error if unset.
- NEVER use `eval()`, `exec()`, or `os.system()` with user-supplied strings
- NEVER use `dangerouslySetInnerHTML` in React without DOMPurify sanitization
- NEVER use f-strings or string concatenation to build SQL queries — always parameterize
- All secrets (DB passwords, API keys, tokens) must come from environment variables or a secrets manager
- Run `git grep -nP '(password|secret|api_key).*=.*["\x27][a-zA-Z0-9]' src/ frontend/src/` before committing to catch accidental leaks

## Test Discipline

- Write tests FIRST (TDD): test → see it fail → implement → see it pass
- NEVER dismiss test failures as "pre-existing" without investigating root cause
- NEVER disable a failing test to "make CI green" — fix the code or fix the test
- Integration test fixtures MUST clean up after themselves (truncate tables, flush Redis, close connections)

## Session Start (MANDATORY)

At the start of EVERY session:
1. Run `git rev-parse --abbrev-ref HEAD`. If it says `main`, STOP immediately.
   - NEVER edit files on `main`.
   - Create a worktree: `bash scripts/agent/setup-worktree.sh "<task-slug>" && cd .worktrees/<task-slug>`
   - If you already made changes on `main`, stash them before creating the worktree.
2. Read `.clinerules/guardrails.md` and `.clinerules/04-imoveis-specific.md` for isolation rules.
3. Read `.clinerules/session-workflow.md` for the full pre/post task ceremony.

See `.clinerules/session-workflow.md` for the complete lifecycle (start → work → finish → clean up).

## Session Continuity

- If a session is interrupted, check the worktree state and Linear status to resume
- Use the Memory Bank (`.cline/memory/`) to maintain context across sessions
- Before starting work, read `active_context.md` to understand what's in progress

## Post-Edit Checks

After editing source files:
- If a new function or class was added, a corresponding test should exist or be planned
- If a config file was modified, verify the corresponding code reads from that config
- Ensure no circular imports in new Python code
- Ensure no TypeScript/PropTypes errors in new React code
