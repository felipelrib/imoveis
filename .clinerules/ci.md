# CI/CD RULES — Portable CI Pattern for Any Python + React + Docker Project

## Pre-commit hooks (local)

- Install: `pre-commit install && pre-commit install --hook-type pre-push`
- pre-commit runs: whitespace, YAML/JSON validation, secret detection, isort, flake8
- pre-push runs: pytest unit suite (fast, <60s)
- NEVER skip hooks with `--no-verify` unless you document why in the commit message

## CI pipeline expectations

- Lint must pass (isort, flake8, eslint)
- Unit tests must pass (pytest, SQLite)
- Integration tests must pass (pytest, PostGIS + Redis)
- Contract tests must pass (API schema, DB schema)
- E2E tests pass on push to main and manual dispatch (Playwright)

## When CI fails

1. Read the failure log — don't guess
2. If lint: run `isort . && flake8 src/` locally, fix, recommit
3. If test: run the failing test locally. If it passes, suspect CI environment
   differences (check DATABASE_URL, Redis availability)
4. If flaky: mark with `@pytest.mark.flaky` and create a Linear ticket to
   investigate root cause
5. NEVER disable a failing test to "make CI green"

## Security scanning (post-merge)

- Trivy scans for vulnerable dependencies after merge to main
- GitHub Security Alerts are enabled for this repo
- Dependabot opens PRs weekly for pip + npm updates
- If a security alert fires, create a Linear ticket immediately

## Local CI testing

- Use `act` to run GitHub Actions workflows locally before pushing:
  ```bash
  act pull_request -j lint,unit
  act push -j security
  ```
- Each project gets `scripts/agent/ci-local.sh` that wraps `act` with the right
  secrets and service containers

## Tools and access (project-specific — Imoveis)

- GitHub Actions: repo owner (felipelrib) has admin access
- Codecov: connected via GitHub OAuth (free for public repos)
- SonarCloud: connected via GitHub OAuth (org: felipelrib, free for public repos)
- All CI config is in `.github/workflows/` — Cline can read/modify these files

## Secrets (set in GitHub repo → Settings → Secrets and variables → Actions)

| Name | Purpose | Scope |
|------|---------|-------|
| `CODECOV_TOKEN` | Upload coverage reports to Codecov | Public repo — safe to include in workflow as it's a repo-specific token |
| `SONAR_TOKEN` | Static analysis upload to SonarCloud | Must be kept secret |
| `SONAR_ORGANIZATION` | SonarCloud org key (e.g., `felipelrib`) | Not a secret but stored here for consistency |

## CI validation in the agent workflow

`scripts/agent/validate.sh` runs the same steps as CI in the same order:

```bash
# Fast feedback (pre-push equivalent)
validate.sh fast      # lint + unit

# Full backend gate (same as CI on PR)
validate.sh backend   # lint + unit + integration + contract

# Complete gate (same as CI on push to main)
validate.sh all       # lint + unit + integration + contract + frontend build