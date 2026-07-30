# Harden admin/auth endpoints — fail-closed default creds + remove mock JWT login

> Feature branch: `feat/harden-admin-auth` · Linear: `BIN-131` · Status: implemented

## Problem

Two related auth findings surfaced by the 2026-07-29 technical debt audit (epic BIN-128):

1. **Hardcoded default admin credentials.** `AuthConfig.admin_user`/`admin_pass` defaulted to the
   literal strings `"admin"`/`"admin"`, contradicting the class's own docstring ("secrets are empty
   by default") and the pattern already used by `api_key`/`jwt_secret` (both `""`). Any deployment
   that forgot to set `ADMIN_USER`/`ADMIN_PASS` (new environment, a Compose profile missing the env
   block) exposed admin JWT issuance behind trivially-guessable `admin`/`admin`.
2. **Unauthenticated mock JWT-issuing endpoint left live.** `/auth/token` issued a valid, 30-day
   signed JWT for `role: "user"` to any username with no password check at all — the docstring
   literally said "mock authentication." Its consumer, `verify_jwt`, was unused anywhere else in
   `src/api`, so this was dead functionality today but a live, reachable endpoint minting real
   signed tokens — a bypass waiting to be inherited by whatever route was next gated with
   `verify_jwt`.

## Approach

- `AuthConfig.admin_user`/`admin_pass` now default to `""` (both `src/infra/config.py` and the
  `auth:` block in `configs/app_config.yaml`), matching `api_key`/`jwt_secret`.
- `login_for_admin_token` (`POST /auth/admin/login`) now calls a new
  `_require_admin_credentials_configured(cfg)` guard before comparing credentials, returning
  `403 Admin credentials not configured` when either `admin_user` or `admin_pass` is unset — the
  same fail-closed pattern `_jwt_secret()` already used for the JWT secret.
- Removed `POST /auth/token` (`login_for_access_token`) entirely rather than gating or
  dev-flagging it: it had no real caller (frontend, docs, or other tests), and deleting it closes
  the vulnerability outright — the only way to mint a JWT is now the credential-gated
  `/auth/admin/login`. Updated `oauth2_scheme`/`oauth2_scheme_optional`'s `tokenUrl` (OpenAPI/Swagger
  metadata only) to point at `/auth/admin/login` since it's now the sole issuer.
- Kept `verify_jwt` (bare signature/claims check, no credential check of its own) since it's a
  reasonable primitive for a future non-admin auth route, but documented in its docstring that any
  route wiring `Depends(verify_jwt)` must pair it with an explicit credential-check dependency
  (`verify_admin_jwt` / `verify_api_key` / `verify_admin_access`) upstream.
- Added a guardrail test, `test_no_route_depends_on_verify_jwt_without_credential_check`, that
  walks the live FastAPI route tree (handling both plain `APIRouter` nesting and the newer FastAPI
  `_IncludedRouter` wrapper, whose real routes live on `.original_router.routes`), collects each
  route's full dependency-call set, and fails if any route depends on `verify_jwt` without also
  depending on one of the credential-check functions. Today it passes trivially (no route uses
  `verify_jwt`) but will catch the exact regression the ticket warned about if a future PR adds one
  ungated.

## Changes

Files touched:

```
 src/infra/config.py                | AuthConfig.admin_user/admin_pass default "" (was "admin"/"admin")
 configs/app_config.yaml            | auth.admin_user/admin_pass sample values "" (was admin/admin)
 src/api/auth.py                    | fail-closed admin login guard; removed mock /auth/token endpoint; oauth2_scheme tokenUrl updated
 src/tests/unit/test_auth.py        | NEW — fail-closed admin login, /auth/token removed, verify_jwt guardrail test
 docs/features/BIN-131-harden-admin-auth.md | NEW — this file
```

## New Dependencies

None.

## How to Test

1. Automated regression suite:
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Targeted tests:
   ```bash
   PYTHONPATH=src pytest src/tests/unit/test_auth.py -v -m unit
   ```
3. Manual check — with `ADMIN_USER`/`ADMIN_PASS` unset, `POST /auth/admin/login` returns
   `403 {"detail": "Admin credentials not configured"}` regardless of the submitted
   username/password. `POST /auth/token` returns `404`.

## Notes / Follow-ups

- `verify_jwt` remains in `src/api/auth.py` unused today (kept as a primitive for a future
  non-admin JWT flow); the new guardrail test is the safety net if it's ever wired to a route
  without an explicit credential check.
- No `docker-compose.yml` / CI / `.env.local.example` files set `ADMIN_USER`/`ADMIN_PASS`, and no
  integration/e2e/contract test exercises admin login, so this change has no effect on other
  validation gates.
