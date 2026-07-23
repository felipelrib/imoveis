# rotating-proxy-scraper-http — Shared proxy-aware HTTP clients for scrapers

> Feature branch: `feat/bin-48-rotating-proxy-scraper-http` · Linear: `BIN-48` · Status: implemented

## Problem

Scrapers built `httpx.Client` with only platform `extra.proxy`, while the typed
global `AppConfig.proxy` pool from Story 3.1 was unused. Rotation was not part
of the BaseScraper contract (AD-5), so each platform would reinvent proxy wiring.

## Approach

- Add a shared helper that resolves a proxy URL from `ProxyConfig` (disabled /
  single `url` / `pool` with `round_robin` or `random`) and builds `httpx.Client`.
- Expose `BaseScraper.create_http_session()` so QuintoAndar and OLX share one path.
- Platform `extra.proxy`: non-null string is a fixed override; `null`/absent defers
  to the global pool (one behaviour, unit-tested).
- Select once per session at `start()`; round-robin uses a process-local counter.

## Changes

Files touched:

```
 src/adapters/scrapers/http_client.py                 | NEW — resolve_proxy_url + create_scraper_http_client
 src/adapters/scrapers/base.py                        | ADD — create_http_session()
 src/adapters/scrapers/olx.py                         | UPDATE — start() uses create_http_session
 src/adapters/scrapers/quintoandar.py                 | UPDATE — start() uses create_http_session
 src/tests/unit/test_scraper_http_client.py           | NEW — rotation / override / disabled tests
 src/tests/unit/test_olx.py                           | UPDATE — lifecycle mocks create_http_session
 src/tests/unit/test_quintoandar.py                   | UPDATE — lifecycle mocks create_http_session
 configs/app_config.yaml                              | UPDATE — document override vs global pool
 docs/features/35-rotating-proxy-scraper-http.md      | NEW — this doc
 _bmad-output/implementation-artifacts/sprint-status.yaml | UPDATE — 3-2 done
```

## New Dependencies

None.

## How to Test

1. Unit tests (no network):
   ```bash
   bash scripts/agent/validate.sh fast
   ```
2. Scraper gate after HTTP wiring change:
   ```bash
   bash scripts/agent/validate-scrapers.sh --require-live
   ```
3. With proxy disabled (default YAML), scrapers still connect directly.

## Notes / Follow-ups

- Related: BIN-47 (AppConfig proxy settings), BIN-49 (operator enablement /
  observability) — **done** (`docs/features/36-operator-proxy-observability.md`).
- Round-robin state is process-local (per Celery worker); not shared across
  processes.
