# Companion — Architecture delta & ticket altitude

**Audience:** Felipe (builder / senior SWE)
**Job:** Keep `docs/architecture.md` and Linear tickets useful — enough to act, not a second novel.
**Spine:** `ARCHITECTURE-SPINE.md` (same folder) is the build contract. This note is the human-facing delta.

## vs `docs/architecture.md` (today)

| Topic | `docs/architecture.md` | Spine adds / corrects |
| --- | --- | --- |
| Layout | Source tree + component blurbs | Same tree, named as **hexagonal roles** |
| Data flow | Scrape → … → alerts | Same path, named **pipeline**; boundaries are hexagonal |
| Stack table | Per-feature updates | Spine seed (refreshed 2026-08-05): PostGIS 17-3.5 + pgvector-from-source, maplibre-gl 6, pip-compile lockfile (all deps pinned), FlareSolverr sidecar; code/lockfiles own drift |
| Dependencies | Implicit | **AD-1:** `core` ↛ `adapters`/`api` (ideal; current leaks = debt) |
| Config | Mentions YAML | **AD-2:** only AppConfig channel |
| Entities | Light | **AD-3:** Property / Listing; pipeline-only commercial/geo writes |
| AI | Ollama + semaphore | **AD-4:** never inline from API; `ai` queue only |
| Scrapers | Plugin pattern | **AD-5:** registry-only entry + resilience contract |
| Auth | Not really covered | **AD-6** + **AD-11:** API edge; one principal |
| Deploy / local AI | Absent / “Ollama / LM Studio” | **AD-7** (amended 2026-08-05): Compose incl. `flaresolverr` (profile `bypass`) + `ollama_init` + host-local AI |
| Cloud AI assist | Feature docs only (BIN-242/248) | **AD-13:** optional, operator-triggered, batch-backfill-only — incremental enrichment stays local; every cloud call metered by the single pacer (`BackfillConfig.redis_prefix`, default `backfill:gemma`); unmetered cloud config fails FR-27 startup validation; one runner lease at a time; backfill runner = sanctioned second *driver* through the AD-10 authority (AD-4/AD-10 notes) |
| Frontend | Component blurb | **AD-8:** API-only I/O |
| Alerts | End of pipeline arrow | **AD-9:** one notifier preference registry; Celery delivery |
| Enrichment writes | Implicit | **AD-10:** single ordered pipeline writer |
| Compare vs export shapes | Absent | **AD-12:** one API-owned property projection |

**Practical edit to `docs/architecture.md` later:** add a short “Invariants” pointer to this spine (or paste AD-1..13 one-liners). Don’t duplicate the full Stack seed.

## Linear / ticket altitude

Write tickets so a parallel agent can implement without inventing a second architecture:

**Include**

- Which **AD(s)** apply (e.g. FR-20 → AD-5 + AD-2)
- Where code should live (`adapters/scrapers` vs `api` vs `frontend`)
- What must *not* happen (e.g. “no `os.getenv` in feature module”, “no Ollama call from FastAPI route”)
- Test / validate gate if special (`validate-scrapers.sh` when HTML/scrapers change)

**Skip**

- Full class diagrams or file-by-file patches in the ticket body
- Re-explaining the whole pipeline every time
- Git rebase instructions (harness / babysit owns that)

**v0.13 theme cheat-sheet** *(v0.5 sheet retired — FR-18..22 all shipped)*

| FR | One-liner | Primary ADs |
| --- | --- | --- |
| 27 | Multi-backend enrichment routing (`ai.backend` per task class) | AD-13, AD-2, AD-4 |
| 28 | Quota-governed cloud backfill as operator surface | AD-13, AD-4, AD-10, AD-6 |
| 29 | Enrichment coverage telemetry (DB-derived) | AD-12, AD-2 |
| 30 | Price/m² percentile views | AD-12, AD-3, AD-8 |
| 31 | Total-cost-of-occupancy normalization | AD-3, AD-12 |
| 32 | Saved-search new-match alerts | AD-9, AD-11 |

## Known debt (don’t “ratify” in tickets)

- AD-1 leaks **still open as of 2026-08-05**: `core/dedupe.py` imports ORM models and enqueues alerts, and lazy `from adapters…` imports have spread across `core` (neighbourhood_*, risk/safety overlays, enrichment_rerun, olx_location). Burn down via dedicated stories; don’t add more of the same.
- A running multi-day cloud backfill and a `validate.sh`/`finish-feature.sh` cycle must never overlap (both touch the primary Postgres container) — FR-28's surface exists partly to make an active backfill visible.
