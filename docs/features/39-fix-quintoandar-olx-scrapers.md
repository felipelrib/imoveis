# Fix QuintoAndar / OLX scrapers — restore ingest after config + HTML drift

> Feature branch: `fix/quintoandar-olx-scrapers` · Linear: n/a (ops incident) · Status: implemented

## Problem

QuintoAndar scrape runs finished with `0 processed / N errors` (e.g. 1265 err) even though search pages returned listings. OLX runs completed with zero listings because listing pages no longer embed `__NEXT_DATA__`.

Root causes:

1. `configs/app_config.yaml` still had a `dedup:` block, but `AppConfig` dropped `DedupConfig`, so every persist path crashed on `cfg.dedup.*`.
2. OLX migrated listing HTML to Next.js Flight (`self.__next_f.push`) with an embedded `"ads":[...]` array instead of `__NEXT_DATA__`.
3. QuintoAndar search JSON renamed `parkingSpaces` → `parkingSpots`.

## Approach

- Restore `DedupConfig` on `AppConfig` so scrape tasks can read YAML thresholds again.
- Keep `__NEXT_DATA__` parsing for OLX, and fall back to extracting `"ads"` from Flight RSC chunks.
- Widen OLX normalize helpers for Flight field names (`listId`, `priceValue`, `locationDetails`, property `name` keys).
- Accept both QuintoAndar parking field names.

## Changes

Files touched:

```
 src/infra/config.py                    | Restore DedupConfig + AppConfig.dedup
 src/adapters/scrapers/quintoandar.py   | Read parkingSpots (fallback parkingSpaces)
 src/adapters/scrapers/olx.py           | Flight ads parse + normalize field updates
 src/tests/unit/test_config.py          | Dedup load/default/override tests
 src/tests/unit/test_quintoandar.py     | parkingSpots normalize test
 src/tests/unit/test_olx.py             | Flight extraction + normalize tests
 docs/features/39-fix-quintoandar-olx-scrapers.md | NEW — this note
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh backend
bash scripts/agent/validate-scrapers.sh --require-live
```

Manual:

1. `POST /scrape` for `quintoandar` and watch Redis `pipeline:scraper:quintoandar:status` — `processed` should climb, `errors` near zero.
2. Same for `olx` when Cloudflare allows the worker IP (403s remain environmental).

## Notes / Follow-ups

- **BUG (Medium)**: OLX intermittently returns Cloudflare 403 from datacenter IPs; enable `proxy:` pool when available (BIN-47/48 path) rather than treating as a parse bug.
- QuintoAndar search cards often omit `location` lat/lon now — geo fuzzy dedupe skips those rows until a detail fetch is added.
- OLX region URL filters sometimes surface national ads in HTML; revisit path/slug config if BH purity matters.
