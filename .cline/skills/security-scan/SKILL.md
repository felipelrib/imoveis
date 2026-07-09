---
name: security-scan
description: Scan the codebase for security vulnerabilities: hardcoded secrets, SQL injection, XSS, unsafe deserialization. Use when the user says "security scan" or "audit for vulnerabilities".
---

# Security Scan

Comprehensive security audit of the codebase against OWASP Top 10 and
framework-specific vulnerabilities.

## Scope

Scan ALL source files in `src/` and `frontend/src/` for:

1. **Hardcoded secrets** — passwords, API keys, tokens, credentials.
2. **SQL injection** — f-strings or string concatenation in SQL.
3. **XSS vectors** — `dangerouslySetInnerHTML` without sanitization.
4. **Unsafe deserialization** — `pickle.load()`, `yaml.load()` without `SafeLoader`.
5. **Command injection** — `os.system()`, `subprocess.call()` with user input.
6. **Path traversal** — file operations without path validation.
7. **Insecure dependencies** — run `pip-audit` and `npm audit`.
8. **Exposed debug endpoints** — routes that leak stack traces or internal state.

## Steps

```bash
# 1. Secrets search
git grep -nP "(password|secret|api_key|token).*=.*['\"][a-zA-Z0-9!@#$%^&*]" src/ frontend/src/ -- "*.py" "*.js" "*.jsx" "*.yaml" "*.yml"
git grep -n "imoveis_secret\|dev-secret-key" src/ frontend/src/

# 2. SQL injection patterns
git grep -nP "(f['\"]|\.format\(|%s|%\().*SELECT|INSERT|UPDATE|DELETE" src/ -- "*.py"

# 3. XSS vectors (React)
git grep -n "dangerouslySetInnerHTML" frontend/src/ -- "*.js" "*.jsx"

# 4. Unsafe deserialization
git grep -nP "(pickle\.load|yaml\.load\()" src/ -- "*.py"

# 5. Command injection
git grep -nP "(os\.system|subprocess\.call|eval\()" src/ -- "*.py"

# 6. Dependency audit
pip-audit --requirement requirements.txt
cd frontend && npm audit

# 7. Exposed secrets in config files
git grep -nP "(password|secret).*[a-zA-Z0-9!@#$%^&*]{8,}" configs/ -- "*.yaml" "*.yml"
```

## Output

Produce a structured security report:

```
## Security Scan Report

### 🔴 Critical
- **Hardcoded password** — `src/api/auth.py:6`: `API_KEY = "dev-secret-key"`. Use `os.getenv("API_KEY")`.

### 🟡 Medium
- **Unsafe deserialization** — `src/utils/data.py:42`: `pickle.load(f)`. Use `json.load()` or validate with a schema.

### 🟢 Low / Info
- **npm audit**: 3 low-severity warnings (see `npm audit` for details).

### Summary
Critical: 1, Medium: 1, Low: 3. Fix Critical issues before deploying.
```

## Integration with CI

The `security-scan` job in `.github/workflows/ci.yml` runs Trivy on push to `main`.
This skill should be run pre-commit to catch issues earlier. The pre-commit hook
`detect-private-key` in `.pre-commit-config.yaml` also catches key files.

## Exclusions

The following patterns are acceptable and should NOT be flagged:
- `password: ""` (empty-string default) — valid.
- `test_password` — valid in test files and CI service definitions.
- `API_KEY = os.getenv("API_KEY")` without a default — correct pattern.