# Cloudflare bypass, generalized — enable OLX + auto-fallback for any provider

> Feature branch: `feat/bin-247-cloudflare-autofallback` · Linear: `BIN-247` · Status: implemented

## Problem

[BIN-246](https://linear.app/felipelrib/issue/BIN-246) added FlareSolverr as an opt-in sidecar but
shipped it **disabled** (`cloudflare_bypass.enabled: false`) and only ever routed an explicit
allowlist (`platforms: [olx]`) through it. Two gaps:

- It was never turned on, so OLX scrapes still hit the Cloudflare 403 wall.
- The allowlist model misses other gated providers. Of the three scrapers — **quintoandar, olx,
  zapimoveis** — **OLX** (403 on ~every request) and **ZAP Imóveis** (`zapimoveis_cloudflare_403`,
  intermittent) are Cloudflare-gated; **QuintoAndar is not**. A new gated provider would silently
  403 until someone manually added it to the list.

## Approach

- **Enable the bypass** in the shipped config (`enabled: true`). `platforms: [olx]` stays the
  **always-bypass** list — every OLX GET goes straight to FlareSolverr, since a direct attempt is
  guaranteed to 403 (pure waste).
- **`auto_fallback: true` (new, default on).** For any platform **not** on the always-list, the
  scraper fetches directly (fast httpx) and only retries a **Cloudflare 403** through FlareSolverr —
  then *sticks* to FlareSolverr for the rest of that scraper session, so a gated provider doesn't
  pay a wasted direct 403 (and trip its circuit breaker) on every subsequent request. Un-gated
  providers (QuintoAndar) never touch FlareSolverr. This makes a newly Cloudflare-gated provider —
  ZAP today, anything later — handled automatically with zero config and zero overhead for the rest.
- Implemented as `CloudflareFallbackSession`, a drop-in for the `.get()` / `.request()` / `.headers`
  / `.close()` surface the scrapers use — OLX/ZAP call `.get()`, QuintoAndar calls
  `.request("GET", …)` — wired in `BaseScraper.create_http_session` (both session types expose both
  verbs).
  403 is the Cloudflare signal the pipeline already uses (`_record_circuit_outcome` buckets it as
  `cloudflare_403`), so no new heuristic is introduced.

## Changes

Files touched:

```
 src/infra/config.py                        | CloudflareBypassConfig.auto_fallback (default True) + docs
 src/adapters/scrapers/flaresolverr.py      | NEW CloudflareFallbackSession (direct-first, sticky 403→FlareSolverr)
 src/adapters/scrapers/base.py              | create_http_session: always-list → FlareSolverr; else auto-fallback
 configs/app_config.yaml                    | cloudflare_bypass.enabled: true + auto_fallback: true (+ comments)
 src/tests/unit/test_flaresolverr.py        | fallback session tests (passthrough/403/sticky/lazy/close/headers) + wiring
 src/tests/unit/test_config.py              | auto_fallback model default + shipped-config enabled assertions
 docs/features/BIN-247-cloudflare-bypass-generalized-autofallback.md | NEW — this doc
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh fast
```

Operationally (requires the sidecar): `docker compose --profile bypass up -d flaresolverr`, then a
scrape — OLX routes through FlareSolverr from the first request; ZAP does so only after it hits a
403 (watch for the `cloudflare_autofallback_engaged` log line); QuintoAndar stays on direct httpx.

## Notes / Follow-ups

- **Deployment coupling:** with `enabled: true` the FlareSolverr sidecar must be running or OLX
  (always-list) scrapes fail. Un-gated providers and auto-fallback platforms degrade to their prior
  behaviour (direct httpx; a 403 just yields empty) if the sidecar is absent.
- The Cloudflare signal is HTTP 403 (consistent with the rest of the pipeline). If a provider ever
  challenges with 503, extend `CloudflareFallbackSession.get`'s trigger — noted, not needed today.
- Related: the OLX description backfill (BIN-244) uses this same sidecar.
