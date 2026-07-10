# TESTING STRATEGY — Imoveis

## Test pyramid

```
┌─────────────────┐
│   E2E (Playwright)│  ← Critical user flows (scrape→view, filter, modal)
├─────────────────┤
│  Integration      │  ← pytest + real PostGIS/Redis (test_e2e.py, test_listings_e2e.py)
├─────────────────┤
│  Contract         │  ← API schema snapshots, DB schema snapshots (test_api_contract.py)
├─────────────────┤
│  Unit             │  ← pytest + SQLite mocks (test_olx.py, test_dedupe.py, etc.)
└─────────────────┘
```

## TDD workflow (MANDATORY)

1. Write a FAILING test first
2. Implement the minimum code to pass
3. Refactor (test stays green)
4. Commit: "test: add test for X" → "feat: implement X"

The agent MUST show the test failing before implementing. No exceptions for "simple" changes.

## pytest markers

Use markers consistently across all test files:

- `@pytest.mark.unit` — fast, no external dependencies (SQLite in-memory, mocks)
- `@pytest.mark.integration` — requires PostGIS + Redis (real or CI service containers)
- `@pytest.mark.e2e` — full stack, Playwright browser tests
- `@pytest.mark.slow` — slow tests that can be skipped during rapid iteration
- `@pytest.mark.flaky` — known-flaky tests that need investigation (create Linear ticket)

## Unit tests

- Location: `src/tests/unit/`
- Use SQLite in-memory for DB tests, mock external services (Redis, Ollama)
- Each test file should cover one module: `test_olx.py` matches `olx.py`
- Fixtures must be function-scoped and isolated

## Integration tests

- Location: `src/tests/integration/`
- Require real PostGIS + Redis via `DATABASE_URL` and `REDIS_URL` env vars
- Skip with `pytest.skip()` if services unavailable (don't fail CI)
- Fixtures must clean up: truncate all tables in reverse foreign-key order
- Test file naming: `test_listings_e2e.py` for end-to-end DB workflows

## Contract tests

- Location: `src/tests/contract/`
- API contract: validate response shapes for every endpoint
- DB contract: verify table schemas match models.py (`alembic check`)
- Frontend contract: Playwright tests that mock API responses and verify UI renders

## AI validation tests

- Location: `src/tests/unit/test_ai_quality.py`
- Golden-file tests: 10 hand-curated property samples with expected scores
- Regression test: run AI on the same input before/after prompt changes
- Threshold test: `condition_score` must be within ±0.15 of golden value after prompt changes
- Ollama availability: skip if `OLLAMA_HOST` unreachable (don't block CI)
- Run with: `bash scripts/agent/validate-ai.sh`

## Scraper validation tests

- Dry-run against live pages (rate-limited, jittered) — see `scripts/dev/test_scraper_dryrun.py`
- HTML snapshot tests: save OLX page HTML → verify parser still extracts correct fields
- Schema compliance: normalized output must match `PropertyCandidate` schema
- Run with: `bash scripts/agent/validate-scrapers.sh`

## Playwright E2E tests

- Location: `frontend/tests/e2e/`
- Critical user flows: browse → filter → view property → trigger scrape
- Mock API responses for deterministic tests (`page.route()`)
- Real backend for full-stack integration tests (requires running stack)
- Screenshot comparison for visual regression on key pages
- Run with: `npm run test:e2e --prefix frontend`

## What Playwright covers vs. pytest

| Test Concern | Right Tool | Coverage Needed |
|---|---|---|
| Scraper parses OLX HTML correctly | pytest unit (golden file) | Every scraper method |
| AI model produces reasonable scores | pytest golden-file tests | Every AI prompt change |
| Dedup correctly matches properties | pytest integration (real PostGIS) | Core dedup logic |
| User can view property list | Playwright E2E | Critical path |
| Modal shows correct property details | Playwright E2E | Critical path |
| Frontend calls correct API endpoint | Playwright with mocked API | Every frontend page |
| API returns valid JSON schema | Contract test (pytest) | Every endpoint |
| DB schema matches models | Alembic check + contract test | Every migration |

## CI integration

- All test types run in CI via GitHub Actions on every PR and push to main.
- **E2E (Playwright) runs as a gate on PRs** AND as a post-merge smoke test on
  push to main. PRs with failing E2E must NOT be merged.
- `validate.sh all` runs the same steps as CI locally: lint → unit →
  integration → contract → frontend build → E2E. Must pass before opening
  a PR.
- Pre-commit hooks: whitespace, YAML/JSON validation, secret detection,
  isort, flake8, forbid-print, forbid-only.
- Pre-push hook: pytest unit + frontend build. Must pass before pushing.
- `finish-feature.sh --pr` automates push → PR → wait-for-CI-green → merge.
- See `.clinerules/ci.md` for full CI pipeline documentation.
