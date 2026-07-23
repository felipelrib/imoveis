# Companion — Architecture delta & ticket altitude

**Audience:** Felipe (builder / senior SWE)
**Job:** Keep `docs/architecture.md` and Linear tickets useful — enough to act, not a second novel.
**Spine:** `ARCHITECTURE-SPINE.md` (same folder) is the build contract. This note is the human-facing delta.

## vs `docs/architecture.md` (today)

| Topic | `docs/architecture.md` | Spine adds / corrects |
| --- | --- | --- |
| Layout | Source tree + component blurbs | Same tree, named as **hexagonal roles** |
| Data flow | Scrape → … → alerts | Same path, named **pipeline**; boundaries are hexagonal |
| Stack table | Still says React 18 + plain PostGIS in places | Spine seed (refreshed BIN-35): React 19.2 / Vite 8.1, PostGIS 15-3.3 + pgvector via `Dockerfile.postgres`; code/lockfiles own drift |
| Dependencies | Implicit | **AD-1:** `core` ↛ `adapters`/`api` (ideal; current leaks = debt) |
| Config | Mentions YAML | **AD-2:** only AppConfig channel |
| Entities | Light | **AD-3:** Property / Listing; pipeline-only commercial/geo writes |
| AI | Ollama + semaphore | **AD-4:** never inline from API; `ai` queue only |
| Scrapers | Plugin pattern | **AD-5:** registry-only entry + resilience contract |
| Auth | Not really covered | **AD-6** + **AD-11:** API edge; one principal |
| Deploy / local AI | Absent / “Ollama / LM Studio” | **AD-7:** Compose + host-local AI (Ollama and/or LM Studio) |
| Frontend | Component blurb | **AD-8:** API-only I/O |
| Alerts | End of pipeline arrow | **AD-9:** one notifier preference registry; Celery delivery |
| Enrichment writes | Implicit | **AD-10:** single ordered pipeline writer |
| Compare vs export shapes | Absent | **AD-12:** one API-owned property projection |

**Practical edit to `docs/architecture.md` later:** add a short “Invariants” pointer to this spine (or paste AD-1..12 one-liners). Don’t duplicate the full Stack seed.

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

**v0.5 theme cheat-sheet**

| FR | One-liner | Primary ADs |
| --- | --- | --- |
| 18 | Side-by-side compare UI | AD-8, AD-3, AD-12 |
| 19 | Auth / API keys | AD-6, AD-2, AD-11 |
| 20 | Proxy pool for scrapers | AD-5, AD-2 |
| 21 | Export + optional digest | AD-8, AD-9, AD-11, AD-12 |
| 22 | Neighbourhood polygons | AD-3, AD-10, PostGIS seed |

## Known debt (don’t “ratify” in tickets)

- `core/dedupe.py` imports ORM models and can enqueue alerts → violates AD-1; burn down via dedicated stories, don’t add more of the same.
