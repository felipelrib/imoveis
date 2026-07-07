# Feature Queue

Add features here, one row per feature. Agents (or you) work them top-down.
`slug` is kebab-case and becomes the branch `feat/<slug>` and worktree `.worktrees/<slug>`.

Status: `pending` → `planned` → `in-progress` → `done`.

> **How to read this file.** The table below is the ordered work queue — the
> `Description` column is the one-line capability + subsystem hint. Each row also
> has a full spec under **[Feature Specifications](#feature-specifications)** giving
> the planner Goal / Why / Affected areas / Approach / Data & API / Frontend /
> Acceptance criteria / Conflict surface. Planners should read the matching spec,
> not just the table row.
>
> **Prioritisation (principal-PM view).** Order is deliberate. **Tier 0 (Foundation)**
> fixes silent breakage and unblocks everything else — do these first and mostly
> serially (they share `src/infra/config.py`, `alembic/`, `src/core/dedupe.py`,
> `src/adapters/db/models.py`). **Tier 1** delivers the core product value (this is
> a *deal-finding* tool — track prices over time, get alerted, cover more
> platforms). **Tier 2** deepens the AI moat. **Tier 3** is design/UX polish that
> is mostly frontend-isolated and can run in parallel with backend work. **Tier 4**
> is robustness/efficiency, opportunistic. Respect the **Depends on** field.
>
> **Cline dispatch.** To work a feature in Cline/Cursor, say:
> - `"Plan feature <slug> from FEATURES.md"` — triggers the planner rule
> - `"Implement feature <slug> from FEATURES.md"` — triggers the coder rule
> - `"Review feature <slug> before merge"` — triggers the reviewer rule
> - `"Run feature <slug> from FEATURES.md"` — triggers the full pipeline skill
> See `.cursor/rules/feature-workflow.mdc` for the full orchestration logic.

| Status  | Slug                          | Title                                            | Depends on               | Description |
|---------|-------------------------------|--------------------------------------------------|--------------------------|-------------|
| done    | `config-yaml-loader`          | Wire `app_config.yaml` into runtime config       | —                        | `src/infra/config.py` never reads the YAML — it returns hardcoded defaults, so every tunable (rate limits, dedup thresholds, AI model/backend, proxy) is inert and `test_config.py` fails. Load and validate `configs/app_config.yaml`, unify the dataclass shape with its consumers, add env overrides. Backend + config; no DB. |
| done | `property-listings-table`     | Add & populate the `property_listings` table     | —                        | The properties API (`src/api/properties.py:125,234`) queries `property_listings`, but no migration creates it and no code writes it — a live break. Add the ORM model + Alembic migration, and persist per-platform rent/sale listing rows during dedupe/ingest. Backend + DB migration. |
| done | `price-history-tracking`      | Record & expose price history                    | `property-listings-table`| The `price_history` table exists but nothing ever writes it. Insert a row (close previous interval) whenever a listing's price changes during dedupe, and add `GET /properties/{id}/price-history`. Foundation for alerts & charts. Backend + DB. |
| pending | `scheduled-scraping`          | Recurring scrapes via Celery beat                | `config-yaml-loader`     | Scraping is manual-only (`POST /scrape`). Add a Celery beat schedule that re-scrapes each enabled platform on a config-driven cadence, with a `POST /admin/schedule` to adjust it and a last-run/next-run readout. Backend + Celery + config. |
| pending | `price-drop-alerts`           | Watchlist price-drop alerts                       | `price-history-tracking` | Let a user watch properties/searches and get notified when a watched listing drops in price. Redis pub/sub off the `price-history-tracking` write path, a pluggable notifier (log + webhook/Telegram), and watchlist API. Backend + Redis + frontend toggle. |
| pending | `olx-scraper`                 | Second platform scraper (OLX)                     | `property-listings-table`| Only QuintoAndar is implemented; multi-platform + cross-platform dedup is the product premise. Implement an `OlxScraper(BaseScraper)` self-registered as `olx`, normalise to `PropertyCandidate`, and verify cross-platform dedup merges duplicates. Backend (scrapers). |
| pending | `saved-searches-watchlist`    | Saved searches & favourites                       | —                        | Users re-run the same filter sets and want to bookmark properties. Persist named saved searches and per-property favourites; expose CRUD API and surface them in the frontend (sidebar + a star on cards). Backend + DB + frontend. |
| pending | `configurable-ai-models`      | Configurable AI models & backend                  | `config-yaml-loader`     | Visual (`llava`) and text (`llama3`) models are hardcoded, ignoring `ai.default_model`/`ai.backend`; `LMStudioClient` can't enrich. Plumb model/backend/timeout/max-tokens from config per analysis, and complete the LM Studio client. Backend (AI). |
| pending | `deal-summary-enrichment`     | Natural-language "why it's a deal" summary        | —                        | Combine the statistical z-score, visual condition, and description sentiment into one short PT-BR verdict ("Undervalued vs Savassi avg, good condition, no red flags") stored on the property and shown on card + modal. Backend (AI/scoring) + frontend. |
| pending | `map-view`                    | Interactive map of properties                     | —                        | Lat/lon + PostGIS are already stored but never visualised. Add a map view (MapLibre/Leaflet) plotting properties as score-coloured markers with popup cards and a viewport-bounds filter on the properties API. Frontend + small API addition. |
| pending | `dashboard-charts`            | Charts for pipeline & market insight              | `price-history-tracking` | `recharts` is installed but unused. Add charts: enrichment-rate & queue-throughput over time (Dashboard) and score/price-per-m² distribution + a per-property price-history line (modal). Frontend + small metrics endpoints. |
| pending | `frontend-ux-hardening`       | Toasts, error states & dynamic filters            | —                        | Replace `alert()` with a toast system, add error/empty/retry states to the Properties grid, and fetch the neighbourhood/city filter options from the backend instead of the 30 hardcoded BH names. Frontend + one lookup endpoint. |
| pending | `pipeline-resilience`         | Wire circuit breakers & skip unchanged AI         | —                        | The circuit breakers are implemented but never used, and dedupe never returns `noop` so every scrape re-enqueues GPU AI work. Wire the Redis circuit breaker into scraping and skip `ai_enrich` when a listing is unchanged. Backend (scrapers/dedupe/queue). |

<!-- Template row (do not work — copy its shape for new features):
| pending | `_example-listing-alerts_` | _Listing price-drop alerts_ | _Notify when a tracked listing drops in price. Backend + Redis pub/sub._ |
-->

## How a feature moves through the pipeline
1. Add a row above with status `pending` (and a spec below if non-trivial).
2. Plan + implement it (pick one):
   - **In Cline/Cursor (recommended):** Say
     `"Run feature <slug> from FEATURES.md"` to trigger the full pipeline skill,
     or say `"Plan feature <slug> from FEATURES.md"` then
     `"Implement feature <slug> from FEATURES.md"` separately.
   - **In Goose:** `goose run --recipe recipes/feature-pipeline.yaml --params feature_slug=<slug> feature_title="<Title>" feature_description="<what it does>"`
   - **Two phases (batch of features):** plan all pending first, then implement
     each — keeps one model resident on the 20 GB VRAM box.
   - **Conversationally:** `@orchestrator work the FEATURES.md queue`.
3. Update this row's status as it progresses. When merged + documented → `done`.

---

# Feature Specifications

Each spec is written so a planner can produce `implementation_plan.md` unaided.
File/line references reflect the current tree. All DB changes go through a **new
Alembic revision** (baseline is `b64c262168da_initial`); never edit an existing
revision. Follow `.cursor/rules/guardrails.mdc` (worktree, ports, plan-before-code,
validate).

## Tier 0 — Foundation (do first, largely serial)

### `config-yaml-loader` — Wire `app_config.yaml` into runtime config
- **Goal.** Make `configs/app_config.yaml` the single source of truth actually
  loaded at runtime, with env-var overrides, and make the config dataclasses match
  what the code already reads.
- **Why.** `src/infra/config.py::load_config()` ignores its `path` arg and returns
  hardcoded defaults; `_find_config_file()` looks for `config.yaml` (wrong name)
  and is never called. Consumers/tests reference `cfg.dedup.radius_m`,
  `cfg.ai.model`, `cfg.ai.backend`, `cfg.ai.default_model`, but the dataclass
  defines `cfg.dedupe` / `cfg.ai.model_name`. Net effect: every YAML knob (rate
  limits, jitter, dedup thresholds, AI model/backend/timeout, proxy, per-platform
  base_url) is dead, and `src/tests/unit/test_config.py` fails today.
- **Affected areas.** `src/infra/config.py` (rewrite loader + dataclasses),
  `configs/app_config.yaml` (align keys), `src/tests/unit/test_config.py`, plus
  read-sites: `src/core/dedupe.py` (thresholds), `src/adapters/ai/client.py`
  (`create_ai_client`, model names), `src/adapters/scrapers/quintoandar.py`
  (throttle), `src/api/main.py::/platforms`.
- **Approach.** (1) Add `PyYAML` load with `${ENV}`/documented env overrides
  (`DATABASE_URL`, `REDIS_URL`, `AI_MODEL`). (2) Define one dataclass tree whose
  attribute names match every current read-site (audit with a grep for `cfg.`);
  prefer `cfg.dedup`, `cfg.ai.default_model`/`cfg.ai.backend`, `cfg.scoring`,
  `cfg.platforms[name]`. (3) Cache via `get_config()`. (4) Fix the no-op
  `ScoringWeights.weights_must_sum_to_one` validator in `src/core/entities.py`.
- **Acceptance.** `pytest src/tests/unit/test_config.py` passes; changing a value in
  the YAML (e.g. `dedup.radius_m`) changes runtime behaviour; `validate.sh backend`
  green. Add tests asserting env override precedence.
- **Conflict surface.** Touches shared config read by nearly every other feature —
  **land this before** `configurable-ai-models` and any threshold-tuning work.

### `property-listings-table` — Add & populate the `property_listings` table
- **Goal.** Create the missing `property_listings` table and write one row per
  platform listing (rent/sale) attached to a deduped property.
- **Why.** `src/api/properties.py:125` and `:234` aggregate from `property_listings`
  (per-listing price, URL, listing_type, furnished/pets, platform), but the initial
  migration (`alembic/versions/b64c262168da_initial.py`) creates no such table and
  there is no ORM model or writer. The properties grid/modal therefore rely on a
  table that does not exist in a clean DB → the read path is broken. The scraper
  already produces a `listings` array on `PropertyCandidate` that is currently
  discarded.
- **Affected areas.** `src/adapters/db/models.py` (new `PropertyListing` model:
  property_id FK CASCADE, platform, platform_listing_id, listing_type rent/sale,
  price, currency, url, is_furnished, accepts_pets, condo_fee, iptu, raw JSON,
  first_seen, last_seen, active); new Alembic revision; `src/core/dedupe.py`
  (upsert listings on create/update, key on `(platform, platform_listing_id)`);
  `src/adapters/scrapers/quintoandar.py::normalize` (ensure listing fields
  populated); verify `src/api/properties.py` SQL matches the new columns.
- **Acceptance.** Fresh `alembic upgrade head` creates the table; running a scrape
  populates listings; `GET /properties` and `/properties/{id}` return listing rows
  with correct URLs and prices; integration test covers a two-listing property.
- **Conflict surface.** Shares `dedupe.py`, `models.py`, `alembic/` with
  `price-history-tracking` and `pipeline-resilience` — sequence these three or
  coordinate the migration order.

### `price-history-tracking` — Record & expose price history
- **Goal.** Populate the existing `price_history` table on every price change and
  expose it via API.
- **Why.** The `price_history` model/table exists (migration line 104) but nothing
  writes it, so price-over-time — the core value of a deal tracker — is impossible.
  Blocks `price-drop-alerts` and the modal price chart.
- **Affected areas.** `src/core/dedupe.py` (in the "updated" branches at ~`:74-124`,
  when incoming price ≠ stored price, close the open interval `end_ts=now` and
  insert a new `price_history` row `start_ts=now`); `src/api/properties.py` (new
  `GET /properties/{id}/price-history` returning ordered intervals; optionally add
  `price_change_30d` to the list payload); reuse the `price_history` model.
- **Approach.** Do the history write inside the same DB transaction as the property
  update. Handle first-seen (seed one open interval). Decide currency/listing_type
  granularity — recommend per `property_listings` row once that table exists
  (**depends on `property-listings-table`**); if landed first, key on property.
- **Acceptance.** Scraping the same listing twice with a changed price yields two
  history rows with correct `start_ts`/`end_ts`; endpoint returns them; unit test
  on the change-detection logic.
- **Conflict surface.** `dedupe.py`, `alembic/`. **Depends on** `property-listings-table`.

## Tier 1 — Core product value

### `scheduled-scraping` — Recurring scrapes via Celery beat
- **Goal.** Automatically re-scrape enabled platforms on a schedule instead of only
  on manual `POST /scrape`.
- **Why.** There is no `beat_schedule` anywhere; fresh data (and thus price history
  and alerts) only exists when a human clicks. A deal tracker must run itself.
- **Affected areas.** `src/adapters/queue/celery_app.py` (add `beat_schedule` /
  `celery beat`), `configs/app_config.yaml` (per-platform `scrape_interval` /
  cron), `src/api/admin.py` (`GET/POST /admin/schedule` to read/adjust cadence,
  persisted in Redis like the other admin toggles), `docker-compose.yml` (a `beat`
  service), `frontend/src/pages/ScraperControl.jsx` + `src/api.js` (show
  last-run/next-run, edit interval).
- **Acceptance.** With beat running, an enabled platform is scraped on its interval
  without manual trigger; changing the interval via the API takes effect; disabled
  platforms are skipped; Live Pipeline panel shows the scheduled runs.
- **Conflict surface.** `celery_app.py`, config, ScraperControl page. **Depends on**
  `config-yaml-loader` (reads per-platform cadence).

### `price-drop-alerts` — Watchlist price-drop alerts
- **Goal.** Notify the user when a watched property (or any property matching a
  saved search) drops in price beyond a threshold.
- **Why.** The canonical example feature and the payoff of price history — turn
  passive data into actionable signals.
- **Affected areas.** New `watchlist` table + model + migration; `src/core/dedupe.py`
  or a post-write hook publishes a `price-drop` event to Redis pub/sub when a
  `price_history` close shows a decrease past `min_drop_pct`; a small notifier
  module `src/adapters/notify/` with a pluggable interface (log + webhook/Telegram,
  channel & token from config); API `POST/DELETE /watchlist`, `GET /watchlist`;
  frontend ★/🔔 toggle on `PropertyCard`/`PropertyModal` and an Alerts list.
- **Approach.** Consumer can be a Celery task subscribed to the channel, or emit the
  notification inline on the write. Keep the notifier interface small so email/other
  channels drop in later. De-dupe repeated alerts (store `last_notified_price`).
- **Acceptance.** Watching a property then ingesting a lower price fires exactly one
  notification via the configured channel; unwatching stops it; threshold respected.
- **Conflict surface.** `dedupe.py`, `alembic/`, frontend cards. **Depends on**
  `price-history-tracking`; pairs with `saved-searches-watchlist` (share the
  watchlist/notify UI — coordinate or land watchlist storage here first).

### `olx-scraper` — Second platform scraper (OLX)
- **Goal.** Add a real second platform to prove multi-platform ingest + cross-platform
  dedup.
- **Why.** OLX is in config (`enabled:false`) but no scraper class exists. The whole
  premise (unified view, dedup across platforms) is untested with one source.
- **Affected areas.** New `src/adapters/scrapers/olx.py` subclassing `BaseScraper`,
  self-registered via `@register("olx")` (mirror `quintoandar.py`); `normalize()`
  → `PropertyCandidate` with lat/lon, images, listing fields; enable in
  `configs/app_config.yaml`; add fixtures + a unit test; verify
  `src/core/dedupe.py` merges an OLX + QuintoAndar duplicate (spatial + title +
  area).
- **Approach.** Reverse-engineer OLX's listing JSON/XHR (see `PLAN.md` guidance);
  respect `rate_limit`/`jitter` from config (do **not** hardcode like QuintoAndar's
  current `sleep`). Handle missing coordinates gracefully (dedup falls back to
  platform id + text).
- **Acceptance.** `POST /scrape {platform:"olx"}` ingests real listings; a known
  duplicate across the two platforms produces one `Property` with two
  `property_listings`; scraper self-registers (appears in `GET /platforms`).
- **Conflict surface.** Mostly isolated (new file), but relies on the
  `property_listings` write path — **depends on `property-listings-table`**.

### `saved-searches-watchlist` — Saved searches & favourites
- **Goal.** Let the user save named filter sets and bookmark individual properties.
- **Why.** The Properties page has rich filters but no persistence — users re-enter
  the same query each visit and can't keep a shortlist.
- **Affected areas.** New `saved_searches` and `favorites` tables + models +
  migration; API `GET/POST/DELETE /saved-searches`, `GET/POST/DELETE /favorites`;
  frontend: sidebar "Saved searches" list that reapplies filters, a ★ on
  `PropertyCard`, and a Favourites view (reuse the grid with an id filter).
- **Approach.** A saved search stores the exact query-param object the Properties
  page already builds (`src/api.js::fetchProperties`). Single-user for now (no
  auth), so no user_id — but design the table with a nullable `owner` for the
  future `frontend-auth` work.
- **Acceptance.** Save a filter set, reload the page, reapply it and get the same
  results; favourite/unfavourite persists across reload; Favourites view lists only
  starred properties.
- **Conflict surface.** `alembic/`, `models.py`, Properties page + `api.js`. Shares
  the ★ UI with `price-drop-alerts`.

## Tier 2 — AI depth

### `configurable-ai-models` — Configurable AI models & backend
- **Goal.** Drive the VLM/text models, backend, timeout and max-tokens from config
  instead of hardcoded values, and make LM Studio a working backend.
- **Why.** `OllamaClient.analyze_visuals` hardcodes `"llava"` and `analyze_text`
  hardcodes `"llama3"`, ignoring `ai.default_model`; `LMStudioClient` implements
  only `chat_completions` (no `analyze_visuals`/`analyze_text`), so switching
  backends breaks enrichment. Users can't try better/smaller models per the VRAM
  budget.
- **Affected areas.** `src/adapters/ai/client.py` (read model/backend/timeout/
  max_tokens from `cfg.ai`; allow separate `visual_model`/`text_model`; complete
  `LMStudioClient.analyze_visuals/analyze_text` incl. base64 image messages; fix
  `create_ai_client` provider selection and the wrong `getattr(...,'ollama')`
  default); `configs/app_config.yaml` (add `visual_model`/`text_model`);
  `POST /admin/ai/model` optional runtime override (Redis, like scoring weights).
- **Acceptance.** Setting `ai.backend: lmstudio` performs a real enrichment; changing
  `visual_model` changes the model called (assert via a mocked client in tests);
  `validate.sh backend` green. **Depends on `config-yaml-loader`.**
- **Conflict surface.** `client.py`, `configs/app_config.yaml`.

### `deal-summary-enrichment` — Natural-language "why it's a deal" verdict
- **Goal.** Produce one concise PT-BR verdict per property fusing statistical
  valuation, visual condition, and description sentiment.
- **Why.** The three signals already exist (`stat_score`, visual `VisualResult`,
  `SentimentResult`) but the user must mentally combine them. A single sentence
  ("~12% below Savassi median, good condition, no red flags") is the product's
  punchline.
- **Affected areas.** `src/adapters/ai/prompts.py` (new synthesis prompt),
  `src/adapters/ai/client.py` (a `summarize_deal(stat, visual, sentiment)` call, or
  a deterministic template if no extra model budget), `src/adapters/queue/tasks.py`
  (`ai_enrich` writes the summary into `metrics_scoring.meta`),
  `src/api/properties.py` (surface `deal_summary`), frontend card + modal render it.
- **Approach.** Prefer a template-with-optional-LLM approach so it works even when
  GPU is paused; keep it inside the existing `ai_enrich` GPU-semaphore section if it
  calls a model. Reuse the neighbourhood stats already computed.
- **Acceptance.** Enriched properties show a coherent one-line verdict consistent
  with their scores; degrades gracefully when a signal is missing.
- **Conflict surface.** `tasks.py`, `scoring` meta, frontend cards.

## Tier 3 — Design / UX (mostly frontend-isolated, parallel-safe)

### `map-view` — Interactive map of properties
- **Goal.** A map that plots the current property result set as score-coloured
  markers with popup summaries, filterable by viewport.
- **Why.** Location is the #1 real-estate dimension; lat/lon + PostGIS are stored
  but only ever shown as a number in the modal. A map makes spatial deal-hunting
  intuitive.
- **Affected areas.** Frontend: add MapLibre GL (or Leaflet) dep, a `/map` route +
  `MapView.jsx`, a "list ⇄ map" toggle on Properties; reuse `fetchProperties`.
  Backend: add optional `bbox=minLon,minLat,maxLon,maxLat` filter to
  `GET /properties` (PostGIS `ST_MakeEnvelope` + `ST_Within`).
- **Approach.** Colour markers by `combined_score` using the existing
  `--score-high/mid/low` CSS vars; popup reuses the card summary; clicking opens
  `PropertyModal`. Cap markers / cluster for large result sets.
- **Acceptance.** Map shows markers at correct coordinates; panning refetches within
  bounds; clicking a marker opens the property; scoreless properties render neutral.
- **Conflict surface.** New route + one API param — low. Coordinates loosely with
  `frontend-ux-hardening` (shared Properties page).

### `dashboard-charts` — Charts for pipeline & market insight
- **Goal.** Replace number-only tiles with real charts using the already-installed
  `recharts`.
- **Why.** `recharts` is a declared dependency but imported nowhere; the data
  (AI throughput telemetry, enrichment rate, score/price distributions, price
  history) is chart-shaped and currently under-communicated.
- **Affected areas.** Frontend: `Dashboard.jsx` (enrichment-rate & queue-throughput
  time series from `/system/pipeline` telemetry), `PropertyModal.jsx` (price-history
  line — **depends on `price-history-tracking`**), optional score/price-per-m²
  histogram on Properties. Backend: a small `GET /system/metrics/history` if the
  Redis telemetry ring isn't enough for a time series.
- **Approach.** Follow the `dataviz` skill's palette/mark guidance; make charts
  render in the existing dark theme; accessible tooltips; no chart for <2 points.
- **Acceptance.** Dashboard shows a live-updating throughput chart; modal shows a
  price-history line when data exists; charts are readable in the dark theme.
- **Conflict surface.** Dashboard/Modal/Properties — coordinate with
  `frontend-ux-hardening` and `map-view` on shared pages.

### `frontend-ux-hardening` — Toasts, error states & dynamic filters
- **Goal.** Production-feel UX: non-blocking notifications, resilient data states,
  and data-driven filter options.
- **Why.** Dashboard uses blocking `alert()`; the Properties grid fails silently
  (only `console.error`) on load errors; the 30 neighbourhood options are hardcoded
  BH names in `Properties.jsx`, so the filter breaks for any other city.
- **Affected areas.** Frontend: a lightweight toast provider + hook (replace all
  `alert()`), error/empty/retry states on the Properties grid, remove the dead
  `toggleNeighborhood` closure, drive the neighbourhood/city multiselect from a new
  endpoint. Backend: `GET /neighborhoods` (distinct neighbourhoods/cities with
  counts from `neighborhoods` + `properties`).
- **Acceptance.** No `alert()` remains; a forced API failure shows an inline error
  with a working Retry; neighbourhood options reflect actual data; empty result set
  shows a proper empty state.
- **Conflict surface.** Properties page + App shell + `api.js`. Sequence with
  `map-view`/`dashboard-charts` or split by component.

## Tier 4 — Robustness / efficiency (opportunistic)

### `pipeline-resilience` — Wire circuit breakers & skip unchanged AI
- **Goal.** Use the existing resilience code and stop wasting GPU on unchanged
  listings.
- **Why.** `circuit_breaker.py` and `redis_circuit_breaker.py` are fully implemented
  but imported nowhere. And because `dedupe` never returns action `"noop"`,
  `tasks.py`'s `!= "noop"` guard always passes, so **every** scrape re-enqueues
  `ai_enrich` even when nothing changed — expensive on a single-GPU box.
- **Affected areas.** `src/adapters/scrapers/quintoandar.py` (+ future scrapers) and
  `src/adapters/queue/tasks.py::scrape_listings` (wrap platform HTTP in the Redis
  circuit breaker; open-circuit → retry/backoff instead of hammering);
  `src/core/dedupe.py` (return `"noop"` when an existing listing is unchanged —
  same price and key fields); `tasks.py` (only enqueue `ai_enrich` on
  `created`/meaningfully-`updated`, and when images changed or scores are missing).
- **Acceptance.** Repeated scrape of unchanged data enqueues zero `ai_enrich` tasks
  (assert via queue length / telemetry); simulated platform failures trip the
  breaker and back off; existing tests still pass.
- **Conflict surface.** `dedupe.py`, `tasks.py`, scrapers — coordinate with the
  Tier-0/Tier-1 features that also touch `dedupe.py`; land after them.

---

# Backlog (ideas, not yet queued — promote to the table when ready)

Short specs; flesh out before queuing.

- **`semantic-search`** — Free-text search over descriptions via embeddings
  (pgvector column on `properties`, embed on ingest, `GET /properties?q=`). Needs a
  local embedding model + `pgvector` extension/migration.
- **`property-comparison`** — Select 2–4 properties and compare side-by-side
  (attributes, scores, price/m², price history). Frontend-only over existing data.
- **`frontend-auth`** — Replace the hardcoded `X-API-Key: dev-secret-key` in
  `frontend/src/api.js` with an env-driven key and a minimal login gate; wire the
  nullable `owner` columns reserved by `saved-searches-watchlist`.
- **`proxy-rotation`** — Implement the `proxy` config block (rotating pool,
  round-robin/random) in the scraper HTTP layer for scale/anti-block.
- **`export-and-report`** — CSV/JSON export of a filtered result set and a
  scheduled "top new deals this week" digest (builds on `scheduled-scraping` +
  notifier).
- **`neighborhood-polygons`** — Populate `neighborhoods.geometry` (currently unused)
  and assign properties by spatial containment instead of the `props_json` string
  fallback, improving stat-scoring cohorts.
