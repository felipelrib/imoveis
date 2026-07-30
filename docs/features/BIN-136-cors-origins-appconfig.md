# CORS Origins AppConfig — stop hardcoding the frontend allowlist in main.py

> Feature branch: `feat/move-cors-origins-to-appconfig` · Linear: `BIN-136` · Status: implemented

## Problem

`src/api/main.py` built `CORSMiddleware` with a literal Python list —
`["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"]`
— instead of sourcing it from `configs/app_config.yaml`. This violated the
project's "single source of truth for all settings" convention and the
CLAUDE.md ban on hardcoded ports/URLs.

Failure scenario: any deployment with a different frontend origin (staging
domain, LAN IP, custom port) required a code change and API image redeploy
instead of a config edit.

## Approach

- Added `ApiConfig` (`api.cors_origins: list[str]`) to `AppConfig` in
  `src/infra/config.py`, following the existing pattern used by
  `UiConfig`/`ProxyConfig` (frozen `BaseModel`, `default_factory`). The
  default preserves the previous hardcoded three-origin allowlist so local
  dev keeps working unchanged.
- `configs/app_config.yaml` gained an `api:` section (placed next to `auth:`)
  declaring the same three origins explicitly, plus a header-comment entry
  documenting the generic `IMOVEIS_API__CORS_ORIGINS` env override (existing
  generic `IMOVEIS_<SECTION>__<KEY>` mechanism — no new env-parsing code
  needed).
- `main.py` now reads `get_config().api.cors_origins` instead of the literal
  list.
- Swept `src/api/` for other hardcoded literal ports/URLs per the ticket's
  acceptance criteria (`grep -rn "localhost\|127.0.0.1\|http://\|https://"`
  and a `:[0-9]{4,5}` port-literal scan across `src/api/`) — the CORS list
  was the only hit. No follow-up ticket needed.

## Changes

Files touched:

```
src/infra/config.py            | NEW — ApiConfig class + AppConfig.api field
src/api/main.py                | FIX — CORSMiddleware reads cfg.api.cors_origins instead of a literal list
configs/app_config.yaml        | NEW — api.cors_origins section + env-override header comment
src/tests/unit/test_config.py  | NEW — defaults, YAML override, frozen, and real-config coverage for api.cors_origins
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
```

`src/tests/unit/test_config.py::test_cors_origins_defaults`,
`test_cors_origins_from_yaml`, `test_api_config_is_frozen`, and
`test_real_config_exposes_cors_origins` lock the new config surface.

## Notes / Follow-ups

- Tracked as part of the BIN-128 tech-debt remediation epic (v0.10
  milestone). Epic parent: BIN-128.
- The `api:` sweep found no other hardcoded ports/URLs in `src/api/` beyond
  the CORS list at the time of this change — nothing deferred.
