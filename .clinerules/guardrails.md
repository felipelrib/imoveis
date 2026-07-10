# NON-NEGOTIABLE GUARDRAILS (re-read every turn)

This file provides a quick-reference summary. Full details are in the numbered
rule files below. All of these rules apply to EVERY turn — no exceptions.

## Core principles

| Rule | Summary | Full Text |
|------|---------|-----------|
| First action | VERY FIRST tool call MUST be `git rev-parse --abbrev-ref HEAD`. No exceptions. | `session-workflow.md` §Start of every session |
| Isolation | Never work on `main`. Always inside `.worktrees/` with port isolation. | `04-imoveis-specific.md` §Isolation |
| Plan first | `implementation_plan.md` must exist before code. Scope discipline. | `04-imoveis-specific.md` §Workflow |
| Commit often | Conventional commits (`feat:`, `fix:`, etc.). Never leave tree dirty. | `01-universal.md` §Commit Discipline |
| Use validate.sh | NEVER run raw `pytest` or `npm test`. Always use `validate.sh`. | `session-workflow.md` §End of every task, step 3 |
| Use finish-feature.sh | NEVER manually `git push` or `gh pr create`. Always use `finish-feature.sh --pr`. | `session-workflow.md` §End of every task, step 4 |
| No secrets in code | No default passwords, API keys, or tokens. Empty-string defaults only. | `01-universal.md` §Security Rules |
| TDD | Write test FIRST, show it failing, then implement. No exceptions. | `testing.md` §TDD workflow |
| Use skills | Don't manually replicate skill steps. Use `use_skill()`. | `04-imoveis-specific.md` §Skill usage |
| Docker validation | Build fresh image before running tests. Clear config cache in containers. | `04-imoveis-specific.md` §Docker validation |
| Test discipline | Never dismiss failures as "pre-existing". Clean up fixtures. | `04-imoveis-specific.md` §Test discipline |
| Validation discipline | NEVER skip or work around validation failures. Fix root causes. | `04-imoveis-specific.md` §Validation discipline |

## Rule file map

| File | Scope |
|------|-------|
| `01-universal.md` | Portable — commit discipline, safety, security, TDD |
| `02-python-backend.md` | Portable — SQLAlchemy, FastAPI, Pydantic, Python testing |
| `03-react-frontend.md` | Portable — React patterns, Playwright, frontend security |
| `04-imoveis-specific.md` | Project — worktree isolation, Docker, feature pipeline, Linear |
| `testing.md` | Project — test pyramid, AI validation, scraper validation, contract tests |
| `ci.md` | Portable + project — pre-commit, GitHub Actions, security scanning |
