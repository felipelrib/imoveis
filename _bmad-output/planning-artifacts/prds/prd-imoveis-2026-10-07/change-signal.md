# Change signal — bmad-prd Update, 2026-10-07

Verbatim intent supplied by Felipe in the `bmad-prd` invocation (the referenced
`NEXT-bmad-prd-update-2026-10-07.md` did not exist in the checkout; this is the signal of record).

```
Update the Imoveis PRD. The product's primary job changes from "generic deal tracker for BH"
to "decision engine for TWO concrete searches run by one operator, with an AI agent (Claude
Code) as the main query client and the React UI as a secondary surface".

Decisions already locked (Felipe, 2026-10-07):
- Two search profiles, versioned in configs/, are first-class product objects:
  * aluguel-2027: apartment, BH, 2 bedrooms (one is a home office), >= 1 parking spot,
    TOTAL monthly cost (rent + condo + IPTU) <= R$ 4.000 (prefer less), unfurnished,
    gym in building desirable, split-AC allowed, elevator desirable. Move-in by Mar/2027.
  * compra-2028: 3–4 bedrooms, >= 2 parking spots, purchase ~mid-2028.
- Personal anchors for travel time (FR-35 input): igreja (Palmares), casa da Nala
  (Santo Antônio), casa da mãe (Planalto), Centro, aulas de música (walking distance
  from current home). Minutes by car and by transit, never km.
- Operator hardware stays AMD RX 7900 XT 20 GB + Ollama. Local-first invariant (NFR-1) holds.
  Strata (github.com/Niko1221/Strata) is a CANDIDATE TEXT BACKEND, to be settled by a spike,
  not an FR: it runs Qwen3.8-Flash-Next (125B MoE, IQ2/Q2 quant) on the RX 7900 XT (Windows
  HIP engine prebuilt since 0.1.34), serves /v1/chat/completions with response_format
  json_object/json_schema (schema prompting + server validation, not constrained decoding),
  ~50-60 tok/s output on RDNA, one request at a time by default ("parallel": 2 opt-in).
  Constraints that bound the spike: vision on AMD is Linux-only through a CPU encoder
  (~3 s/photo at 300 tokens, 8 cores) and unavailable on Windows; no embeddings endpoint
  (bge-m3 stays on Ollama, sharing the GPU); needs >= 32 GB RAM (64 recommended, loads
  35-55 GB) and ~80 GB NVMe; AMD path marked "not validated" for images and answer quality.
  Integration is config-only through the existing `lmstudio` backend + `enrichment_routing`
  (route sentiment / attributes / deal_verdict to Strata; visual + embedding stay on Ollama).
  Spike exit criteria: A/B vs qwen2.5vl:7b on ~50 listings (attribute accuracy, JSON validity,
  seconds per property with Ollama co-resident), using scripts/dev/ab_gemini_vs_ollama.py
  adapted. If it passes, it becomes the text route for FR-39/FR-40 and a local replacement
  for the Gemma cloud backfill on text classes.
- v0.13 Epic 2 (FR-30 done; FR-32 and 2-1..2-5 still backlog) is NOT re-litigated; fold its
  status in as baseline/in-flight. The v0.14 wave (FR-33–FR-38) is kept but RE-SCOPED around
  the change signal: FR-35 and FR-36 are promoted and redefined; FR-33/34/37/38 stay as planned.
- UI work is deprioritized: the operator will mostly read agent-produced dossiers and open
  listing links. Compare stays minimal; no new screens unless an FR cannot be exercised
  otherwise.

Grounding sources (read before inventing requirements):
- The current PRD + addendum, epics.md, sprint-status.yaml, deferred-work ledger
- src/adapters/ai/prompts.py, enrich_pipeline.py, image_store.py, client.py
- src/adapters/metrics/scoring.py, src/core/neighbourhood_quality.py, neighbourhood_access.py
- src/adapters/scrapers/{quintoandar,olx,zapimoveis}.py (field coverage)
- configs/app_config.yaml (ai.*, scoring.*, neighbourhood_quality.*, transit.*, photo_gate.*)
- docs/features/BIN-182-photo-gate-floor-8.md, BIN-146 (dedupe overwrites image_urls)

Output: new versioned PRD folder + addendum under _bmad-output/planning-artifacts/prds/,
status final, with FR numbering continuing from FR-38. Then tell me to run
bmad-architecture (fresh chat) for the attribute/photo schema, and bmad-create-epics-and-stories
for v0.14.
```
