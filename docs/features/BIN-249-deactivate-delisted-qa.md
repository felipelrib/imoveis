# Delisted QuintoAndar sweep — deactivate empty-description placeholder rows

> Feature branch: `feat/bin-249-deactivate-delisted-qa` · Linear: `BIN-249` · Status: implemented

## Problem

After the [BIN-245](https://linear.app/felipelrib/issue/BIN-245) description backfill,
~900+ active QuintoAndar rows still had an empty `description`. Live probing showed most
are **not** text-less live listings — they are **delisted** listings whose
`/imovel/{id}` detail page now serves a generic SPA **placeholder shell** with an empty
`houseInfo` (blank `id`/`displayId`/`status`, empty `listings`, no `rentPrice` /
`DescriptionsSection`) and never 301-redirects to a slug URL.

The `availability_recheck` job (BIN-80) never retired them because the availability
detector classified this empty-`houseInfo` shell as **UNKNOWN** (`qa_status_unclear`),
and UNKNOWN never soft-deactivates (correct for Cloudflare/proxy failures, wrong here).
So the dashboard carried delisted inventory as active.

## Approach

- **Add the placeholder signal to the availability detector** (the durable fix, so this
  self-heals): `parse_quintoandar_availability` now detects the empty-`houseInfo`
  placeholder shell → `UNAVAILABLE` / reason `qa_placeholder_shell`. The empty payload
  (no `id`/`displayId`/`status`/`listings`) is the self-contained signal; a slug in the
  final URL vetoes it as a safety guard (a slug redirect means the page resolved to a
  live listing). `request_url`/`final_url` are threaded through `classify_response` so the
  recheck job's followed-redirect URL corroborates the payload signal.
- **One-off backlog sweep** (`scripts/dev/deactivate_delisted_qa.py`): the recheck job's
  throughput (`batch_size=50` every 6h ≈ 200/day) can't drain a ~1200-row backlog before
  the daily scrape re-activates listings, so a manual sweep clears the existing rows now.
  It probes each active empty-description QA listing and buckets it:
  - **delisted** — probe returns `UNAVAILABLE` (`qa_placeholder_shell`,
    `qa_listing_unpublished`, `qa_house_despublicado`, 404/410, …) → soft-deactivated.
  - **duplicate** — `/imovel/{id}` redirects to a *different* live listing id → stale row
    deactivated; canonical id reported if already present in the DB.
  - **no_text** — probe returns `AVAILABLE` for the same id (genuinely text-less live
    listing) → left untouched ([BIN-243](https://linear.app/felipelrib/issue/BIN-243)
    neutral no-signal sentiment already covers these).
  - **unknown** — transient (Cloudflare 403 / timeout / 5xx) → left active for retry.
  Deactivation goes through the shared `deactivate_listing_and_maybe_property` path, so a
  property flips inactive only when it has no remaining active listing (invariant kept).

## Why `availability_recheck` wasn't already catching these

Cross-check (live probe, 2026-07-31, primary `realestate` DB):

- **Staleness — fine.** All 1218 matching listing rows had `last_seen` ≥ 24h old
  (2026-07-24…27), so every one was eligible for the recheck query's `last_seen < cutoff`.
- **Routing — fine.** `tasks.recheck_listing_availability` is routed to the `scrapers`
  queue (workers consume it); the beat entry is present when `availability_recheck.enabled`.
- **Real gaps — two:**
  1. The empty-`houseInfo` placeholder shell was classified UNKNOWN, never deactivated
     (this PR fixes the signal → it now self-heals).
  2. Throughput: `batch_size=50` / 6h can't keep pace with the delisted backlog. See
     follow-up below.

## Changes

Files touched:

```
 src/adapters/scrapers/availability.py             | Detect empty-houseInfo QA placeholder shell -> UNAVAILABLE; thread request_url/final_url through the QA parser + classify_response
 scripts/dev/deactivate_delisted_qa.py             | NEW — one-off sweep to classify & soft-deactivate the empty-description QA backlog
 src/tests/fixtures/scrapers/quintoandar_delisted_placeholder.html | NEW — oracle fixture: trimmed real placeholder shell (empty houseInfo)
 src/tests/unit/test_availability.py               | Placeholder-shell detection cases (with/without URLs, slug-redirect veto, live-still-available)
 src/tests/unit/test_deactivate_delisted_qa.py     | NEW — sweep classification buckets + dry-run/apply guards
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh backend
```

Sweep (dry-run is default; `--apply` writes):

```bash
PYTHONPATH=src python scripts/dev/deactivate_delisted_qa.py            # dry-run, all rows
PYTHONPATH=src python scripts/dev/deactivate_delisted_qa.py --apply --limit 100
```

## Results (primary `realestate` DB, 2026-07-31)

Candidates probed: **1218** active empty-description QA listing rows (959 distinct
properties). Direct httpx probing — no proxy/Cloudflare needed.

```
candidates            : 1218
delisted (deactivated): 1038   # UNAVAILABLE — placeholder shell / unpublished / 404
no_text  (left active):  177   # AVAILABLE live listing, genuinely no seller text
duplicate             :    0   # none redirected to a different canonical id
unknown  (left active):    3   # transient (left active for retry)
properties_deactivated:  797   # flipped inactive after their last active listing went
```

Post-sweep the DB carries **180** active empty-description QA listing rows
(177 no_text + 3 unknown) — down from 1218. 827 QA properties are now inactive.

## Notes / Follow-ups

- **FOLLOW-UP (throughput):** `availability_recheck.batch_size=50` every
  `interval_minutes=360` (~200 rows/day) is too slow to retire delisted backlog faster
  than the daily scrape re-activates listings. Consider raising `batch_size` (or lowering
  the interval) so recheck keeps pace without a manual sweep. Left as config tuning
  out of this ticket's scope.
- `no_text` (live, description-less) rows are intentionally left active —
  [BIN-243](https://linear.app/felipelrib/issue/BIN-243) neutral sentiment handles them.
- Related: [BIN-245](https://linear.app/felipelrib/issue/BIN-245) (QA description
  extraction), [BIN-243](https://linear.app/felipelrib/issue/BIN-243) (empty descriptions).
