# Gate /system/* introspection endpoints behind auth — consistent admin-surface credential gate

> Feature branch: `feat/gate-system-endpoints-auth` · Linear: `BIN-150` · Status: implemented

## Problem

In `src/api/system.py`, only `POST /system/ollama/ensure` had
`dependencies=[Depends(verify_admin_access)]`. `GET /system/status`,
`/system/pipeline`, `/system/pipeline/history`, `/system/alerts`, and
`/system/ollama/status` were all open — inconsistent with the auth discipline
already applied across `admin.py` (router-level `verify_admin_access`) and
`GET /properties/export` (`verify_api_key_if_configured`).

Any unauthenticated caller could read queue depths, worker node names,
proxy-pool health, DB/Redis/Ollama connectivity, and the last 100 price-drop
alerts (with `property_id` + price) — internal topology and pricing-signal
disclosure. Not itself a write/abuse vector, but inconsistent with the rest of
the admin surface and flagged in the 2026-07-29 technical debt audit.

## Approach

- **Checked the frontend call sites first** (the ticket's explicit
  acceptance-criteria gate): `frontend/src/api.ts` calls `fetchStatus`
  (`GET /system/status`), `fetchPipeline` (`GET /system/pipeline`),
  `fetchPipelineHistory` (`GET /system/pipeline/history`), and `fetchAlerts`
  (`GET /system/alerts`) via bare, unauthenticated `fetch()`. These are wired
  into `App.jsx`'s persistent status chrome (`useSystemStatus`, polled on
  every page), `Dashboard.jsx` (pipeline chart, alerts feed), and
  `ScraperControl.jsx` (pipeline status). `GET /system/ollama/status` is
  **not** called by the SPA at all — only its `POST /ollama/ensure` sibling
  is, and that already required admin credentials.
- Blanket-gating all five behind the full `verify_admin_access` (like
  `admin.py`) would have broken the Dashboard/App chrome for any request
  without a pasted admin credential — the exact regression the ticket warned
  against, and a real deployment risk since `.env.local.example` configures
  `API_KEY` by default.
- Instead, split the gate by actual usage, matching the existing Epic 2 edge
  rule already used for `GET /properties/export`:
  - `/status`, `/pipeline`, `/pipeline/history`, `/alerts` →
    `verify_api_key_if_configured` — anonymous access allowed only when no
    admin API key is configured server-side (dev/local default); a valid
    `X-API-Key` (or admin JWT) is required once one is configured.
  - `/ollama/status` → full `verify_admin_access` (same as `/ollama/ensure`)
    since nothing in the SPA depends on it being open.
- Updated `frontend/src/api.ts` to attach a stored `X-API-Key` header (when
  the user has pasted one via the BIN-46 paste-once credential gate) on the
  four SPA-facing calls, mirroring the existing `exportProperties` pattern,
  so the Dashboard keeps working end-to-end in both the unconfigured
  (anonymous) and configured (credentialed) deployment states. 401/403
  responses now surface the same `errors.invalidCredential` toast used
  elsewhere instead of the endpoint's generic fetch-failure message.

## Changes

Files touched:

```
 src/api/system.py                            | Added verify_api_key_if_configured to /status, /pipeline,
                                                 /pipeline/history, /alerts; verify_admin_access to /ollama/status
 frontend/src/api.ts                          | fetchStatus/fetchPipeline/fetchPipelineHistory/fetchAlerts now
                                                 attach X-API-Key when present and surface 401/403 as authErrorMessage
 src/tests/unit/test_system_auth_gating.py    | NEW — regression tests: all 5 routes reject anonymous access once
                                                 API_KEY is configured; the 4 SPA routes stay open when unconfigured;
                                                 /ollama/status stays gated either way
 src/tests/unit/test_system_status_counts.py  | Pin API_KEY="" explicitly (endpoint now auth-gated)
 src/tests/unit/test_pipeline_proxy_summary.py| Pin API_KEY="" explicitly (endpoint now auth-gated)
 src/tests/unit/test_pipeline_metric_snapshots.py | Pin API_KEY="" explicitly (endpoint now auth-gated)
 src/tests/contract/test_api_contract.py      | test_system_status_shape now passes admin_headers (contract
                                                 fixture always configures API_KEY); added
                                                 test_system_status_requires_key_when_configured
```

## New Dependencies

None.

## How to Test

1. `bash scripts/agent/validate.sh all`
2. Manual dashboard check: with `API_KEY` configured in `.env.local` and no
   credential pasted in the SPA, `GET /system/status` / `/pipeline` /
   `/pipeline/history` / `/alerts` return `403`; the Dashboard/App chrome
   degrade gracefully (existing error-state handling in `useSystemStatus`,
   `useAlerts`) rather than crashing. Pasting the API key via the BIN-46
   credential gate restores normal polling. With `API_KEY` unset, all four
   remain open with no credential.

## Notes / Follow-ups

- `GET /system/ollama/status` now always requires admin credentials — it
  isn't currently surfaced anywhere in the SPA, so this has no UI impact.
- BIN-46 (frontend paste-once credential gate) is the mechanism users rely on
  to keep the Dashboard working once an admin API key is configured; no
  changes needed there beyond attaching the stored key to these four calls.
