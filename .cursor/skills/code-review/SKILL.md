---
name: code-review
description: >-
  Review staged or diffed changes for guardrail violations, missing tests, and
  code quality. Use when the user says "review my code", "check this diff", or
  "pre-commit check".
---

# Code Review

Review ALL staged changes (or diff against `main` if nothing staged).

## Checklist

1. **Secrets** — no `imoveis_secret`, `dev-secret-key`, hardcoded passwords/tokens.
2. **Hardcoded ports** — no bare `5432`, `6379`, `8000`, `5173` or localhost URLs (env/config only).
3. **Missing tests** — new functions/classes need corresponding tests.
4. **Conventional commit** — latest message matches `feat:|fix:|test:|docs:|refactor:|chore:`.
5. **Scope creep** — unexpected files beyond the stated task; flag if >3.
6. **Lint** — `bash scripts/agent/validate.sh fast`.
7. **Print statements** — no `print()` in production code.
8. **Test anti-patterns** — no `.only()` / `.skip()` without a comment.
9. **SQL injection** — no f-strings/concatenation in SQL.
10. **Circular imports** — check new Python files.

## Commands

```bash
git diff --staged --name-only || git diff main --name-only
bash scripts/agent/validate.sh fast
git grep -nP "(imoveis_secret|dev-secret-key|password\s*=\s*['\"][a-zA-Z0-9])" $(git diff --staged --name-only 2>/dev/null)
git log -1 --format=%s
```

## Output

```
## Code Review — <branch or commit>

### Passed
- [x] ...

### Issues Found
- [ ] **Missing test** — ...

### Recommendations
- ...

### Summary
N issues, N recommendations.
```
