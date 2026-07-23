# Next chat — `bmad-prd` Create (hand-off)

Copy into a **fresh** Cursor chat on branch `feat/bmad-method-adoption` (or after merge, on `main` with artifacts present).

## Invoke

```
bmad-prd Create
```

Or open the skill `.agents/skills/bmad-prd` / `.agents/skills/bmad-create-prd`.

## Intent (paste)

```
Create a retrofit PRD for Imoveis — Deal Tracker.

Decisions already locked:
- BMad Method track
- English artifacts
- Baseline = shipped MVP (Linear milestones v0.1–v0.4 are 100% Done)
- Then define goals, KPIs, non-goals, and prioritized themes for v0.5 / Beyond MVP

Product one-liner:
Local-first Brazilian real-estate deal tracker (BH/MG): scrape QuintoAndar + OLX →
geospatial/heuristic dedupe → price history → local Ollama AI enrich → score-coloured
React UI + watchlist price-drop alerts.

Constraints:
- Local-first, single-tenant today (auth incomplete — BIN-20)
- Config via configs/app_config.yaml / AppConfig only
- Implementation gates stay on scripts/agent/ (ADR 0002 + ADR 0003)

Grounding sources (read before inventing requirements):
- README.md, docs/index.md, docs/architecture.md, docs/features/
- docs/adr/0002-cursor-single-agent-workflow.md, docs/adr/0003-bmad-planning-bridge.md
- _bmad-output/planning-artifacts/bmad-help-session.md
- Linear project Imoveis — Deal Tracker; parent BIN-31; open Future items BIN-18..23
  (BIN-18 was partially implemented at hand-off — **reconciled Done** in BIN-38 / PR #16)

Output: English PRD under _bmad-output/planning-artifacts/ (plus addendum/memlog per workflow).

When done: mark Linear BIN-33 Done and tell me to start BIN-34 (bmad-architecture) in a fresh chat.
```

## Linear

- Parent: https://linear.app/felipelrib/issue/BIN-31/bmad-method-adoption-planning-spine-retrofit-mvp-v05
- This step: https://linear.app/felipelrib/issue/BIN-33/create-retrofit-prd-mvp-baseline-v05-via-bmad-prd
