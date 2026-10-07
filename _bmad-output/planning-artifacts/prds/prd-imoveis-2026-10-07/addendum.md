# Addendum — Imoveis Deal Tracker PRD (2026-10-07)

Technical and planning depth that belongs downstream (architecture, epics) or supports the PRD without bloating it. Supersedes the 2026-08-05 addendum; entries still true are carried forward, entries made stale by v0.13 delivery are marked.

## Grounding snapshot (2026-10-07) — what the code does today

Extracted from source for this update so architecture does not re-derive it. File:line cites are as of `main` at 31995d8f.

### Enrichment surface
- Task classes (`src/core/enrichment.py:33-40`): `visual`, `sentiment`, `deal_verdict`, `valuation`, `embedding`. Backends (`:43-55`): `ollama`, `lmstudio` (local), `gemini`, `gemma` (cloud). Default routing: every class → `ollama` (`configs/app_config.yaml:284-289`). Routing map must cover every class; cloud values honoured only on the backfill path with a key present; `embedding` never goes to cloud (`src/adapters/ai/client.py:1315-1365`).
- Outputs: `visual` → `metrics_scoring.meta.visual` (`condition_score`, 5-value category, `features_detected[]`, `issues_detected[]`); `sentiment` → `meta.sentiment` (`sentiment_score`, 5-value category, free-text `green_flags[]`/`red_flags[]`); `deal_verdict` → `meta.deal_verdict` (`verdict`, `confidence`); `embedding` → `properties.embedding` vector(1024) bge-m3. `ai_score = 0.7·visual + 0.3·sentiment`.
- **No Attribute extraction exists** from text or photos; FR-26 "description enrichment" is, in code, the sentiment pass plus scraper-side description fetching. FR-39's `attributes` is therefore a **new task class**, plus an extension of the visual prompt for photo-derived Attributes.
- Structured output today: Ollama `format="json"`; Gemini/Gemma `response_format: json_object`; **LM Studio client sends no `response_format`** and hardcodes `max_tokens` (1024 visual/sentiment, 256 verdict) (`client.py:770,804-826,848,882`); 3-attempt invalid-JSON retry + Pydantic validation + [0,1] clamp on all backends. `LMStudioClient` lacks `generate()` which the OLX location prompt path calls (`src/core/olx_location.py:362-388`) — a Strata route for all text classes would need that path fixed or kept on Ollama.
- Concurrency: Redis `GPUSemaphore`, `gpu.semaphore_limit: 2`; visual and sentiment run sequentially per Property.

### Photo pipeline
- All scraped URLs stored in `properties.image_urls` (JSON); downloads capped at `ai.max_images_per_property: 8`; stored at `{base}/{property_id}/{sha256}{ext}` (docstring says MD5 — stale); downscaled to 768 px longest side, cached `.d768.jpg`.
- Photo gate (`src/core/photo_gate.py`, `config.py:383-395`): `effective_min = max(floor_min=8, ceil(8 × coverage_ratio=1.0))` → 8; sub-threshold Properties persisted `active=false`, re-checked on re-runs (BIN-182 raised floor 3→8, max images 5→8, `num_ctx` 16384).
- **BIN-146 follow-up still open:** `src/core/dedupe.py:222` assigns `prop.image_urls, prop.props_json = candidate.image_urls, candidate.props_json` unguarded on fuzzy match. Consequence for FR-39: a `photo`-provenance Attribute must stamp the gallery hash set it read, or be invalidated when `image_urls` changes. Architecture decision: stamp (cheap, auditable) vs re-run (costly).
- Strata has **no Windows vision path** (AMD vision = Linux-only CPU encoder, ~3 s/photo at 300 tokens on 8 cores). `visual` stays on Ollama in every spike outcome.

### Scraper field coverage (drives the Attribute schema)

| Field | QuintoAndar | OLX | ZapImóveis |
|---|---|---|---|
| Rent / sale price | yes (`rentPrice` kept as `base_price`) | yes | yes |
| Condo fee | `condoFee`, else bundled `condoIptu`, else `totalCost−rent` | labelled prop | `prices.<side>.condominium`; JSON-LD fallback via `additionalProperty` |
| IPTU | `iptu`; `None` when bundled | labelled prop | `prices.<side>.iptu` **often annual, stored as published**; JSON-LD fallback always `None` |
| Total monthly | `totalCost` or rent+condo+iptu → stored as listing `price` | rent_base+condo+iptu → stored as `price` (**0.0 used for missing fee in the sum**) | **not computed**; `price` = rental value only |
| Area / bedrooms / bathrooms | yes | yes | yes |
| Suites / floor | no | no | no |
| Parking | yes | yes | yes (JSON-LD fallback: empty) |
| Furnished | `isFurnished` | labelled prop | **no** |
| Elevator / gym / pool | raw codes in `props_json.amenities` only | **never** (`amenities: []`) | raw codes in `props_json.amenities` only |
| Pets | code or flag → `accepts_pets` | labelled prop | code or flag |
| Photos | all URLs, no cap | all URLs | `medias.images[].dangerousSrc` |
| Lat/lon | yes | yes | yes (JSON-LD fallback: none) |

- DB: `Property{area_m2,bedrooms,bathrooms,parking,image_urls,props_json}`; `PropertyListing{is_furnished,accepts_pets,condo_fee,iptu,base_price,raw_json}`. **No column** for suites, floor, elevator, gym, split-AC, total monthly cost. Amenity codes are platform-specific; a committed code→Attribute vocabulary table is required (FR-39 consequence). BIN-114 declined a dedicated "bundled" column — `fees_bundled` lives in `props_json`/`raw_json`.
- Implication for FR-31: rent price/m² (and therefore stat score and percentile) **already includes fees** for QuintoAndar/OLX and excludes them for ZapImóveis — a cross-platform comparability bug FR-31 must address (compute percentile on `base_price` or on Total Monthly Cost consistently; architecture decides, with a characterization lock before changing `scoring.py`).

### Scoring and neighbourhood
- `combined = 0.4·stat + 0.4·ai + 0.2·neighbourhood`; stat = sigmoid(−z) on price/m² within neighbourhood × listing-type cohort; `percentile_rank{,_rent,_sale}` via `PERCENT_RANK()` since BIN-84 (`scoring.py:308-312`) — the baseline the "FR-30 done" remark refers to; Epic 2 s2.1/s2.2 (pipeline + badge/filter) remain backlog.
- Neighbourhood profile: four nullable sub-scores (amenity/transit/access/safety), `risk_flags[]` (`flood_zone`, `industrial_adjacent` managed), `quality_meta` JSONB per source. Transit = offline GTFS stops + OSM, centroid-based proximity score (disabled by default). Access = `ST_PointOnSurface` → fixed hubs (BH: Praça Sete, Savassi) → minutes via **OSRM** `/route/v1/{driving|walking|cycling}` when `base_url` set, else **haversine @ 30 km/h** (`src/adapters/geo/osrm_client.py`, `neighbourhood_access.py`). Stored `quality_meta.access{hub_id,minutes,distance_m,mode,provider}`.
- **Nothing is per-Property**; no POI/Anchor concept; frontend map has clusters only, no polygons/bands.

## Mechanism notes for architecture (FR-35 travel time)

- Car: OSRM already integrated (driving profile); needs a BH extract served locally (Docker) or a hosted OSRM — decide, and make haversine an explicitly labelled estimate or drop it from the travel-time field (FR-35 consequence).
- Transit: OSRM has no transit profile. Local options: OpenTripPlanner 2 or r5/r5py with BH GTFS (BHTrans publishes GTFS; the repo already consumes `stops.txt`) — heavier image, fully local, deterministic departure-time semantics; cloud options: Google Routes / HERE transit as an **optional provider** behind a config flag, off by default (NFR-1 posture, §9 Q2). Either way the stored shape is `{anchor_id, mode, minutes, departure_assumption, provider, computed_at}` with `unknown{reason}`.
- Walk budget for `aulas de música`: OSRM walking profile is sufficient; `walk` is computed only for Anchors declaring a budget.
- Departure-time default weekday 08:00 local (configurable per Anchor) must be part of the stored key so a provider change or a schedule update invalidates the right rows.
- **Anchor coordinates are personal data:** committed schema (an `anchors.example.yaml`-style file), values in a git-ignored local file loaded like `.env.local`; a unit test fails if the committed file carries coordinates. Any cloud routing provider receives Anchor coordinates with every request — weigh that in §9 Q2.
- Recompute triggers: Property location change, Anchor version change, provider change — not every scrape (Celery beat job over stale rows, like `access_refresh`).

## Strata — caller-supplied facts (not independently verified in this run)

From the change signal (Felipe, 2026-10-07): `github.com/Niko1221/Strata`; runs Qwen3.8-Flash-Next (125B MoE, IQ2/Q2 quant) on the RX 7900 XT via a prebuilt Windows HIP engine (since 0.1.34); serves `/v1/chat/completions` with `response_format` `json_object`/`json_schema` implemented as schema prompting + server-side validation (not constrained decoding); ~50–60 tok/s output on RDNA; one request at a time by default, `"parallel": 2` opt-in; no embeddings endpoint; needs ≥ 32 GB RAM (64 recommended; loads 35–55 GB) and ~80 GB NVMe; AMD path marked "not validated" for images and answer quality.

Spike mechanics (config-only integration):
1. `ai.lmstudio_url` → Strata; `enrichment_routing: {sentiment: lmstudio, attributes: lmstudio, deal_verdict: lmstudio, visual: ollama, embedding: ollama}` via the `.env.local` override channel (never the committed config — pinned all-local by unit test).
2. Pre-work the spike will force: send `response_format` from `LMStudioClient` (json_object, or json_schema with the Pydantic schema), make `max_tokens` configurable, decide the OLX-location `generate()` path.
3. Co-residency: Strata (35–55 GB RAM, GPU) + Ollama (`qwen2.5vl:7b` visual + bge-m3) on one 20 GB card — measure VRAM spill; re-tune `gpu.semaphore_limit`/`OLLAMA_NUM_PARALLEL`; `scripts/dev/bench_ollama_vram.py --cases A,D` after changes.
4. A/B harness: adapt `scripts/dev/ab_gemini_vs_ollama.py` to compare `lmstudio`(Strata) vs `ollama`(qwen2.5vl:7b) on ~50 BH listings with hand labels: Attribute exact-match, JSON validity (first-try and after retry), s/Property wall-clock with Ollama co-resident. Record verdict under `planning-artifacts/research/` + ledger.
5. Pass ⇒ also replaces Gemma cloud backfill for text classes (the runner's scope would route text locally; whether Gemma stays available as a quota-bounded assist is an `[ASSUMPTION]` — the signal says "replacement"). Fail ⇒ nothing changes in product scope (`[ASSUMPTION]`, not stated in the signal).

## Sentiment facet seed derivations (FR-36) — starting rules for the vocabulary file

| Facet | Derivation (tri-state `yes`/`no`/`unknown`) | Provenance recorded |
|---|---|---|
| `seguro` | `yes` if neighbourhood `safety_score` ≥ 0.6 and no `red_flags` normalizing to {insegur*, assalto, violên*}; `no` if `safety_score` < 0.4 or such a flag exists; else `unknown` | neighbourhood signal + text flag |
| `reformado` | `yes` if visual category ∈ {pristine, good} **and** description mentions reformad*/renovad*/novo; `no` if visual ∈ {needs_renovation, poor}; else `unknown` | photo + text |
| `silencioso` | `yes` if `green_flags` normalize to {silencios*, tranquil*}; `no` if `red_flags` normalize to {barulh*, movimentad*, avenida}; else `unknown` | text flag |

Thresholds are placeholders for the architecture/epics pass; the rule is that every facet states its inputs, and the mapping is data (committed vocabulary), not code.

## Agent query surface (FR-42) — transport notes

- Default transport: existing FastAPI REST with `X-API-Key`, consumed by Claude Code via HTTP; `docs/api.md` gains an "Agent usage" section with example calls (list fits for a profile, fetch bundle, star, recheck). Contract tests in `src/tests/contract/` for every new schema.
- Sorting/filtering needs: by profile, Fit status, soft score, Total Monthly Cost, minutes to a named Anchor/mode, price-drop %, freshness; pagination. Bundle endpoint returns the FR-40 shape with explicit `unknown` and an `unknown_count`.
- MCP wrapper (FastMCP over the same endpoints) is a later convenience; the REST contract is the product surface. No DB access for the agent.

## Carried-forward mechanism decisions (still true)

- Stack: FastAPI, Celery + Redis, PostgreSQL 17 + PostGIS 3.5 + pgvector, React 19 / Vite 8 / TS strict, maplibre-gl 6, host Ollama / LM Studio, FlareSolverr, pip-compile lockfile; native Windows dev (`requirements-windows.txt`, Git Bash gates).
- Redis multi-surface (broker, slowapi, `ui:locale`, `backfill:gemma*` pacer/heartbeat/migrating keys). Dedup defaults 50 m / ±2 m² / Jaro–Winkler ≥ 0.65. Scraper registry; `scrapers` vs `ai` queues.
- Gates: `validate.sh` is THE merge gate via `finish-feature.sh`; CI = docs deploy + nightly drift canary; bmad-loop wraps gates. Primary stack inviolable; `migrate-primary.sh` heartbeat guard.
- Cloud-assist sizing (Gemma ≈ 14.4k RPD ≈ 4.6k Properties/day; single pacer invariant) — unchanged; relevant to the spike's "replace Gemma on text classes" outcome.

## Alternatives considered (product + process)

| Theme | Chosen (date) | Rejected / deferred |
|-------|---------------|---------------------|
| Primary job | Decision engine for two concrete searches, agent-first (Felipe, 2026-10-07) | Generic BH deal tracker with UI-first experience (2026-08-05 framing) |
| Search definition | Versioned config profiles with hard/soft semantics (FR-41) | Reusing Saved searches (filter presets lack provenance-aware evaluation); profile-builder UI (UI deprioritized) |
| Agent interface | REST read endpoints + contract tests; agent writes prose | MCP server first (convenience, later); agent reading the DB directly (bypasses honesty rules); UI scraping |
| Text backend | Capability FRs routed through `enrichment_routing`; Strata = spike | Strata as an FR; new backend class; cloud text as default |
| Travel time | Per-Property minutes to personal Anchors, car + transit, `unknown` over estimate | Neighbourhood-centroid hubs (existing); km; haversine shown as time |
| FR-31 | Un-deferred with `unknown`/`bundled` semantics (needs §9 Q1 confirmation) | Keep deferred (blocks aluguel-2027 hard constraint) |
| UI in v0.14 | Consume new data on existing surfaces only | New screens; Compare redesign |
| Epic 2 | Folded in as in-flight, order untouched | Re-planning Epic 2 inside this PRD |

## Debt carried into planning

- BIN-146 follow-up: unguarded `image_urls`/`props_json` overwrite on fuzzy merge — **now load-bearing for FR-39** (gallery stamping).
- Image-store docstring says MD5, code is SHA-256 — doc drift.
- LM Studio client: no `response_format`, hardcoded `max_tokens`, no `generate()` — blocks any OpenAI-compatible text backend beyond smoke use.
- Zap IPTU periodicity; OLX zero-vs-None fee sum; fee-inclusive rent price/m² on two of three platforms — all FR-31.
- Dead listing URL pruning; config hot-reload; Celery beat restart on schedule change; `asyncio.run` inside sync Celery AI tasks — still debt.
- Epic 3 retro items 1–3 and Epic 1 retro items 1, 5 open in sprint-status.yaml; fu12/fu13/fu14 backlog.

## Conflicts with prior decisions surfaced in this update

1. **FR-31 deferral (2026-08-05 epics) vs aluguel-2027 total-cost cap** — reversed here; confirmation requested (§9 Q1).
2. **"FR-30 done" (change signal) vs tracker** — Epic 2 s2.1/s2.2 are backlog; a BIN-84 percentile column exists. PRD records tracker truth; nothing re-planned.
3. **FR-35 definition** — 2026-08-05: map POI layer with bands (UI capability); now: per-Property minutes to Anchors, car + transit, agent-readable; map bands demoted to consumer. Decided by the change signal.
4. **FR-36 definition** — 2026-08-05: grid filter on extensible tags; now: structured facets with provenance, API-filterable, usable as profile soft preferences; picker demoted to consumer. Decided by the change signal.
5. **Personas** — Ana/Bruno (2026-08-05 UJ-1/UJ-2) retired; single operator persona. Decided by the change signal ("one operator").
