# QuintoAndar SSR ceiling metrics — document hard ceiling and surface truncation

> Feature branch: `feat/bin-111-quintoandar-pagination-beyond-ssr-ceiling-12` · Linear: `BIN-111` · Status: implemented

## Problem

Atomic QuintoAndar search windows that remain at the SSR page size (≥12 houses) after price bisect, neighborhood fan-out, and house-type fan-out still truncate: the scraper only reads `__NEXT_DATA__` and never paginates deeper. Operators had no run-level metric for how often coverage was capped.

## Approach

- Research: QuintoAndar has no public list pagination API. Third-party scrapers paginate by browser-intercepting an internal tokenized search API — the opposite of this scraper’s deliberate SSR/`__NEXT_DATA__` approach. **Decision:** keep SSR-only; do not ship a non-SSR client.
- Name the ceiling as `_SSR_PAGE_CEILING = 12` and count truncated windows / houses yielded from them.
- Emit `quintoandar_ssr_ceiling_summary` at end of `fetch_pages`, and fold nonzero counters into scrape-run Redis telemetry (`ssr_truncated_windows`, `ssr_truncated_houses_yielded` on `recent_scrape_runs`).

## Changes

Files touched:

```
 src/adapters/scrapers/quintoandar.py              | Named ceiling, truncation counters, summary log
 src/adapters/queue/tasks.py                       | Pass SSR truncation into _record_scrape_run
 src/tests/unit/test_quintoandar.py                | Truncation path + summary/counter asserts
 src/tests/unit/test_scrape_run_telemetry.py       | Telemetry payload + scrape_listings wiring
 docs/features/BIN-74-scraper-coverage-location-source-filter.md | Notes: follow-up → BIN-111
 docs/features/BIN-111-quintoandar-ssr-ceiling-metrics.md | NEW — this note
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
```

Manual:

1. Trigger a QuintoAndar scrape; look for `quintoandar_window_truncated` and a closing `quintoandar_ssr_ceiling_summary`.
2. `GET /system/pipeline` → `recent_scrape_runs` may include `ssr_truncated_windows` / `ssr_truncated_houses_yielded` when truncation occurred.

## Notes / Follow-ups

- Coverage behaviour unchanged: truncated windows still yield the ≤12 SSR cards. `validate-scrapers` gate not updated (no behaviour change).
- Deeper coverage would require a browser/tokenized internal API client (high anti-bot risk) or further funnel dimensions (extra types / denser neighborhoods) that shrink residual gaps without removing the ceiling.
- Related: BIN-74 / feature 53 (house-type fan-out), BIN-62 adaptive funneling.
