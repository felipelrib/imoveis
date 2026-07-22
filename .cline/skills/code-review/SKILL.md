---
name: code-review
description: Review staged or diffed changes for guardrail violations, missing tests, and code quality issues. Use when the user says "review my code", "check this diff", or "pre-commit check".
---

# Code Review

Analyses the current git diff against project guardrails and produces a structured review.

## Scope

Review ALL staged changes (or diff against `main` if nothing staged). For each
changed file, check:

1. **Secrets & credentials** — no `imoveis_secret`, `dev-secret-key`, hardcoded passwords, API keys, or tokens.
2. **Hardcoded ports** — no `5432`, `6379`, `8000`, `5173` or `localhost` URLs (env vars only).
3. **Missing tests** — new functions/classes should have corresponding tests.
4. **Conventional commit** — `git log -1 --format=%s` matches `feat:|fix:|test:|docs:|refactor:|chore:`.
5. **Scope creep** — files changed should match `implementation_plan.md`. If >3 unexpected files, flag it.
6. **Linter violations** — run lint via `validate.sh`.
7. **Print statements** — no `print()` in production code.
8. **Test anti-patterns** — no `.only()` or `.skip()` without a comment.
9. **SQL injection** — no f-strings or string concatenation in SQL.
10. **Circular imports** — check new Python files for import cycles.

## Steps

```bash
# 1. Get the diff
git diff --staged --name-only  ||  git diff main --name-only

# 2. Run lint
bash scripts/agent/validate.sh fast

# 3. Check for secrets in the diff
git grep -nP "(imoveis_secret|dev-secret-key|password\s*=\s*['\"][a-zA-Z0-9])" $(git diff --staged --name-only)

# 4. Check commit message
git log -1 --format=%s
```

## Output

```
## Code Review — <branch or commit>

### ✅ Passed
- [x] No hardcoded secrets
- [x] No hardcoded ports
- [x] Linter clean

### ❌ Issues Found
- [ ] **Missing test** — `src/core/new_feature.py` adds `calculate_score()` without a test.
- [ ] **Scope creep** — `src/adapters/db/models.py` modified but not in plan.

### 📋 Recommendations
- Consider adding a contract test for `/api/properties/filter`.

### Summary
N issues, N recommendations. Ready to commit after fixing.
```
