# OLX description enrich — real-oracle extractor fix + backfill runbook

> Feature branch: `claude/bin-244-c605f2` · Linear: `BIN-244` · Status: implemented

## Problem

Follow-up to [BIN-243](https://linear.app/felipelrib/issue/BIN-243) for the two items that could
not be verified without a way past OLX's Cloudflare challenge (OLX 403s plain HTTP clients).
[BIN-246](https://linear.app/felipelrib/issue/BIN-246) unblocked this by adding the FlareSolverr
headless-browser sidecar and, during its spike, captured a **real** OLX detail page as a fixture
(`olx_detail_real.html`) — the previous `olx_detail*.html` stubs were hand-written synthetic
~300–560 byte blobs, never validated against production HTML.

Verifying `extract_olx_description` against that real oracle surfaced a defect the synthetic
fixtures hid:

- Real OLX detail pages carry the seller's ad body in a **schema.org JSON-LD block**
  (`RentAction`/`SaleAction` → `Object.description`, or a bare `Product.description`) — **not** in
  `__NEXT_DATA__` or the Flight payload the extractor targets.
- That field is **HTML** (`<br>`-separated lines). The extractor only caught it by accident via
  the crude whole-page `_first_body_in_text` regex, and returned the raw text — so ~1.8 KB of
  `<br>`-littered markup would have flowed into sentiment enrichment
  ([BIN-242](https://linear.app/felipelrib/issue/BIN-242)) and rendered as literal `<br>` in the
  dashboard. QuintoAndar descriptions are already tag-stripped; OLX ones were not.

## Approach

- **Explicit JSON-LD path** (`_olx_from_json_ld`): parse `application/ld+json` blocks and pull the
  ad `description`, preferring one reached through a nested ad entity (`Object`/`mainEntity`/…) or
  on an ad-typed node (`RentAction`, `SaleAction`, `Product`, …) so a generic `WebPage`/breadcrumb
  `description` (SEO decoy) never wins. Ordered **after** `__NEXT_DATA__` and Flight, **before** the
  crude regex — the regex stays as a last resort for truncated captures (the committed fixture is a
  byte-exact *slice*, so its JSON-LD block is intentionally unclosed and falls through to it).
- **Markup cleanup** (`_clean_olx_body`): turn `<br>` into separators, strip any remaining tags via
  BeautifulSoup, collapse whitespace — the same plain-text contract the QA extractor honours.
  Applied to **every** OLX source (JSON-LD, `__NEXT_DATA__`, Flight), so live scrapes and the
  backfill both persist clean text.
- **Backfill needs no code change.** `scripts/dev/backfill_listing_descriptions.py` builds the
  scraper through `create_http_session`, which already routes GETs through FlareSolverr when
  `scraping.cloudflare_bypass` is enabled (BIN-246). Enabling the bypass is a config/runbook step,
  not a code change — see *How to Test*.

## Changes

Files touched:

```
 src/adapters/scrapers/listing_description.py | JSON-LD extraction path + <br>/tag cleanup for OLX; extract_olx_description now returns clean plain text
 src/tests/unit/test_listing_description.py   | Strengthened real-fixture assertions (no markup); new JSON-LD decoy-precedence + __NEXT_DATA__-cleanup tests
 docs/features/BIN-244-olx-description-oracle-fix-and-backfill.md | NEW — this doc
```

## New Dependencies

None. (BeautifulSoup / httpx already in `requirements.txt`.)

## How to Test

Extractor (fully covered, no network needed):

```bash
bash scripts/agent/validate.sh fast
```

Backfill (requires a bypass-capable environment — FlareSolverr reachable and able to clear OLX):

1. Enable the bypass in `configs/app_config.yaml` → `scraping.cloudflare_bypass.enabled: true`.
2. Start the sidecar: `docker compose --profile bypass up -d flaresolverr`.
3. Dry-run OLX only (fetches through the bypass; reports how many rows *would* update):
   ```bash
   PYTHONPATH=src python scripts/dev/backfill_listing_descriptions.py --platform olx --limit 20
   ```
4. Apply once the dry-run shows non-zero `would_update`:
   ```bash
   PYTHONPATH=src python scripts/dev/backfill_listing_descriptions.py --apply --platform olx
   ```
5. Spot-check: `SELECT description FROM properties WHERE platform='olx' AND COALESCE(TRIM(description),'')<>'' LIMIT 5;`
   — text should be clean (no `<br>`), and `embed_property` re-enqueues on the `ai` queue.

## Notes / Follow-ups

- **Backfill execution is environment-gated.** It could not be run from the dev/CI environment,
  where OLX returns Cloudflare 403 without the sidecar + a clean egress IP (the BIN-243/246 saga).
  The extractor is oracle-verified and the backfill wiring is confirmed; the one-time apply is a
  manual op to run in a bypass-capable environment via the runbook above.
- After the backfill populates real OLX descriptions, re-run the
  [BIN-242](https://linear.app/felipelrib/issue/BIN-242) Gemini-vs-Ollama sentiment A/B on OLX rows.
- The committed `olx_detail_real.html` is a byte-exact *slice*; its JSON-LD block is deliberately
  unclosed, so this ticket's fixture exercises the regex-fallback + cleanup path. A future full-page
  capture would additionally exercise `_olx_from_json_ld` end-to-end.
