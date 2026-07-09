---
name: code-review
description: Review staged or diffed changes for guardrail violations, missing tests, and code quality issues. Use when the user says "review my code", "check this diff", "code review", or "pre-commit check".
---

# Code Review

Analyzes the current git diff (staged or against main) against the project's
guardrails and produces a structured review.

## Scope

Review ALL staged changes (or diff against `main` if nothing staged). For each
changed file, check:

1. **Secrets & credentials** — no `imoveis_secret`, `dev-secret-key`, hardcoded
   passwords, API keys, or tokens in source code.
2. **Hardcoded ports** — no `5432`, `6379`, `8000`, `5173` or `localhost` URLs
   in source code (env vars only).
3. **Missing tests** — new functions/classes should have corresponding tests.
4. **Conventional commit format** — check that `git log -1 --format=%s` matches
   `feat:|fix:|test:|docs:|refactor:|chore:`.
5. **Scope creep** — files changed should match the feature's `implementation_plan.md`.
   If >3 unexpected files, flag it.
6. **Linter violations** — run `isort --check src/` and `flake8 src/`.
7. **Print statements** — no `print()` calls in production code.
8. **Test anti-patterns** — no `.only()` or `.skip()` in test files without a
   comment explaining why.
9. **SQL injection** — no f-strings or string concatenation in SQL queries.
10. **Circular imports** — check new Python files don't create import cycles.

## Steps

```bash
# 1. Get the diff
git diff --staged --name-only  ||  git diff main --name-only

# 2. Run pre-commit hooks (same as CI)
bash scripts/agent/lint.sh

# 3. Run unit tests (fast feedback)
pytest src/tests/unit/ -v --timeout=30

# 4. Check for secrets in the diff
git grep -nP "(imoveis_secret|dev-secret-key|password\s*=\s*['\"][a-zA-Z0-9])" $(git diff --staged --name-only)

# 5. Check commit message
git log -1 --format=%s
```

## Output

Produce a structured report:

```
## Code Review — <branch or commit>

### ✅ Passed
- [x] No hardcoded secrets
- [x] No hardcoded ports
- [x] Linter clean

### ❌ Issues Found
- [ ] **Missing test** — `src/core/new_feature.py` adds function `calculate_score()` without a corresponding test in `src/tests/unit/`.
- [ ] **Scope creep** — `src/adapters/db/models.py` modified but not in implementation plan.

### 📋 Recommendations
- Consider adding a contract test for the new `/api/properties/filter` endpoint.
- The `fetchPages()` function is >200 lines — consider splitting it.

### Summary
2 issues, 3 recommendations. Ready to commit after fixing missing test.