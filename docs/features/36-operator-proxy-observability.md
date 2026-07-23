# operator-proxy-observability — Safe proxy mode signals and operator enablement docs

> Feature branch: `feat/bin-49-operator-proxy-observability` · Linear: `BIN-49` · Status: implemented

## Problem

Operators could enable a rotating proxy pool via AppConfig (Stories 3.1–3.2) but had no
safe runtime signal that proxy mode was active, and no first-class docs for turning the
pool on/off. Guessing from silent direct connections makes scale/anti-block work brittle.

## Approach

- Add `redact_proxy_url` / `proxy_mode_summary` so logs and metrics never include userinfo.
- Emit structured log `scraper_proxy_mode` when each scraper HTTP client is created.
- Attach the same safe fields to Redis `pipeline:scraper:*:status` (visible via
  `/system/pipeline`) for the duration of a scrape run.
- Document enable/disable in `docs/setup.md` and YAML comments; disabling returns to
  direct mode on the next scrape without code changes (config already drives resolution).

## Changes

Files touched:

```
 src/adapters/scrapers/http_client.py                 | ADD — redact, summary, log on client create
 src/adapters/scrapers/base.py                        | ADD — proxy_summary on session create
 src/adapters/queue/tasks.py                          | UPDATE — Redis status includes proxy fields
 src/tests/unit/test_scraper_http_client.py           | ADD — redaction / mode / log safety tests
 src/tests/unit/test_scrape_proxy_observability.py    | NEW — Redis status + scrape start signal
 configs/app_config.yaml                              | UPDATE — operator enablement comments
 docs/setup.md                                        | ADD — Proxy rotation section
 docs/features/36-operator-proxy-observability.md     | NEW — this doc
 _bmad-output/implementation-artifacts/sprint-status.yaml | UPDATE — 3-3 done
```

## New Dependencies

None.

## How to Test

1. Unit tests:
   ```bash
   bash scripts/agent/validate.sh fast
   ```
2. Scraper gate (HTTP client touched):
   ```bash
   bash scripts/agent/validate-scrapers.sh --require-live
   ```
3. Manual: set `proxy.enabled: true` with a pool, restart workers, trigger a scrape, confirm
   `scraper_proxy_mode` in logs and `proxy_mode` on the Redis status key without passwords.
4. Set `enabled: false`, restart, confirm `proxy_mode: direct` on the next run.

## Notes / Follow-ups

- Related: BIN-47 (AppConfig), BIN-48 (HTTP rotation) — Epic 3 / FR-20 complete with this story.
- Round-robin remains process-local per Celery worker (unchanged from BIN-48).
- No frontend dashboard widgets for proxy mode (out of scope).
