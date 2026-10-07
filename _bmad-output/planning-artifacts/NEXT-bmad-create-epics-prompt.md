# Next chat — `bmad-create-epics-and-stories` for v0.14 (hand-off)

Copy into a **fresh** chat on `main` (artifacts are merged). Written 2026-10-07 at the end of the `bmad-architecture` update run.

## Invoke

```
bmad-create-epics-and-stories
```

## Intent (paste)

```
Create the v0.14 epics and stories for Imoveis — Deal Tracker from the 2026-10-07 PRD and the
updated architecture spine (AD-1..19). planningTarget = v0.14.

Decisions already locked (Felipe, 2026-10-07):
- FR-31 Total Monthly Cost is UN-DEFERRED (PRD Q1 confirmed). Tier 1 foundation; AD-3 cost
  columns on property_listings bind.
- Anchor coordinate invalidation = overlay version lock (AD-16 as written). The coordinate-hash
  alternative is rejected.
- Cohort price/m² basis = fee-exclusive rent_monthly once FR-31 lands, stamped price_basis on
  metrics_scoring (headline until then), behind a characterization lock (AD-3). The percentile
  pipeline story (old s2.1) consumes that single definition and never hardcodes `price`.
- PRD Q3 ordering: there is NO separate "v0.13 in-flight" wave any more. Every pending v0.13 item
  is transferred into v0.14 as ONE carry-over epic (suggested: Epic 1 "v0.13 carry-over") so a
  single deliverable plan exists. Re-key the carried stories as v0.14 story keys; mark the old
  v0.13 keys superseded in sprint-status.yaml (never downgrade a `done`).
- PRD Q2 (transit provider): answered by AD-18 — local OSRM + OpenTripPlanner 2.10 behind one
  port; cloud transit optional, off by default.
- Strata is a spike (PRD §6.4), not an FR; it only flips `.env.local` routing values (AD-17).

Pending v0.13 inventory to fold into the carry-over epic (from sprint-status.yaml and
deferred-work.md on 2026-10-07):
- Epic 2 stories still open: 2-7 corpus-repair-fabricated-scores (awaiting-operator:
  `bash scripts/agent/migrate-primary.sh`), 2-1 cohort-price-m2-percentiles-pipeline,
  2-2 percentile-badge-and-filter, 2-3 saved-search-new-match-detection,
  2-4 saved-search-alert-management-ui, 2-5 detail-side-panel-migration (all backlog).
  Old gates: 2-1 ← 2-7 + DW-32; 2-2 ← 2-1 + 2-6; 2-3 ← 2-1; 2-4 ← 2-3 + 2-6; 2-5 ← 2-2 + 2-6.
- Open retro action items: epic-1-retro-item-1-escalation-reverification,
  epic-1-retro-item-5-ledger-budget-per-epic, epic-3-retro-item-1-operator-actions-batch-per-wave,
  epic-3-retro-item-2-followup-review-flag-disposition, epic-3-retro-item-3-dw32-drain-before-epic-2.
- Backlog follow-ups: v0.13-fu12 plural-agreement sweep (dashboard keys), v0.13-fu13 toast/compare
  bar bottom strip, v0.13-fu14 setup-worktree renames bmad-loop branches.
- Open deferred-work ledger entries (21): DW-8, 9, 10, 12, 13, 14, 15, 16, 19, 20, 21, 22, 23, 24,
  25, 26, 28, 29, 30, 32, 34 (backfill runner heartbeat/lease/throttle semantics, migrate-primary
  Redis addressing, start.sh primary-migration bypass, audit "who", scanning + advisory bumps,
  follow-up reviews). Bundle them by surface into a few stories or a sweep story; do not mint
  21 stories. DW-32 and 2-7 are the two that gate the percentile story.

Prerequisite stories the spine makes explicit (foundation wave, mostly file-disjoint):
- BIN-146 fuzzy-merge gallery guard + properties.gallery_fingerprint + normalized-URL fingerprint
  (AD-15).
- `stages` literals → frozenset[EnrichmentTaskClass] scope with per-class skip keys and the
  dependency table in core; backfill scope derived from the routing map (AD-17).
- LMStudioClient parity: response_format json_object/json_schema, configurable max_tokens,
  generate() (AD-17; also the Strata spike pre-work).
- AppConfig sibling-file include for search_profiles / anchors (+ overlay version check) /
  attribute_vocabulary / facets; `travel_time` config section; anchors coordinate + .gitignore pin
  tests; fixture overlay for the suite (AD-16, AD-18).
- Migrations: property_attributes, property_facets, property_travel_times, property_fit_status,
  scraper_runs, property_listings cost columns (AD-14, AD-3, AD-18, AD-19, FR-37).
- The visual candidate SQL fragment shared by runner / rerun / coverage (AD-15).

Sequencing constraints to encode in epics.md (then verify with the real bmad-loop parser):
- Foundation before consumers: migrations + config loader before FR-39/FR-41/FR-35 stories.
- Percentile story ← AD-3 price-basis story (FR-31) + 2-7 + DW-32.
- src/api/schemas.py edits stay serial across stories (one shared contract surface).
- Strata spike before FR-39 text-extraction stories (PRD Q6 default: spike first, time-boxed).
- Nothing in the suite depends on OSRM, OTP, Ollama, Strata or the operator overlay (fakes).

Grounding sources (read before inventing stories):
- _bmad-output/planning-artifacts/prds/prd-imoveis-2026-10-07/{prd.md,addendum.md,change-signal.md}
- _bmad-output/planning-artifacts/architecture/architecture-imoveis-2026-07-23/ARCHITECTURE-SPINE.md
  and COMPANION-architecture-delta.md (cheat-sheet + prerequisite stories + known debt)
- _bmad-output/planning-artifacts/epics.md (current v0.13 plan of record — keep its story keys
  history, supersede the Epic 2 rows)
- _bmad-output/implementation-artifacts/sprint-status.yaml, deferred-work.md
- CLAUDE.md "Tracking" + "Epic refine / multi-story planning" (the wrap-up MUST include the
  Parallel work plan: waves, gates, start-here set, do-not-parallelize list)

Output: refreshed epics.md (planningTarget v0.14, carry-over epic + decision-engine epics, gates in
frontmatter `tracking:`), then run bmad-sprint-planning to regenerate sprint-status.yaml with
BMad-standard keys, and report the Parallel work plan.
```

## Open items carried for Felipe

- Strata decode throughput on the RX 7900 XT is unpublished (spike measures it; 50–60 tok/s is unverified).
- PRD Q4 (home-office definition), Q5 (compra-2028 preferences/geography), Q7 (agent write scope) stay decided-unless-overridden at their named stories.
- PRD §9 still lists Q1/Q2/Q3 as open; the answers above supersede it. Patch the PRD §9 in the epics pass or a quick `bmad-prd` update if you want the document to match.
