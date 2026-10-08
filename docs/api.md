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
| `accepts_pets` | bool | `true`: keep Properties known to accept pets (an active Listing with `accepts_pets` true, or the QuintoAndar pets amenity). `false`: the complement, "not known to accept pets": a Listing that says no and one that says nothing are both kept, so `true` and `false` together are every Property. Absent: no filter |
| `max_price_per_m2_percentile` | number, > 0 and ≤ 1 | Keep Properties whose stored cohort price/m² percentile is at or under the value (`0.25` = among the 25% cheapest of the neighbourhood). Outside the range or not a number: `422` |

`GET /properties/export` accepts the same `sort_by`, `max_total_monthly_cost`,
`include_incomplete_totals` and `max_price_per_m2_percentile`.

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
  are appended after the original columns (followed by the two percentile
  columns below); per-Listing `cost` is inside the `listings` JSON cell.

#### Cohort price/m² percentile (FR-30)

The same serializer adds two fields to every Property on the list, batch,
export and detail endpoints:

| Field | Meaning |
|-------|---------|
| `price_per_m2_percentile_rent` | Share of the Property's city × neighbourhood rent cohort priced at or below it, in (0, 1]; lower is cheaper. `0.25` reads "among the 25% cheapest". `null` when there is no value |
| `price_per_m2_percentile_sale` | The same for the sale cohort |

- **Stored, not computed.** The values are `metrics_scoring` columns written by
  the scoring stage (see `docs/features/v0.14-s1.6-cohort-price-per-m2-percentiles.md`)
  and are served unrounded, so "the value is ≤ 0.25" and "passes
  `max_price_per_m2_percentile=0.25`" are the same test.
- **`null` is "no percentile", never a default.** The cohort is below the
  minimum size, the Property is not a cohort member (no area, no neighbourhood,
  no Listing price) or it has no scoring row. A `null` never matches the filter.
- **The filter follows `listing_type`.** `rent` compares the rent field, `sale`
  the sale field; `both` or no `listing_type` keeps a Property when either field
  qualifies. A field only counts while the Property has an active Listing of
  that type (the stored value outlives a deactivated Listing until the next
  scoring run).
- **Not `percentile_rank*`.** The legacy `percentile_rank`, `percentile_rank_rent`
  and `percentile_rank_sale` are still served with their old definition (SQL
  `PERCENT_RANK`, rounded to three places, cheapest = 0). Use the fields above
  for "how cheap in its neighbourhood".
- CSV export: `price_per_m2_percentile_rent` and `price_per_m2_percentile_sale`
  are the last two columns; an empty cell is `null`.
- Saved searches store the filter as `max_price_per_m2_percentile` in `filters`
  (same range; out of range is a `422` on save).

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

## Saved Searches

All routes need the API key (`X-API-Key`) and only see the searches of the
authenticated principal.

```
GET    /saved-searches?page=1&page_size=50
GET    /saved-searches/{id}
POST   /saved-searches
PATCH  /saved-searches/{id}
DELETE /saved-searches/{id}
```

Every item carries:

| Field | Type | Description |
|-------|------|-------------|
| `id`, `name`, `created_at` | string | |
| `filters` | object | Snake_case English filter wire (`listing_type`, `max_price`, `price_type`, `min_bedrooms`, `min_parking`, `min_score`, `neighborhood`, `city`, `property_type`, `platform`, `is_furnished`, `accepts_pets`, `max_price_per_m2_percentile`, `sort_by`, `sort_dir`, `q`). camelCase keys are accepted on write |
| `notify_new_matches` | bool | New-match alerts for this search (FR-32). Default `false` |
| `min_price_drop` | number ≥ 0 or `null` | Minimum price drop of this search, in reais (absolute). Returned as stored; no rule reads it yet |
| `notify_enabled_at` | string or `null` | Naive UTC timestamp of the last time `notify_new_matches` was turned on. Read-only. Only Properties first seen at or after it can be a new match |
| `new_match_alerts_supported` | bool | `false` when `filters.q` is non-blank (a semantic search is a ranking), the stored filters carry a key outside the list above, or the stored value is not an object: such a search never produces a new-match alert, whatever `notify_new_matches` says. Read-only |
| `last_new_match_alert_on` | string (`YYYY-MM-DD`) or `null` | Local date of the last new-match email of this search. Read-only |

Writing:

- `POST` body: `name`, `filters`, optional `notify_new_matches` (default
  `false`) and `min_price_drop`.
- `PATCH` body: any of `name`, `filters`, `notify_new_matches`,
  `min_price_drop`. `"min_price_drop": null` sent explicitly clears the value;
  an absent key leaves it.
- Turning `notify_new_matches` on (`false` to `true`, or creating with `true`)
  stamps `notify_enabled_at`. Turning it off keeps the stamp; turning it on
  again replaces it. `true` on a search that is already on changes nothing.
- A negative or non-finite `min_price_drop` is a `422`.

New-match alerts (see `docs/features/v0.14-s1.9-saved-search-new-match-detection.md`):

- A Property is a new match of a search when it was first seen after the
  search was turned on, passes `GET /properties` with the parameters the
  search stands for, and has a stored verdict and an evaluated percentile.
  Until it has both it is held, with no time limit, and alerted when it does.
- Each search gets at most one email per local day, by email only, listing the
  matches recorded since the last one. Each search x Property pair is alerted
  at most once.
- There is no endpoint that lists the recorded matches in this version.

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
