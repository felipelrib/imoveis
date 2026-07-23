# Addendum — Imoveis Deal Tracker PRD

Technical and planning notes that should not bloat the PRD spine.

## Mechanism decisions (for architecture)

- Stack: FastAPI, Celery+Redis, PostgreSQL 15 + PostGIS + pgvector, React/Vite, host Ollama.
- Scraper plugin registry; queues `scrapers` vs `ai` (GPU concurrency 1).
- Dedup defaults: 50 m geo, ±2 m² area, Jaro–Winkler ≥ 0.65 (config-driven).
- Implementation gates: `scripts/agent/validate.sh`, `finish-feature.sh --pr`, babysit-pr — not replaced by BMad story cycle alone.

## Alternatives considered (product)

| Theme | Chosen for now | Rejected / deferred |
|-------|----------------|---------------------|
| Hosting | Local-first single operator | Multi-tenant cloud SaaS |
| AI | Local Ollama/LM Studio | Cloud-only LLM |
| Planning | BMad Method retrofit PRD | Stay Linear-only without PRD |
| Parallel agents | Worktree when primary busy (ADR 0004) | Always-on nested `.worktrees/` |

## Debt carried into planning (not v0.5 commitments)

- Condo/IPTU not normalized across platforms
- Dead listing URL pruning
- Config hot-reload absent
- Map tiles require internet
- Image store MD5 identity; `asyncio.run` inside sync Celery AI tasks
- Schedule changes may need Celery beat restart

## Linear mapping (pre-epic)

| FR | Rough Linear seed |
|----|-------------------|
| FR-15 | BIN-18 (Done) + BIN-38 reconcile |
| FR-18 | BIN-19 |
| FR-19 | BIN-20 |
| FR-20 | BIN-21 |
| FR-21 | BIN-22 |
| FR-22 | BIN-23 |
