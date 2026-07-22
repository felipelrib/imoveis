---
paths:
  - "src/tests/**"
  - "frontend/tests/**"
  - "pytest.ini"
---

# Testing Strategy

## Test Pyramid

```
┌─────────────────┐
│  E2E (Playwright)│  ← Critical user flows (scrape→view, filter, modal)
├─────────────────┤
│  Integration      │  ← pytest + real PostGIS/Redis
├─────────────────┤
│  Contract         │  ← API schema snapshots, DB schema snapshots
├─────────────────┤
│  Unit             │  ← pytest + SQLite mocks
└─────────────────┘
```

## TDD Workflow (MANDATORY)

1. Write a FAILING test first.
2. Implement the minimum code to pass.
3. Refactor (test stays green).
4. Commit: `test: add test for X` → `feat: implement X`.

The agent MUST show the test failing before implementing. No exceptions.

## pytest Markers

Use consistently across all test files:

- `@pytest.mark.unit` — fast, no external deps (SQLite, mocks)
- `@pytest.mark.integration` — requires PostGIS + Redis
- `@pytest.mark.e2e` — full stack, Playwright
- `@pytest.mark.slow` — skip during rapid iteration
- `@pytest.mark.flaky` — known-flaky (create Linear ticket)

## Unit Tests

- Location: `src/tests/unit/`
- SQLite in-memory for DB tests, mock Redis/Ollama.
- Each file covers one module: `test_olx.py` ↔ `olx.py`.
- Function-scoped, isolated fixtures.

## Integration Tests

- Location: `src/tests/integration/`
- Require real PostGIS + Redis via `DATABASE_URL`, `REDIS_URL`.
- Skip with `pytest.skip()` if services unavailable.
- Fixtures must clean up: truncate all tables in reverse FK order.

## Contract Tests

- Location: `src/tests/contract/`
- API contract: validate response shapes for every endpoint.
- DB contract: verify schemas match `models.py` (`alembic check`).
- Frontend contract: Playwright + mocked API → verify UI renders.

## AI Validation Tests

- Location: `src/tests/unit/test_ai_quality.py`
- Golden-file tests: 10 curated samples with expected scores.
- Threshold: `condition_score` within ±0.15 of golden value.
- Skip if `OLLAMA_HOST` unreachable.
- Run: `bash scripts/agent/validate-ai.sh`

## Scraper Validation Tests

- Dry-run against live pages (rate-limited): `scripts/dev/test_scraper_dryrun.py`
- HTML snapshot tests: saved HTML → verify parser extracts correct fields.
- Schema compliance: output must match `PropertyCandidate` schema.
- Run: `bash scripts/agent/validate-scrapers.sh`

## Coverage by Tool

| Concern | Tool | Scope |
|---|---|---|
| Scraper parses HTML | pytest unit (golden file) | Every scraper method |
| AI produces reasonable scores | pytest golden-file | Every prompt change |
| Dedup matches properties | pytest integration (PostGIS) | Core dedup logic |
| User can view property list | Playwright E2E | Critical path |
| Modal shows property details | Playwright E2E | Critical path |
| Frontend calls correct API | Playwright + mocked API | Every page |
| API returns valid JSON schema | Contract test (pytest) | Every endpoint |
| DB schema matches models | Alembic check + contract | Every migration |

## CI Integration

- All test types run in GitHub Actions on every PR and push to main.
- E2E runs as a gate on PRs AND post-merge smoke test.
- `validate.sh all` mirrors CI locally: lint → unit → integration → contract → frontend build → E2E.
- Pre-commit hooks: whitespace, YAML/JSON, secret detection, isort, flake8.
- Pre-push hook: pytest unit + frontend build.
