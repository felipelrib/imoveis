# Companion — Architecture delta & ticket altitude

**Audience:** Felipe (builder / senior SWE)
**Job:** Keep `docs/architecture.md` and story files useful — enough to act, not a second novel.
**Spine:** `ARCHITECTURE-SPINE.md` (same folder) is the build contract. This note is the human-facing delta.

## vs `docs/architecture.md` (today)

| Topic | `docs/architecture.md` | Spine adds / corrects |
| --- | --- | --- |
| Layout | Source tree + component blurbs | Same tree, named as **hexagonal roles**; agent client is a driving client of the API only |
| Data flow | Scrape → … → alerts | Same path, named **pipeline**, now extended **… → travel → fit → alert**; every post-persist stage is a named writer of its own facts |
| Stack table | Per-feature updates | Spine seed (refreshed 2026-10-07): osrm-backend v26.8.0 + OpenTripPlanner 2.8 behind the compose `routing` profile, BH GTFS feeds, Strata ≥ 0.1.34 as a *candidate* reached only via the `lmstudio` backend; code/lockfiles own drift |
| Dependencies | Implicit | **AD-1:** `core` ↛ `adapters`/`api` (ideal; current leaks = debt; new v0.14 `core` modules are pure from day one) |
| Config | Mentions YAML | **AD-2 + AD-16:** one AppConfig loader, now also for `search_profiles.yaml`, `anchors.yaml` (+ git-ignored `anchors.local.yaml` coordinates), `attribute_vocabulary.yaml`, `facets.yaml`; integer `version` is the only invalidation key |
| Entities | Light | **AD-3:** Property / Listing; pipeline-only commercial/geo writes — now including FR-31 cost components (`unknown` never zero) |
| AI | Ollama + semaphore | **AD-4:** never inline from API; `ai` queue only; a co-resident OpenAI-compatible local server (Strata) is GPU work under the same semaphore |
| Scrapers | Plugin pattern | **AD-5:** registry-only entry + resilience contract |
| Auth | Not really covered | **AD-6** + **AD-11:** API edge; one principal; the agent uses the same API-key gate |
| Deploy / local AI | Absent / "Ollama / LM Studio" | **AD-7** (amended 2026-10-07): Compose incl. `flaresolverr` (`bypass`), `ollama_init`, and the opt-in `routing` profile (OSRM + OTP); routing data under git-ignored `data/routing/` |
| Cloud AI assist | Feature docs only (BIN-242/248) | **AD-13:** optional, operator-triggered, batch-backfill-only; single pacer; one routing source of truth |
| Frontend | Component blurb | **AD-8:** API-only I/O — same rule for the agent client |
| Alerts | End of pipeline arrow | **AD-9:** one notifier preference registry; Celery delivery; gone-favourite alerts ride it |
| Enrichment writes | Implicit | **AD-10:** single ordered pipeline writer — now also owns `text`/`photo` Attribute rows, facet values and `fit_summary` |
| Compare vs export shapes | Absent | **AD-12:** one API-owned property projection — the Fit bundle and cohort summary are assemblies of persisted facts, never computed at read time |
| **Attributes** | Absent | **AD-14:** `property_attributes` provenance rows (`scraper`/`text`/`photo`) with typed source columns; conflicts are rows; **one** resolver `core.attributes.resolve()` (no SQL view) with a deterministic intra-provenance tie-break and per-provenance read-time staleness (inactive Listing / description hash / AD-15); legacy columns become row-backed, fallback only when no row exists; writers partitioned by provenance; rows never deleted |
| **Photo evidence** | Absent | **AD-15:** `properties.gallery_fingerprint` (normalized URLs) persisted on the persist path; evidence set = SHA-256 hashes of the files fed to the VLM, immutable per fingerprint (`data/images/<property>/<gallery_fp>/`); every photo fact stamped; staleness decided at read time; one visual candidate SQL fragment shared by runner/rerun/coverage (`ai_score IS NULL` retired as a key); legacy flat dirs ignored; **BIN-146 guard is a prerequisite story** |
| **Task classes** | FR-27 routing map | **AD-17:** `attributes` + `fit_summary` added to the one enum; photo Attributes ride `visual`; `stages` literals retired for a `frozenset` scope with per-class skip keys and one dependency table in `core`; backfill scope derived per class from the routing map (a Strata pass shrinks the cloud scope instead of breaking `--serve`); one Pydantic schema = validator + `json_schema` (object root; Strata 502 = client retry); LM Studio client parity before any production `lmstudio` route; the spike only flips `.env.local` routing values |
| **Travel time** | Neighbourhood hubs (BIN-90) | **AD-18:** `property_travel_times` (property × anchor × version × mode × departure); minutes or `unknown` + reason; OSRM v26.10 (two `osrm-routed`, car + foot) for car/walk, OTP 2.10 **GraphQL `planConnection`** for transit (REST `/plan` is gone), both self-hosted behind one `TravelTimeProvider` port and one `travel_time` config section; cloud transit optional and off; haversine never stored as a time; Anchor endpoint never returns coordinates; recompute via beat on `scrapers` incl. absent rows and backed-off `provider-error` |
| **Fit** | Absent | **AD-19:** `core/fit.py` pure over persisted scope facts + resolved attributes + cost columns + travel + facets; `property_fit_status` per (property, profile, version) incl. `fit_summary`, history retained; trigger = beat sweep on `scrapers` (`updated_at` > `evaluated_at`), fact writers never enqueue Fit; `fit_summary` generated after the row commits from the persisted `FitResult`; reads = loaded version only; `unknown` never yields `fails`; soft prefs only order |
| **Facets** | Absent | **Facets convention:** `property_facets` table written by the facet stage (enrichment order + fit sweep), skip key `inputs_hash`, inputs incl. visual category (AD-15 staleness) and description-text matches; never `metrics_scoring.meta`, never read-time |
| **Cost / price basis** | `price` fee-inclusive on two platforms | **AD-3:** typed cost columns on `property_listings` (`rent_monthly` unbundled, condo, IPTU + periodicity, `fees_bundled`, `total_monthly_cost`, `cost_complete`); cohort price/m² basis = fee-exclusive `rent_monthly` once FR-31 lands (`price_basis` stamped; `headline` until then) behind a characterization lock — Epic 2 s2.1 consumes the same definition |

**Practical edit to `docs/architecture.md` later:** add a short "Invariants" pointer to this spine (or paste AD-1..19 one-liners) and the `… → travel → fit` stages. Don't duplicate the full Stack seed.

## Story altitude

Write stories so a parallel agent can implement without inventing a second architecture:

**Include**

- Which **AD(s)** apply (e.g. FR-39 text extraction → AD-14 + AD-17 + AD-10)
- Where code should live (`adapters/geo` vs `core/fit.py` vs `api`)
- What must *not* happen (e.g. "no resolved-attribute column", "no haversine minutes in `property_travel_times`", "no model call from a FastAPI route", "no YAML opened outside `infra/config.py`")
- Test / validate gate if special (`validate-scrapers.sh` for scrapers, `validate-ai.sh` for prompts/clients, `alembic check` for the new tables, labelled fixture sets for FR-39/FR-31/FR-41, contract tests for FR-42)

**Skip**

- Full class diagrams or file-by-file patches in the story body
- Re-explaining the whole pipeline every time
- Git rebase instructions (harness owns that)

**v0.14 cheat-sheet** *(v0.13 Epic 1/3 sheet retired — shipped; Epic 2 rows kept while in flight)*

| FR | One-liner | Primary ADs |
| --- | --- | --- |
| 30 | Price/m² percentile views (Epic 2, in flight) | AD-12, AD-3, AD-8 |
| 31 | Total Monthly Cost components on the persist path; `unknown`/`bundled`; basis change behind a characterization lock | AD-3, AD-12, AD-19 |
| 32 | Saved-search new-match alerts (Epic 2, in flight) + Alertas/push remainder | AD-9, AD-11 |
| 33 / 34 | Availability recheck; gone / resurrection lifecycle + gone-favourite alert | AD-5, AD-3, AD-9, AD-12 |
| 35 | Minutes to Anchors, car + transit (+ walk budget), OSRM + OTP behind one port | AD-18, AD-16, AD-7, AD-12 |
| 36 | Sentiment facets from a committed vocabulary with derivation rules | AD-16, AD-10, AD-12 |
| 37 / 38 | Scraper run analytics; recent-filter recall | AD-5, AD-12 / AD-8 |
| 39 | Attribute rows with provenance; amenity-code vocabulary; `attributes` text class; photo extension of `visual` with evidence stamps | AD-14, AD-15, AD-16, AD-17, AD-10 |
| 40 | Fit bundle + `fit_summary` as AD-12 assembly | AD-12, AD-19, AD-17 |
| 41 | Search Profiles as versioned config; `core/fit.py`; `property_fit_status` | AD-16, AD-19, AD-10 |
| 42 | Agent read endpoints + star/recheck; contract tests; `docs/api.md` agent section | AD-6, AD-8, AD-12, AD-11 |
| spike | Strata via `lmstudio` routing values in `.env.local`; LM Studio client parity first; A/B harness | AD-17, AD-4, AD-13 |

**Prerequisite stories the spine makes explicit:** BIN-146 fuzzy-merge gallery guard + `properties.gallery_fingerprint` column + normalized-URL fingerprint (AD-15); `stages` → `frozenset` scope with per-class skip keys (AD-17); LM Studio client parity (AD-17); AppConfig sibling-file include, overlay version check, `travel_time` section + anchors pin tests (AD-16/18); `property_attributes` / `property_facets` / `property_travel_times` / `property_fit_status` / `scraper_runs` migrations and the `property_listings` cost columns (AD-14/3/18/19); the visual candidate SQL fragment shared with coverage (AD-15).

## Known debt (don't "ratify" in stories)

- AD-1 leaks **still open as of 2026-10-07**: `core/dedupe.py` imports ORM models and enqueues alerts, and lazy `from adapters…` imports have spread across `core` (neighbourhood_*, risk/safety overlays, enrichment_rerun, olx_location). Burn down via dedicated stories; new `core/attributes.py` and `core/fit.py` must not add more of the same.
- `ImageStore.download_images` returns cached files first regardless of which gallery they came from — AD-15's per-fingerprint evidence directory is the fix, not a workaround to carry forward.
- Image-store docstring says MD5, code is SHA-256 — fix in the AD-15 story.
- Cohort stat score is fees-inclusive on QuintoAndar/OLX and fees-exclusive on ZapImóveis — FR-31's basis change needs the characterization lock first.
- A running multi-day cloud backfill and a `validate.sh`/`finish-feature.sh` cycle must never overlap (both touch the primary Postgres container) — FR-28's surface exists partly to make an active backfill visible.
