---
name: security-scan
description: >-
  Scan the codebase for security vulnerabilities: hardcoded secrets, SQL
  injection, XSS, unsafe deserialization. Use when the user says "security scan"
  or "audit for vulnerabilities".
---

# Security Scan

Audit `src/` and `frontend/src/` against common OWASP issues.

## Scope

1. Hardcoded secrets (passwords, API keys, tokens).
2. SQL injection (f-strings / concatenation in SQL).
3. XSS (`dangerouslySetInnerHTML` without sanitization).
4. Unsafe deserialization (`pickle.load`, `yaml.load` without SafeLoader).
5. Command injection (`os.system`, `subprocess` with user input, `eval`).
6. Path traversal.
7. Insecure dependencies (`pip-audit`, `npm audit`).
8. Exposed debug endpoints.

## Commands

```bash
git grep -nP "(password|secret|api_key|token).*=.*['\"][a-zA-Z0-9!@#$%^&*]" src/ frontend/src/ -- "*.py" "*.js" "*.jsx" "*.yaml" "*.yml"
git grep -n "imoveis_secret\|dev-secret-key" src/ frontend/src/
git grep -nP "(f['\"]|\.format\(|%s|%\().*SELECT|INSERT|UPDATE|DELETE" src/ -- "*.py"
git grep -n "dangerouslySetInnerHTML" frontend/src/ -- "*.js" "*.jsx"
git grep -nP "(pickle\.load|yaml\.load\()" src/ -- "*.py"
git grep -nP "(os\.system|subprocess\.call|eval\()" src/ -- "*.py"
pip-audit --requirement requirements.txt
(cd frontend && npm audit)
git grep -nP "(password|secret).*[a-zA-Z0-9!@#$%^&*]{8,}" configs/ -- "*.yaml" "*.yml"
```

## Exclusions (do NOT flag)

- `password: ""` empty defaults
- `test_password` in tests/CI service defs
- `API_KEY = os.getenv("API_KEY")` without a hardcoded default

## Output

```
## Security Scan Report

### Critical
- ...

### Medium
- ...

### Low / Info
- ...

### Summary
Critical: N, Medium: N, Low: N.
```

CI runs Trivy in `.github/workflows/ci.yml`; this skill catches issues earlier.
