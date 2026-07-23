# BMad Help Session — Imoveis (2026-07-23)

## Project context provided

- **Product:** Local-first Brazilian real-estate deal tracker (BH/MG): scrape QuintoAndar + OLX → geospatial/heuristic dedupe → price history → local Ollama AI enrich → score-coloured React UI + watchlist alerts.
- **Stack:** FastAPI, Celery, Redis, PostgreSQL 15 + PostGIS + pgvector, React 18/Vite, host Ollama.
- **Maturity:** MVP milestones v0.1–v0.4 are **100% Done** in Linear. No in-repo PRD. Planning intent lived in Linear + `docs/features/`.
- **Open backlog (at session time):** BIN-18 (semantic search — then In Progress / partial), BIN-19 comparison UI, BIN-20 auth, BIN-21 proxy rotation, BIN-22 weekly digest, BIN-23 neighbourhood polygons.
- **Reconcile (BIN-38, 2026-07-23):** BIN-18 is **Done** (PR #16 + `docs/features/20-semantic-search.md`); no remaining FR-15 scope to split. Open Beyond-MVP seeds are BIN-19–23 (now epics BIN-41..55).
- **Harness:** ADR 0002 single Cursor agent; local `.cursor/` rules/skills; committed `scripts/agent/` validate/finish/babysit gates. Linear team Bino, project Imoveis — Deal Tracker.
- **User decisions:** BMad Method track; **retrofit MVP + plan v0.5+**; English artifacts.

## Artifact scan

| Location | Status |
|----------|--------|
| `_bmad-output/planning-artifacts/` | Help session + PRD hand-off prompt (no PRD yet) |
| `_bmad-output/implementation-artifacts/` | Empty (no sprint-status) |
| `docs/` (project_knowledge) | Architecture, features 01–19, ADRs — rich brownfield knowledge |

## Where you are

- Module: **BMad Method**
- Phase: **2-planning** (Phase 1 analysis optional — skip for this brownfield retrofit)
- Completed BMad required gates: **none**

## Recommended sequence

### Optional (helpful for brownfield, not required)

1. `[GPC]` **Generate Project Context** — `bmad-generate-project-context`
2. `[DP]` **Document Project** — `bmad-document-project`

### Next required

3. `[PRD]` **Create Edit and Review PRD** — `bmad-prd`
   **Action: Create.** Intent: retrofit shipped MVP as baseline; define goals/KPIs/non-goals for **v0.5 / Beyond MVP**. English.
   Output: `_bmad-output/planning-artifacts/` PRD (+ addendum/memlog).
   Starter: `NEXT-bmad-prd-prompt.md`

### Then (required Method track)

4. `[CU]` **Create UX** — `bmad-ux` (optional if UI-heavy)
5. `[CA]` **Architecture** — `bmad-architecture` (brownfield: ratify; delta vs `docs/architecture.md`)
6. `[CE]` **Create Epics and Stories** — `bmad-create-epics-and-stories`
7. `[IR]` **Check Implementation Readiness** — `bmad-check-implementation-readiness`
8. `[SP]` **Sprint Planning** — `bmad-sprint-planning` → story cycle

### Implementation bridge

After stories: sync to Linear → `setup-branch.sh` → TDD → `validate.sh` → `finish-feature.sh --pr` → babysit. See `.cursor/skills/imoveis-planning-bridge/SKILL.md` and ADR 0003.

## Fresh-chat rule

Run each major workflow in a **fresh Cursor chat**.
