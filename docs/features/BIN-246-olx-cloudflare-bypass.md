# OLX Cloudflare bypass — headless-browser fetch backend

> Feature branch: `feat/bin-246-olx-cloudflare-bypass` · Linear: `BIN-246` · Status: implemented

## Problem

OLX returns a Cloudflare JS challenge (HTTP 403) to every plain HTTP request in
this environment, blocking OLX scraping and the OLX description backfill/verify
work in [BIN-244](https://linear.app/felipelrib/issue/BIN-244). Free proxy pools
do **not** help: they are public datacenter IPs that Cloudflare challenges
identically (empirically, 345 ProxyScrape + 150 Proxifly proxies → every one that
reached OLX got the same `cf-ray` 403 — see [BIN-246] rationale). The block is a
browser/JS/TLS challenge, not (for this host) IP reputation.

## Approach

**Spike (2026-07-31) — decisive.** A real headless Chromium (the node Playwright +
chromium already installed for the e2e suite) fetched OLX from this host's
**residential Brazilian IP** with **HTTP 200 and no challenge** on the search hub,
search results, *and* detail pages. Our existing parsers then worked unchanged on
the rendered HTML: `_extract_flight_ads` found 50 ads on a results page and
`extract_olx_description` pulled an 1,870-char ad body from a detail page. So the
three things Cloudflare wants — residential IP + real TLS fingerprint + JS
execution — are all satisfiable locally; no paid residential proxy is needed.

**Integration — FlareSolverr sidecar.** Rather than embed a browser in the Python
worker image, the winning approach runs [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr)
as an opt-in compose sidecar. It exposes a `/v1` HTTP API (`{cmd:"request.get",url}`
→ solved HTML). The scraper's HTTP session is swapped for a drop-in that POSTs to
it:

- `FlareSolverrSession.get()` returns a real `httpx.Response` (status/text/url), so
  platform scrapers need **zero** changes — throttling and circuit-breaker logic in
  `_throttled_request` stay put, and an upstream 403 still surfaces as a `Response`
  the breaker can see (not an exception).
- Wiring lives at the single choke point `BaseScraper.create_http_session`: when
  `scraping.cloudflare_bypass.enabled` and the platform is listed, it returns the
  FlareSolverr session instead of the httpx client. Default off → direct httpx.
- The sidecar is behind a compose **profile** (`--profile bypass`) so the default
  stack never pulls the ~1 GB image.

## Changes

Files touched:

```
 src/infra/config.py                                       | CHANGED — add CloudflareBypassConfig; scraping.cloudflare_bypass
 src/adapters/scrapers/flaresolverr.py                     | NEW — FlareSolverrSession drop-in (returns httpx.Response) + FlareSolverrError
 src/adapters/scrapers/base.py                             | CHANGED — create_http_session routes matching platforms through the bypass session
 configs/app_config.yaml                                   | CHANGED — scraping.cloudflare_bypass block (default off)
 docker-compose.yml                                        | CHANGED — flaresolverr service (profile: bypass)
 src/tests/unit/test_flaresolverr.py                       | NEW — session happy/403/error paths + base routing (mocked)
 src/tests/unit/test_config.py                             | CHANGED — cloudflare_bypass defaults
 src/tests/unit/test_listing_description.py                | CHANGED — extract_olx_description on a real captured page
 src/tests/fixtures/scrapers/olx_detail_real.html          | NEW — byte-exact real OLX detail slice (feeds BIN-244)
 docs/setup.md                                             | CHANGED — § Cloudflare bypass (OLX)
 docs/features/BIN-246-olx-cloudflare-bypass.md            | NEW — this doc
```

## New Dependencies

None in Python (`FlareSolverrSession` uses the existing `httpx`). Operationally, an
opt-in Docker image `ghcr.io/flaresolverr/flaresolverr:v3.3.21`, pulled only when
running `docker compose --profile bypass`.

## How to Test

```bash
bash scripts/agent/validate.sh backend
```

Targeted:

```bash
PYTHONPATH=src python -m pytest src/tests/unit/test_flaresolverr.py src/tests/unit/test_listing_description.py -q
```

Live (opt-in): start the sidecar and enable the config (see
`docs/setup.md § Cloudflare bypass`), then run a small OLX scrape and confirm
`scraper_cloudflare_bypass` + `flaresolverr_fetch` logs and a 200 payload.

## Notes / Follow-ups

- **Unblocks [BIN-244](https://linear.app/felipelrib/issue/BIN-244)** (OLX detail
  extractor live-verify + backfill). The captured `olx_detail_real.html` fixture is
  provided as its oracle.
- **BIN-244 polish:** `extract_olx_description` returns the ad body with literal
  `<br>` tags (e.g. `"...consta com:<br><br>2 quartos;<br>"`). Strip/normalize them
  before feeding sentiment. `**BUG (Low)**`: HTML tags leak into the extracted OLX
  description — normalize in BIN-244.
- FlareSolverr runs a headed browser and is heavier/slower than httpx (seconds per
  request); it is intentionally OLX-only and opt-in. For unattended production at
  scale, revisit rate limits and consider a managed browser/bypass service.
- The residential-IP dependency is the host's egress IP. Inside Docker the worker's
  egress is the host IP (NAT), so the same IP applies — but a datacenter-hosted
  deployment would lose the residential advantage and may need a residential proxy
  in front of FlareSolverr.

[BIN-246]: https://linear.app/felipelrib/issue/BIN-246
