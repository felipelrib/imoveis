# Scraper regression gates — catch config/task wiring and OLX Flight drift in unit CI

> Feature branch: `feat/scraper-regression-gates` · Linear: n/a · Status: implemented

## Problem

Scraper platforms can look “broken” when the failure is outside scraper parsers:

1. `AppConfig` silently drops YAML sections (Pydantic extra ignore) that `scrape_listings` still reads — e.g. missing `DedupConfig` → every listing lands in `errors`.
2. Existing scrape unit tests mocked the entire config object, so that AttributeError never fired in CI.
3. OLX unit cassettes only covered `__NEXT_DATA__` while live pages use Next.js Flight ads.
4. Live dry-run (`scripts/dev/test_scraper_dryrun.py`) only normalizes QuintoAndar listings — it does not exercise `cfg.dedup` or persist.

## Approach

- Assert critical `app_config.yaml` sections exist as `AppConfig` fields (no silent drop).
- Add a `scrape_listings` happy-path unit test that uses a **real** `DedupConfig` and asserts `processed=1 / errors=0`.
- Commit a Flight HTML cassette so OLX’s non-`__NEXT_DATA__` path stays green in unit CI without live OLX (Cloudflare).

## Changes

Files touched:

```
 src/tests/unit/test_config.py                      | Critical YAML↔AppConfig contract tests
 src/tests/unit/test_scrape_listings_pipeline.py    | NEW — real DedupConfig scrape happy path
 src/tests/fixtures/scrapers/olx_search_flight.html | NEW — Flight ads cassette
 src/tests/unit/test_scraper_cassettes.py           | Flight cassette extract+normalize
 docs/features/40-scraper-regression-gates.md       | NEW — this note
 docs/features/39-fix-quintoandar-olx-scrapers.md | Note live dry-run vs unit gates
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh backend
bash scripts/agent/validate-scrapers.sh --require-live
```

Targeted:

```bash
.venv/bin/python -m pytest \
  src/tests/unit/test_config.py \
  src/tests/unit/test_scrape_listings_pipeline.py \
  src/tests/unit/test_scraper_cassettes.py \
  -q
```

## Notes / Follow-ups

- Live dry-run remains QuintoAndar-normalize-only; config + task unit gates cover the persist path.
- Do not force live OLX in CI while Cloudflare 403s are intermittent — Flight cassette is the unit stand-in.
- Cleaning legacy YAML `redis_url` would unlock `extra="forbid"` on `AppConfig` later (stronger than the critical-section allowlist).
