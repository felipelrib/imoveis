# AppConfig-backed API credential — Edge auth via AppConfig with a stable principal

> Feature branch: `feat/bin-44-appconfig-api-credential` · Linear: `BIN-44` · Status: implemented

## Problem

API credentials were read with ad-hoc `os.environ` in `auth.py`, `verify_api_key` was unused, and `/admin` relied on JWT secrets outside AppConfig. That violated AD-2 (settings only via AppConfig) and blocked a single principal model (AD-11) for favourites / searches / watchlist ownership.

## Approach

- Add frozen `AuthConfig` (`api_key`, `jwt_secret`, `principal_id`, `admin_user`, `admin_pass`) on `AppConfig`, with env wiring (`API_KEY`, `JWT_SECRET`, `ADMIN_*`, `IMOVEIS_AUTH__*`).
- `verify_api_key` validates `X-API-Key` against AppConfig and returns `Principal(id=principal_id, method="api_key")`.
- `/admin` uses `verify_admin_access`: valid API key **or** admin JWT, both mapping to the same `principal_id` (SPA JWT login kept until Story 2.2 / BIN-46).
- No `os.environ` / `os.getenv` remains in `api/auth.py`.
- `validate.sh` defaults to `test-local-api-key` (not the forbidden `dev-secret-key` literal).

## Changes

Files touched:

```
 src/infra/config.py                         | AuthConfig + API_KEY/JWT/ADMIN env wiring
 configs/app_config.yaml                     | auth: section (empty secrets)
 docker-compose.yml                          | API_KEY / JWT_SECRET passthrough
 src/api/auth.py                             | Principal, AppConfig-backed verify, dual admin access
 src/api/admin.py                            | Depends(verify_admin_access)
 src/tests/unit/test_auth.py                 | NEW — missing/invalid/valid credential tests
 src/tests/unit/test_config.py               | Auth env override cases
 src/tests/integration/test_e2e.py           | admin_headers use X-API-Key
 src/tests/contract/test_api_contract.py     | Configured API key for admin contracts
 scripts/agent/validate.sh                   | Neutral test API_KEY / JWT_SECRET defaults
 .github/workflows/ci.yml                    | JWT_SECRET for integration job
 docs/features/07-rest-api.md                | Point auth at AppConfig
 docs/features/18-admin-control-panel.md     | Dual-accept note + AppConfig
 _bmad-output/.../sprint-status.yaml         | Epic 2 in-progress; 2-1 done
```

## New Dependencies

None.

## How to Test

1. Set credentials (never commit real values):
   ```bash
   export API_KEY=test-local-api-key
   export JWT_SECRET=test-local-jwt-secret
   ```
2. Call a protected route without a credential — expect 401:
   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/admin/health
   ```
3. Call with a valid key — expect 200:
   ```bash
   curl -s -H "X-API-Key: $API_KEY" http://localhost:8000/admin/health
   ```
4. Automated:
   ```bash
   bash scripts/agent/validate.sh backend
   ```

## Notes / Follow-ups

- Story 2.2 ([BIN-46](https://linear.app/felipelrib/issue/BIN-46)): frontend credential gate (sessionStorage / paste-once); SPA can drop admin JWT once the UI sends `X-API-Key`.
- Story 2.3 ([BIN-45](https://linear.app/felipelrib/issue/BIN-45)): owner-scope favourites / saved searches / watchlist using `Principal.id`.
- CORS `allow_headers` still lists `X-API-Key` (and not `Authorization`); Vite `/api` proxy continues to cover the admin JWT path for the SPA.
