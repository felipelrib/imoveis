# API Reference

The FastAPI backend exposes a REST API. Interactive docs are available at `/docs` when the server is running.

## Health Check

```
GET /health
```

Returns `{"status": "ok"}` when the API is running and connected to the database.

## Properties

### List Properties

```
GET /properties
```

Query parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `neighbourhood` | string | Filter by neighbourhood name |
| `city` | string | Filter by city name |
| `listing_type` | string | `rent` or `sale` |
| `min_price` | number | Minimum price filter |
| `max_price` | number | Maximum price filter |
| `min_area` | number | Minimum area (m²) |
| `max_area` | number | Maximum area (m²) |
| `platform` | string | Source platform filter |
| `bbox` | string | Bounding box: `minLon,minLat,maxLon,maxLat` |
| `limit` | int | Results per page (default 50) |
| `offset` | int | Pagination offset |
| `sort_by` | string | `combined_score` (default), `price`, `total_monthly_cost`, `first_seen`, `created_at`, `area_m2`; anything else is a `422` |
| `sort_dir` | string | `asc` or `desc` (default) |
| `max_total_monthly_cost` | number ≥ 0 | Keep Properties that have an active rent Listing with `total_monthly_cost` at or under the cap |
| `include_incomplete_totals` | bool | Only with `max_total_monthly_cost`: also keep Properties that have an active rent Listing but none with a total. No effect alone |

`GET /properties/export` accepts the same `sort_by`, `max_total_monthly_cost` and
`include_incomplete_totals`.

#### Total Monthly Cost (FR-31)

Every Property returned by `GET /properties`, `/properties/by-ids`,
`/properties/export` and `/properties/{id}` goes through one serializer
(`core/property_projection.py`, AD-12) and carries the same cost fields. Every
figure is a stored `property_listings` column copied as is — nothing is
computed, imputed or re-derived at read time, and the legacy `price`,
`condo_fee`, `iptu` and `base_price` are never used as a fallback.

Per Property:

| Field | Meaning |
|-------|---------|
| `deciding_listing_id` | `id` of the one Listing in `listings` that decides the Property's monthly cost |
| `deciding_rule` | `lowest-complete-total`: the active rent Listing with the lowest total (ties: `platform`, then `id`, ascending). `lowest-headline-price`: no active rent Listing has a total, so `primary_listing` decides |
| `total_monthly_cost` | The deciding Listing's stored total under `lowest-complete-total`, otherwise `null` |

All three are `null` only when `primary_listing` is `null`. `price` and
`primary_listing` keep their meaning (lowest headline price), so
`deciding_listing_id` and `primary_listing.id` can differ.

Per Listing (`listings[]` and `primary_listing`): `id` (the Listing UUID) and a
nested `cost` object.

| `cost` field | Values |
|--------------|--------|
| `rent_monthly`, `rent_state` | number or `null`; `known`, `unknown`, `not-applicable` (sale Listing) |
| `condo_fee_monthly`, `condo_fee_state` | number or `null`; `known`, `bundled`, `unknown` |
| `iptu_monthly`, `iptu_state` | number or `null`; `known`, `bundled`, `unknown` |
| `iptu_periodicity_source` | `monthly`, `annual`, `unknown` |
| `fees_bundled` | `true` when the platform published one combined fee figure (held in `condo_fee_monthly`) |
| `total_monthly_cost`, `total_state` | number or `null`; `complete`, `bundled`, `incomplete`, `not-applicable` (sale Listing) |
| `cost_complete` | `true` exactly when the total is not `null` |

- **`null` is "not published", never zero.** An `unknown` component makes the
  total `incomplete` and `null`.
- **`cost.fees_bundled` is not the Listing's top-level `fees_bundled`.** The
  top-level key is the legacy `raw_json` flag and keeps its meaning.
- **`sort_by=total_monthly_cost`** orders by the lowest total among the
  Property's active rent Listings; Properties without one sort last in both
  directions. The sort and the cap read `total_monthly_cost` only and use the
  same rule as `deciding_listing_id`, so the order always matches the
  `total_monthly_cost` shown. `sort_by=price` and `max_price` are unchanged.
- **A sale-only Property never passes the cap**, with or without
  `include_incomplete_totals`: totals exist for rent Listings only.
- CSV export: `deciding_listing_id`, `deciding_rule` and `total_monthly_cost`
  are the last three columns; per-Listing `cost` is inside the `listings` JSON
  cell.

### Get Property

```
GET /properties/{id}
```

Returns full property details including listings, scores, and metadata, plus the
Total Monthly Cost fields described above.

### Price History

```
GET /properties/{id}/price-history
```

Returns ordered price history intervals with `start_ts`, `end_ts`, and `price`.

## Scraper Control

### Trigger Scrape

```
POST /scrape
```

Body:

```json
{
  "platform": "quintoandar",
  "search_url": "https://quintoandar.com.br/..."
}
```

### Get Platforms

```
GET /platforms
```

Returns list of available scraper platforms and their status.

## Admin Endpoints

### Worker Management

```
POST /admin/workers/pause    # Pause AI workers
POST /admin/workers/resume   # Resume AI workers
GET  /admin/workers/status   # Check worker status
```

### GPU Control

```
POST /admin/gpu/scale
```

Body:

```json
{
  "limit": 2
}
```

### AI Model Override

```
POST /admin/ai/model
```

Body:

```json
{
  "model": "llava",
  "backend": "ollama"
}
```

### Cloud Enrichment Backfill Control

All four require an admin `X-API-Key` (router-level gate); the three mutations
are rate-limited, and each is recorded in the `admin_audit` trail. Auditing is
best-effort for outcomes that are already decided (a refusal, an applied
pause/resume): a database blip loses the audit row and is logged, but never
turns an applied mutation into a `500`. A `start` is the exception — it queues a
multi-day cloud spend, so a start that cannot be audited is rolled back and
reported as a failure rather than fired unrecorded.

```
GET  /admin/backfill/status   # control state, lease holder, budget, checkpoint
POST /admin/backfill/start    # 202 — records a start *request*
POST /admin/backfill/pause    # pause level (also withdraws a queued start)
POST /admin/backfill/resume   # clears the pause and any pending stop
```

Three non-obvious semantics:

- **`start` returns 202, not 200** — it only records a request. The runner needs
  `GEMINI_API_KEY`, which lives in the operator's host shell, so a host-side
  supervisor (`PYTHONPATH=src python scripts/dev/backfill_gemma.py --serve`) must
  be running to turn the request into a run. With no supervisor the request is
  accepted but nothing consumes it, which the status body reports as
  `runner_present: false` (and the request expires in an hour).
- **`start` returns 409 while a run holds the lease**, naming the active run
  (owner, how long it has held the lease, when it was last seen) — there is only
  ever one runner.
- **A mutation's `status` may be `null`, and that is still a success.** The
  `pause`/`resume` body is `{action, cleared_start, cleared_stop, status}`, where
  `status` is a full status snapshot taken *after* the mutation was applied. It
  is best-effort: a Redis blip on that read nulls it and the mutation still
  happened, so a client must render `status: null` as "applied — poll
  `/status`", never as an error. `cleared_start` (pause withdrew a queued start
  that no run could have honored) and `cleared_stop` (resume also dropped a
  pending stop) report what else the call did. The `start` body is
  `{requested, already_requested, requested_at, runner_present,
  discarded_requests}`: `already_requested: true` means a request was already
  pending and `requested_at` is the *original* stamp, and `discarded_requests`
  lists the stale pause/stop levels the queued run will start without.

`status` reports `active` (someone holds the lease) as the liveness signal;
`state` is what the runner last published and can read `idle` under a live run,
and `heartbeat_active` means "rows are being enriched right now" (a paused run
stops beating it on purpose). `quarantined` is always null here — counting it
scans every property ever attempted; the CLI's `--status` reports it instead.

`budget.consumed` and `seconds_until_reset` come from the live window in Redis;
`budget.limit` and the whole `pacing` block are the **configured** values
(`AppConfig.backfill`). A run started by hand can override them on the command
line, so `--serve` refuses `--daily-budget`, `--concurrency`, `--tpm-limit` and
`--min-interval` — the supervisor cannot report an override, so a run the API
asked for always paces to the figures shown here.

### Enrichment Coverage

```
GET /admin/enrichment/coverage   # per-signal AI coverage + the live run's ETA
```

Admin `X-API-Key` (same router gate), rate-limited to `30/minute`. How much of
the corpus carries each AI signal, measured **from the database** — never from
the backfill runner's Redis checkpoints (FR-29), so the figures are correct with
no runner present and identical across repeated calls over an unchanged corpus.
The lease contributes exactly two things: `backfill.active`, and the window bound
the throughput is measured over.

```json
{
  "signals": [{"task_class": "visual", "enriched": 1234, "total": 2000, "fraction": 0.617}],
  "minimum_fraction": 0.6,
  "total_properties": 2000,
  "backfill": {"active": true, "remaining": 640, "throughput_per_day": 4600.0,
               "eta_days": 3.2, "projected_completion_date": "2026-08-14"},
  "cost_completeness": [{"platform": "olx", "total": 4, "complete": 2, "bundled": 1,
                         "incomplete": 1, "complete_fraction": 0.5,
                         "bundled_fraction": 0.25, "incomplete_fraction": 0.25}]
}
```

- **`cost_completeness` is Total Monthly Cost completeness per Platform**
  (NFR-6 / SM-3), counted over active rent Listings of active Properties. The
  three counts are mutually exclusive and always sum to `total`: `complete` (a
  total, itemized), `bundled` (a total built on a combined published fee figure)
  and `incomplete` (no total). Rows are ordered by `platform`; a Platform with no
  active rent Listing has no row, so the list is `[]` on an empty corpus. The
  fractions are null when `total` is 0.

- **`null` means "not measurable", never "zero".** `fraction` is null when the
  denominator is zero (an empty or fully delisted corpus has *undefined*
  coverage), and `throughput_per_day` / `eta_days` /
  `projected_completion_date` are all null unless a run holds the lease **and**
  the snapshot history supports a rate: at least two `pipeline_metric_snapshots`
  points spanning ≥15 minutes inside the window, with a positive delta. Render
  absence, not `0%` — a client that substitutes zero reports a failed enrichment
  on a healthy database.
- **One entry per `EnrichmentTaskClass`**, always, in declaration order, English
  on the wire (`visual`, `sentiment`, `deal_verdict`, `valuation`, `embedding`).
  The list grows when the enum does; it is deliberately not fixed-length.
- **The denominator is `active` properties.** Delisted rows are never enriched,
  so counting them would depress coverage permanently.
- **`eta_days` is an order-of-magnitude figure, not a delivery date.** Its
  numerator (active, photo-gated rows with no `ai_score`) and its denominator
  (the corpus-wide enrichment rate, which also moves for live-pipeline work) are
  measured over different populations, and `remaining` does not subtract
  quarantined rows. `src/adapters/db/enrichment_coverage_queries.py` states both
  limits in full.

### Schedule Management

```
GET  /admin/schedule    # Get current scrape schedule
POST /admin/schedule    # Update scrape interval
```

## System

```
GET /system/pipeline     # Pipeline status and telemetry
GET /system/health       # Detailed health check
