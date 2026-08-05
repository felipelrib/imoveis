---
title: Sprint Change Proposal — Planning-artifact drift after v0.6–v0.11 + untracked wave
date: 2026-08-05
workflow: bmad-correct-course
mode: batch
status: approved-and-executed (2026-08-05; approved by Felipe, session-scope items applied)
trigger: >
  Navigate significant changes. May recommend update PRD, redo architecture,
  sprint planning, or correct epics and stories.
---

# Sprint Change Proposal — 2026-08-05

## 1. Issue Summary

**Problem statement:** The BMad planning artifacts (PRD, architecture spine, epics, sprint-status) were written 2026-07-23 for the v0.5 wave and have not been updated since 2026-07-27. Since then the project delivered **six additional milestones (v0.6–v0.11, all 100% Done)** plus a **milestone-less post-v0.11 wave (~BIN-241…BIN-272, closed through 2026-08-03)**. The backlog is now empty: Linear shows **zero open issues** in the project. Every planning document is therefore describing a project state roughly six waves behind reality, and there is no planned next wave to execute.

**Discovery context:** Surfaced during a correct-course review on 2026-08-05, immediately after regenerating project knowledge (`docs/` document-project scan) and `project-context.md`, which made the artifact-vs-reality gap explicit.

**Evidence:**

- Linear (project `Imoveis — Deal Tracker`): milestones v0.1–v0.11 all at 100% progress; `list_issues` returns **no** started and **no** backlog issues.
- Recent Done tickets BIN-241…BIN-272 (descriptions enrichment repair, Gemini/Gemma cloud A/B + resumable free-tier backfill runner, FlareSolverr Cloudflare bypass generalization, PostGIS 15-3.3→17-3.5, maplibre-gl 5→6, Dependabot/CI fixes) carry **no project milestone**, breaking the "every wave gets a `v0.N` milestone" convention in CLAUDE.md.
- `sprint-status.yaml` (`last_updated: 2026-07-27`) tracks epics 1–6 and 8 only — **epic 7 (v0.7 dual listing-type scoring) is absent**, and nothing after epic 8 exists in the file despite v0.9–v0.11 having shipped.
- PRD FR-18…FR-22 ("v0.5 planned") and epics.md Epics 1–5 are all delivered; FR-23 (ZapImóveis) is listed as "deferred / not committed" but `src/adapters/scrapers/zapimoveis.py` shipped (BIN-127).
- Architecture spine stack table asserts PostGIS 15-3.3 + pgvector, FastAPI/Celery "unpinned in requirements.txt", React-only stack facts that are now false (PostGIS 17-3.5 via BIN-272; full pip-compile lockfile via BIN-138; maplibre-gl 6 via BIN-271).
- PRD §1/§2.2 & NFR-8 state BH-first geography, but SP/Campinas scrape coverage shipped (BIN-113); NFR-1 "no required cloud AI" now coexists with an optional Gemini/Gemma **cloud** enrichment path (BIN-242, BIN-248, BIN-267…269) — optional, but an undocumented posture change.

**Issue type:** Planning-artifact drift / strategic checkpoint — not a technical failure. Nothing shipped is being questioned; the *plans* no longer describe the product, and no next wave is defined.

## 2. Impact Analysis

### Epic impact

- **Current epics (epics.md Epics 1–5 / Linear BIN-19…23):** fully delivered and closed. No modification needed; the document should be **marked delivered/archived**, not edited into a new plan.
- **Undocumented epics:** v0.6 (BIN-85), v0.7, v0.8 (BIN-63), v0.9 (BIN-104), v0.10, v0.11 waves have Linear history and feature docs but **no corresponding BMad epic artifacts** (only sprint-status entries for 6 and 8). Accept as historical record in Linear + `docs/features/`; do not retro-write epic files.
- **Future epics:** none exist anywhere. This is the actionable gap — the next wave (v0.12) has no PRD themes, no epics, no stories.
- **Sequencing impact:** nothing to resequence today; sequencing questions move into the next PRD/epics cycle.

### Artifact conflicts

| Artifact | Conflict | Severity |
|---|---|---|
| PRD (`prds/prd-imoveis-2026-07-23/`) | Scope §4.6/§6.2 ("v0.5 planning"), geography (BH-first vs shipped SP/Campinas), FR-23 "deferred" vs shipped Zap scraper, NFR-1 posture vs optional cloud-Gemma backfill, §9 open questions all since answered by shipped code | High — PRD no longer states product truth or next intent |
| Architecture spine | Stack table stale (PostGIS 17-3.5, maplibre 6, pinned deps); AD-7 topology missing FlareSolverr service + optional cloud-AI assist; AD-4/AD-10 don't mention the sanctioned CLI backfill runner path; "Deferred: pinning deps" is done | Medium — invariants AD-1…AD-12 remain sound; facts around them drifted |
| Epics (`epics.md`) | Entirely delivered; presents as active plan | Medium — misleads any fresh planning session |
| `sprint-status.yaml` | Missing epic-7; ends at epic-8; `last_updated` 2026-07-27 | Medium |
| UI/UX artifacts | None exist | N/A |
| Secondary artifacts | `docs/` knowledge set + `project-context.md` regenerated **today** (2026-08-05) and current; human docs (`architecture.md`, `api.md`) already updated per-feature; Linear milestone hygiene broken for post-v0.11 tickets | Low (one hygiene fix) |

### Technical impact

None on shipped code. All impact is on planning/tracking surfaces.

## 3. Recommended Approach

**Selected path: MVP/Scope Review → full re-plan cycle (checklist Option 3), with two direct micro-adjustments (Option 1) for record hygiene.** Rollback (Option 2) is not applicable — nothing needs reverting.

Rationale: the original PRD MVP **and** its Beyond-MVP scope are complete. Editing stories or patching epics (pure Option 1) cannot fix "there is no plan"; the artifacts need a version-stamped refresh so the next wave starts from truth. The BMad-standard route is a fresh planning cycle: PRD update → architecture update → epics & stories → sprint planning, each in a **fresh session** per repo convention, with Linear sync through the planning bridge. Effort: Medium (mostly document work). Risk: Low — shipped product untouched. Timeline impact: planning-only; no delivery in flight to disturb.

**Decision required from Felipe inside the PRD update (not invented here):** what v0.12 should be — candidate themes surfaced by this analysis include productizing the cloud/local AI-enrichment split (Gemma backfill runner → sanctioned architecture), multi-city productization (SP/Campinas beyond "config allows it"), alert/digest channel expansion, and any new deal-intelligence features. Also decide the pending **BMad-SoR vs Linear-SoR harness pivot** before generating the next epics, so the new artifacts are born under the right regime.

## 4. Detailed Change Proposals

### 4.1 PRD — run `bmad-prd` (update intent) in a fresh session

- **Section 0/frontmatter** — OLD: `status: final`, "retrofits v0.1–v0.4 … defines what v0.5 should prioritize". NEW: supersede with an updated PRD (new dated shard dir) whose baseline is **v0.1–v0.11 + post-v0.11 wave shipped**, and whose planning target is **v0.12**.
  *Rationale: the "next phase" the PRD defines has shipped in its entirety.*
- **§1 Vision / §2.2 / NFR-8** — OLD: "Geographic focus (current): Belo Horizonte / MG". NEW: BH/MG primary + SP/Campinas scrape coverage shipped (BIN-113); state whether multi-city is now product intent or still opportunistic.
- **§4.6 + §6** — OLD: FR-18…FR-22 "planned / in scope for v0.5". NEW: fold into shipped baseline (§6.1) alongside new baseline capabilities: neighbourhood quality profiles (v0.6), dual listing-type scoring (v0.7), product i18n pt-BR (v0.8), follow-up sweep (v0.9), debt remediation (v0.10), frontend TS migration (v0.11), listing-description enrichment + Cloudflare bypass + cloud-backfill tooling (post-v0.11).
- **FR-23** — OLD: "deferred, not committed". NEW: shipped (ZapImóveis scraper, BIN-127) — move into baseline.
- **NFR-1** — OLD: "no required cloud AI". NEW: keep local-first as the default posture, and **document the optional cloud-assist exception** (Gemini/Gemma free-tier batch backfill, quota-bounded, operator-triggered) so the next architecture pass can bind it.
- **§9 Open Questions** — OLD: five v0.5-era questions. NEW: mark answered-by-shipping (auth = API-key gate; digest = shipped notifier registry; polygons = GeoJSON path shipped; Zap = shipped) and pose the v0.12 intake questions (next wave themes; multi-city; cloud-assist productization; SoR pivot).

### 4.2 Architecture — run `bmad-architecture` (update intent) in a fresh session; **no redo**

- **Stack table** — OLD: PostGIS 15-3.3 + pgvector v0.8.0, "FastAPI/Celery unpinned (rebuilds may float)". NEW: PostGIS 17-3.5 (BIN-272), maplibre-gl 6 (BIN-271), full pip-compile lockfile (BIN-138) — remove the "unpinned" caveats.
- **AD-7 (topology)** — OLD: Compose = Postgres/Redis/API/workers/beat + host AI. NEW: add `flaresolverr` service (+`ollama_init`) as ratified topology; add one sentence bounding the **optional cloud AI assist** path (batch backfill only, quota-bounded, never required for core enrichment) — either as an AD-7 amendment or a new AD-13.
- **AD-4 / AD-10 note** — NEW: name the resumable backfill runner (`core/backfill_runner.py` + `scripts/dev` CLI) as a sanctioned second *driver* of enrichment that still writes through the single pipeline authority — so it stops looking like an invariant violation.
- **Deferred table** — OLD: "Pinning all Python deps in requirements.txt | Hygiene". NEW: remove (done). Verify AD-1 core→ORM debt status while in there (dedupe leak burn-down was planned in v0.10).

### 4.3 Epics — mark delivered, then regenerate

- **epics.md frontmatter/banner** — NEW: add `delivery-status: delivered 2026-07-27 (Epics 1–5 = BIN-19…23 all Done)` note at top so no future session mistakes it for an active plan. Content otherwise untouched (historical record).
- After the updated PRD + architecture land: run `bmad-create-epics-and-stories` (fresh session) for v0.12, then sync to Linear as a `v0.12` milestone + parent epic(s) with children, per the planning bridge.

### 4.4 Sprint status — correct now, regenerate later

- **`sprint-status.yaml`** — NEW (post-approval edit): add `epic-7: done # v0.7 dual listing-type scoring — delivered via Linear (BIN-96 area), never tracked in this file` for the record gap, bump `last_updated`, and add a header note that epics 1–8 are all delivered and the file awaits regeneration by `bmad-sprint-planning` after the v0.12 epics exist.

### 4.5 Linear hygiene — milestone backfill (single micro-ticket)

- Post-v0.11 Done tickets (~BIN-241…BIN-272) have **no milestone**. NEW: create milestone `v0.12 — Description enrichment & platform upgrades` *(or fold into a retroactive naming Felipe prefers)*, following the milestone description standard (prose + Theme + Exit criteria), assign those tickets to it, and mark it complete — restoring the "every wave is a `v0.N`" invariant. Note: this makes the *next* planned wave `v0.13` (or renumber the backfill as `v0.12a` — Felipe's call in the PRD session).

## 5. Implementation Handoff

**Scope classification: Major** — fundamental replan (new PRD version + architecture update + new epics), plus two Minor record fixes.

| Work | Route | Deliverable |
|---|---|---|
| PRD update (v0.12 intake) | PM (`bmad-prd`, fresh session) | New dated PRD shard set superseding 2026-07-23 |
| Architecture update | Architect (`bmad-architecture`, fresh session, after PRD) | Spine stack/AD-7 refresh (+AD-13 if chosen) |
| Epics & stories for v0.12 | PM/PO (`bmad-create-epics-and-stories`, fresh session) | epics doc + Linear sync (milestone, parent epic, children, parallel work plan) |
| Sprint plan regeneration | `bmad-sprint-planning` (fresh session) | New `sprint-status.yaml` |
| epics.md delivered banner + sprint-status epic-7 record fix | Developer agent (this or any session, post-approval) | Two small edits |
| Linear milestone backfill for BIN-241…272 | Developer agent via Linear MCP (post-approval) | Completed `v0.12` backfill milestone |

**Success criteria:** every planning artifact states the shipped baseline truthfully; a v0.12/v0.13 wave exists in PRD→epics→Linear→sprint-status with no orphan tickets; milestone convention restored; SoR-pivot decision recorded before epic generation.

## 6. Checklist Record

- §1 Trigger & context: 1.1 [x] (no single triggering story — trigger is backlog exhaustion + artifact drift; nearest stories BIN-241…272) · 1.2 [x] · 1.3 [x]
- §2 Epic impact: 2.1 [x] · 2.2 [x] · 2.3 [x] · 2.4 [x] (new epics needed; none invalidated) · 2.5 [x] (no resequencing)
- §3 Artifacts: 3.1 [x] PRD · 3.2 [x] Architecture · 3.3 [N/A] UX (none) · 3.4 [x] Secondary
- §4 Path: 4.1 viable-partial (micro-fixes only) · 4.2 not viable (nothing to roll back) · 4.3 **selected** · 4.4 [x]
- §5 Proposal components: 5.1–5.5 [x]
- §6 Final review: 6.1 [x] · 6.2 [x] · 6.3 [x] approved by Felipe 2026-08-05 · 6.4 [x] sprint-status.yaml updated (epic-7 record, delivered note) · 6.5 [x] handoff confirmed (see §5)

## 7. Execution Record (2026-08-05, post-approval)

- Linear: created retroactive milestone **v0.12 — Stabilization, docs backfill & description enrichment** (`0bb409a1-f7d4-437b-8a67-64811c8152ad`) and assigned all **39** orphaned Done tickets (BIN-96, BIN-166–188, BIN-241–249, BIN-267–272). Note: the orphan census found 24 more tickets than the proposal's original ~15 estimate (the 2026-07-30 stabilization/docs batch); all were folded into the one retroactive milestone. Next planned wave is therefore **v0.13** unless renumbered in the PRD session.
- `epics.md`: delivered-status banner added (frontmatter `delivery-status`).
- `sprint-status.yaml`: epic-7 gap recorded as done; delivered/awaiting-regeneration note; `last_updated` bumped.
- Handed off (fresh sessions, in order): `bmad-prd` update → `bmad-architecture` update → `bmad-create-epics-and-stories` → `bmad-sprint-planning`.
