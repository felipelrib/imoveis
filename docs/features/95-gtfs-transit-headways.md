# GTFS transit headways — schedule frequency in quality_meta

> Feature branch: `feat/bin-119-gtfs-transit-headways` · Linear: `BIN-119` · Status: implemented

## Problem

Transit proximity (BIN-89) scored neighbourhoods by stop distance and density
only. GTFS often also publishes service frequency (`frequencies.txt`) or
enough `stop_times` departures to estimate headways — useful signal that was
deferred as a stretch and blocked until stops were durable (BIN-118).

## Approach

- At file-based refresh, parse per-stop headways: prefer `frequencies.txt`
  `headway_secs` joined via `stop_times`; else median inter-arrival from
  `stop_times` departure clocks (min 3 diffs in a 2–120 min band).
- Aggregate stops inside `count_radius_m` into nested
  `quality_meta.transit.headway` with method, median minutes, sample size,
  static window label, and an explicit schedule-not-live disclaimer.
- Do **not** change `transit_score` or add columns on `transit_stops` —
  beat already re-reads GTFS dirs; `--from-db` / OSM-only leave headway
  `unavailable`.

## Changes

Files touched:

```
 src/core/gtfs_headways.py                         | NEW — parse + aggregate headways
 src/core/transit_proximity.py                     | score_centroid nests headway meta
 src/adapters/geo/transit_refresh.py               | parse GTFS headways into scoring
 scripts/dev/refresh_transit_proximity.py          | document frequencies.txt / headway
 src/tests/fixtures/transit/gtfs_tiny/frequencies.txt | NEW — 600s metro headway
 src/tests/unit/test_gtfs_headways.py              | NEW — frequencies / stop_times / aggregate
 src/tests/unit/test_transit_proximity.py          | headway on score meta
 src/tests/unit/test_transit_refresh.py            | pass stop_headways into scoring
 src/tests/integration/test_transit_proximity.py   | API meta includes headway
 src/tests/integration/test_transit_stops.py       | from-db → unavailable headway
 docs/features/67-transit-proximity.md             | Notes → shipped link
 docs/features/92-persist-transit-stops.md         | Notes → headways shipped
 docs/features/95-gtfs-transit-headways.md         | NEW — this doc
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh backend
# or focused:
PYTHONPATH=src pytest src/tests/unit/test_gtfs_headways.py \
  src/tests/unit/test_transit_proximity.py -q
```

Manual:

```bash
PYTHONPATH=src python scripts/dev/refresh_transit_proximity.py \
  --gtfs-dir path/to/gtfs --dry-run
# Inspect quality_meta.transit.headway after a non-dry-run refresh.
```

## Notes / Follow-ups

- Headways are schedule estimates only — UI/blend must surface the disclaimer
  (same discipline as safety attribution / listing claim stats).
- Persisting per-stop headway on `transit_stops` (so `--from-db` retains
  frequency) is intentionally out of scope.
- Calendar / peak-window filtering and live GTFS-RT are not implemented.
- Related: BIN-89 / feature 67, BIN-118 / feature 92, parent BIN-104.
