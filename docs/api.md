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

### Get Property

```
GET /properties/{id}
```

Returns full property details including listings, scores, and metadata.

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

### Schedule Management

```
GET  /admin/schedule    # Get current scrape schedule
POST /admin/schedule    # Update scrape interval
```

## System

```
GET /system/pipeline     # Pipeline status and telemetry
GET /system/health       # Detailed health check
