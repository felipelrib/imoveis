# blend-neighbourhood-profiles-scoring-ui — objective nhood scores in combined ranking + UI

> Feature branch: `feat/bin-94-neighbourhood-scoring-ui` · Linear: `BIN-94` · Status: implemented

## Problem

Listing LLM “location sentiment” was treated like neighbourhood truth and drove 40% of `ai_score`. Objective neighbourhood profiles (amenity / transit / access / safety) lived only on `/properties/neighborhoods` and never influenced property ranking or the property card/modal.

## Approach

- Project a nested `neighbourhood_quality` object on property list/detail (live JOIN — no new metrics column).
- Blend `neighbourhood_score` (mean of available sub-scores; neutral 0.5 when empty) into combined scoring with `neighbourhood_weight: 0.20` (stat/ai 0.40 each).
- Down-weight listing text inside `ai_score` (`visual_weight: 0.70`, `text_weight: 0.30`).
- Relabel listing sentiment as **ad claims** in UI + deal-verdict prompt/template; prefer objective nhood in the LLM prompt when signals conflict.
- Geo profile updates still only need `POST /admin/scoring/recalculate` (no GPU). Full AI re-enrich after epic is an operator step (BIN-95).

## Changes

Files touched:

```
 configs/app_config.yaml                                 | scoring + AI weight defaults
 src/core/entities.py                                    | ScoringWeights three-way sum
 src/core/neighbourhood_quality.py                       | aggregate_neighbourhood_score + profile score
 src/infra/config.py                                     | ScoringConfig.neighbourhood_weight; AI defaults
 src/adapters/metrics/scoring.py                         | blend + recalc JOIN to neighborhoods
 src/adapters/queue/tasks.py                             | combined blend + verdict nhood payload
 src/adapters/ai/prompts.py                              | deal verdict: objective nhood + ad claims
 src/adapters/ai/client.py                               | template listing-claim wording + nhood parts
 src/api/property_projection.py                          | neighbourhood_quality on list/detail
 src/api/properties.py                                   | detail SELECT quality columns
 src/api/schemas.py                                      | NeighbourhoodQualityModel on Property*
 frontend/src/components/PropertyModal.jsx               | Neighbourhood quality + Ad claims labels
 frontend/src/pages/Properties.jsx                       | card nhood badge + Ad claims framing
 frontend/src/components/CompareView.jsx                 | quality / risk compare rows
 frontend/tests/e2e/neighbourhood-quality-labels.spec.js | NEW — label regression
 docs/features/75-blend-neighbourhood-profiles-scoring-ui.md | NEW — this doc
 _bmad-output/implementation-artifacts/sprint-status.yaml | 6-9 done
```

## New Dependencies

None.

## How to Test

1. Unit / backend:
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. After deploying weight changes, refresh combined scores without AI:
   ```bash
   curl -X POST -H "X-API-Key: $API_KEY" http://localhost:${API_PORT:-8000}/admin/scoring/recalculate
   ```
3. Open a property modal: confirm **Neighbourhood quality** is separate from **Ad claims (listing)**.
4. After prompt/model/verdict changes: Dashboard **AI Enrichment re-run** (or
   `POST /admin/enrichment/rerun`) — see `docs/features/76-selective-ai-enrichment-rerun.md`.
   Geo profile / weight-only updates still use recalculate (no GPU).

## Notes / Follow-ups

- Operator should recalculate after geo profile fills; use BIN-95 AI re-run when stored
  `ai_score` / `deal_summary` must pick up prompt or nhood-aware verdict changes.
- Related: BIN-85 epic, BIN-86 profile schema, BIN-95 selective AI re-run
  (`docs/features/76-selective-ai-enrichment-rerun.md`).
