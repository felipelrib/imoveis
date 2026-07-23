# Frontend credential gate — Paste-once sessionStorage API key for the SPA

> Feature branch: `feat/bin-46-frontend-credential-gate` · Linear: `BIN-46` · Status: implemented

## Problem

Admin and other protected SPA calls need an AppConfig-backed API key (BIN-44), but the React app must never ship hardcoded secrets (`VITE_API_KEY` was removed). Operators need a paste-once UI gate so credentials live only in client session storage and attach via `api.js` (AD-8).

## Approach

- Sidebar **CredentialGate**: paste API key → `sessionStorage` key `api_key` → validate with `GET /admin/health`.
- `apiFetch` attaches `X-API-Key` from sessionStorage only; SPA no longer sends admin JWT Bearer tokens.
- Invalid/missing credentials throw a stable message and surface as non-blocking toasts; browsing public pages still works.
- Pre-commit continues to forbid `dev-secret-key` / `imoveis_secret` in `frontend/src`.

## Changes

Files touched:

```
 frontend/src/api.js                              | sessionStorage helpers + X-API-Key; drop adminLogin/JWT
 frontend/src/components/CredentialGate.jsx       | NEW — sidebar paste-once gate
 frontend/src/App.jsx                             | Mount CredentialGate in System footer
 frontend/src/index.css                           | Compact credential-gate styles
 frontend/tests/e2e/credential-gate.spec.js       | NEW — save / invalid toast / clear
 frontend/tests/e2e/helpers/apiMocks.js           | mockAdminHealth
 docs/features/31-frontend-credential-gate.md     | NEW — this doc
 docs/features/30-appconfig-api-credential.md     | Story 2.2 follow-up marked done
 docs/features/18-admin-control-panel.md          | SPA gate note updated
 _bmad-output/implementation-artifacts/sprint-status.yaml | 2-2 → done
 mkdocs.yml                                       | Nav entry
```

## New Dependencies

None.

## How to Test

1. Set server `API_KEY` (never commit real values), e.g. `export API_KEY=test-local-api-key`.
2. Open the SPA → sidebar **API credential** → paste the same key → **Save**.
3. Status should show **set**; admin actions (pause workers, recalculate) should succeed.
4. Paste a wrong key → error toast; page remains usable; status stays **missing**.
5. Automated:
   ```bash
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- Story 2.3 ([BIN-45](https://linear.app/felipelrib/issue/BIN-45)): owner-scope favourites / saved searches / watchlist using `Principal.id`.
- Backend still accepts admin JWT for curl/scripts; SPA uses `X-API-Key` only.
