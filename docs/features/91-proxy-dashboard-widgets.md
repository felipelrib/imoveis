# proxy-dashboard-widgets — Read-only proxy mode / pool health on Dashboard

> Feature branch: `feat/bin-124-proxy-dashboard-widgets` · Linear: `BIN-124` · Status: implemented

## Problem

Operators could see safe proxy signals in Redis / logs (BIN-49) but the System
Dashboard had no widget for proxy enabled/mode/pool readiness. Misconfigured
proxy (enabled with empty pool) was invisible from the UI.

## Approach

- Extend `GET /system/pipeline` with a top-level `proxy` summary built from
  existing `proxy_mode_summary` / `resolve_proxy_url` (no new credential surface).
- Derive `health`: `direct` | `ok` | `warn` from config readiness only (no
  per-proxy success metrics exist).
- Render a read-only Proxy card on the Dashboard Service Status grid and a
  one-line mode summary on Scraper Control Live Pipeline.
- Never display userinfo or raw pool URLs with credentials — only redacted hosts.

## Changes

Files touched:

```
 src/api/system.py                                      | ADD — _pipeline_proxy_summary + pipeline.proxy
 src/api/schemas.py                                     | ADD — PipelineResponse.proxy
 src/tests/unit/test_pipeline_proxy_summary.py          | NEW — safe fields + credential redaction
 frontend/src/pages/Dashboard.jsx                       | ADD — proxy-health-card widget
 frontend/src/pages/ScraperControl.jsx                  | ADD — live proxy mode line
 frontend/src/i18n/locales/en.json                      | ADD — dashboard/scraper proxy strings
 frontend/src/i18n/locales/pt-BR.json                   | ADD — PT translations
 frontend/tests/e2e/helpers/apiMocks.js                 | ADD — default pipeline.proxy mock
 frontend/tests/e2e/dashboard.spec.js                   | ADD — Direct + Pool widget asserts
 docs/features/37-operator-proxy-observability.md       | UPDATE — strike no-widgets follow-up
 docs/features/91-proxy-dashboard-widgets.md            | NEW — this doc
```

## New Dependencies

None.

## How to Test

1. Unit + e2e gate:
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Manual: open Dashboard — Proxy card shows Direct when `proxy.enabled: false`.
3. Enable a pool in `configs/app_config.yaml`, restart API, confirm card shows
   Pool and pool size without passwords. Trigger a scrape and confirm Scraper
   Control Live Pipeline shows the same mode (and redacted host when running).

## Notes / Follow-ups

- Parent epic: BIN-104 (v0.9 feature follow-up backlog).
- Per-proxy latency / error rates remain out of scope (no telemetry yet).
- Related: BIN-47, BIN-48, BIN-49.
