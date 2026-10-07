# Reconciliation — change-signal.md vs prd.md / addendum.md (2026-10-07)

Input of record: `change-signal.md`. Artifacts checked: `prd.md`, `addendum.md` (same folder). Tracker cross-check: `sprint-status.yaml` lines 195-226.

Status legend: **faithful** · **reinterpreted** (meaning narrowed/sharpened without a tag) · **missing** · **over-asserted** (PRD states as fact what the signal did not lock; needs `[ASSUMPTION]` / `[NOTE FOR PM]`).

## A. Primary job / framing

| # | Signal item | Where represented | Status | Note |
|---|---|---|---|---|
| A1 | Primary job → "decision engine for TWO concrete searches run by one operator" | prd §0, §1, §4.3 Theme; addendum Alternatives row 1 | faithful | Verbatim quote in §0. |
| A2 | AI agent (Claude Code) = main query client | prd §1, Glossary "Agent query client", FR-42 | faithful | Glossary widens to "or any HTTP client acting for the operator" — harmless extension. |
| A3 | React UI = secondary surface | prd §1, §5, §6.3 | faithful | |
| A4 | "one operator" | prd §2.2, §2.3 (Ana/Bruno retired); addendum Conflicts #5 | faithful | Persona retirement is a derivation; addendum labels it "decided by the change signal" — acceptable, slight over-attribution. |

## B. Search Profiles

| # | Signal item | Where represented | Status | Note |
|---|---|---|---|---|
| B1 | Two profiles, versioned in `configs/`, first-class product objects | Glossary "Search Profile", FR-41, NFR-2, §4.3 exit crit. 1 | faithful | |
| B2 | aluguel-2027: apartment, BH | FR-41 table (rent, apartment, BH) | faithful | |
| B3 | 2 bedrooms (one is a home office) | FR-41 "2 bedrooms (one usable as home office)"; FR-39 `home-office-capable`; §9 Q4 | faithful | "is a home office" read as "usable as"; definition correctly pushed to Q4. |
| B4 | >= 1 parking spot (hard) | FR-41 | faithful | |
| B5 | TOTAL monthly cost (rent + condo + IPTU) <= R$ 4.000 (hard) | FR-41, Glossary "Total Monthly Cost", FR-31 | faithful | |
| B6 | "prefer less" | FR-41 soft "lower total cost preferred" | faithful | |
| B7 | unfurnished | FR-41 hard constraint | faithful | Signal lists it without "desirable" → hard; consistent. |
| B8 | gym in building desirable | FR-41 soft | faithful | |
| B9 | split-AC allowed | FR-41 soft "acceptable (not required)" + `[ASSUMPTION]`; §11 | faithful | Properly tagged. |
| B10 | elevator desirable | FR-41 soft | faithful | |
| B11 | Move-in by Mar/2027 | FR-41 "move-in by 2027-03"; §1 | faithful | |
| B12 | compra-2028: 3–4 bedrooms, >= 2 parking spots | FR-41 table; UJ-6 | faithful | |
| B13 | purchase ~mid-2028 | FR-41 "purchase ~2028-06"; §1 "around mid-2028" | reinterpreted (minor) | "~mid-2028" sharpened to a month in the table. Fix: write "~mid-2028" or tag the month. |
| B14 | compra-2028 geography (NOT stated) | §1, FR-41, §9 Q5, §11 — all `[ASSUMPTION]` | faithful | Correctly tagged everywhere. |
| B15 | compra-2028 soft prefs (NOT stated) | FR-41 `[ASSUMPTION: none stated yet]`; Q5; §11 | faithful | Correctly tagged. |
| B16 | compra-2028 listing type "sale" (implied by "compra") | FR-41 | faithful | Reasonable; no "apartment" imposed (§1 says "larger home"). |

## C. Anchors / travel time

| # | Signal item | Where represented | Status | Note |
|---|---|---|---|---|
| C1 | igreja (Palmares) | Glossary "Anchor"; UJ-5 | faithful | |
| C2 | casa da Nala (Santo Antônio) | Glossary; UJ-5 | faithful | |
| C3 | casa da mãe (Planalto) | Glossary | faithful | |
| C4 | Centro | Glossary | faithful | |
| C5 | aulas de música (walking distance from current home) | Glossary; FR-35 consequence + `[ASSUMPTION]` walk-mode modelling; §6.5; §11 | faithful | Walk mode is an extension beyond "car and transit", properly tagged. |
| C6 | Anchors are FR-35 input | FR-35 header/body; §6.3 | faithful | |
| C7 | Minutes by car and by transit, never km | Glossary "Travel time", FR-35 consequences, §5 non-goal, §6.5, SM-C4 | faithful | |

## D. Hardware / NFR-1

| # | Signal item | Where represented | Status | Note |
|---|---|---|---|---|
| D1 | Hardware stays AMD RX 7900 XT 20 GB + Ollama | §1, NFR-1, §6.4 | faithful | |
| D2 | Local-first invariant (NFR-1) holds | §1, §5, NFR-1, SM-7 | faithful | |

## E. Strata

| # | Signal item | Where represented | Status | Note |
|---|---|---|---|---|
| E1 | Strata = CANDIDATE TEXT BACKEND, settled by spike, not an FR | Glossary "Spike", §5, §6.4, addendum Alternatives row 4 | faithful | |
| E2 | github.com/Niko1221/Strata | §10; addendum §Strata | faithful | |
| E3 | Qwen3.8-Flash-Next, 125B MoE, IQ2/Q2 | §6.4; addendum | faithful | |
| E4 | Windows HIP engine prebuilt since 0.1.34 | addendum §Strata only | faithful | Not in prd.md body — acceptable (technical depth). |
| E5 | `/v1/chat/completions`, `response_format` json_object/json_schema = schema prompting + server validation, not constrained decoding | §6.4 (abbrev.); addendum (full incl. "not constrained decoding") | faithful | |
| E6 | ~50–60 tok/s output on RDNA | addendum §Strata only | faithful | Not in §6.4 Bounds; optional to add since it feeds the s/Property criterion. |
| E7 | One request at a time by default, `"parallel": 2` opt-in | §6.4 Bounds; addendum | faithful | |
| E8 | Vision on AMD Linux-only via CPU encoder (~3 s/photo @ 300 tok, 8 cores), unavailable on Windows | §6.4 Bounds (no numbers); §4.4(b); addendum §Photo pipeline (numbers) | faithful | |
| E9 | No embeddings endpoint (bge-m3 stays on Ollama, sharing GPU) | §6.4 Bounds; addendum §Strata + mechanics #3 | faithful | |
| E10 | >= 32 GB RAM (64 rec., loads 35–55 GB), ~80 GB NVMe | §6.4 Bounds; addendum | faithful | |
| E11 | AMD path "not validated" for images and answer quality | §6.4 Bounds; addendum | faithful | |
| E12 | Config-only integration via existing `lmstudio` backend + `enrichment_routing` | §6.4 Integration constraint; addendum mechanics #1 | faithful | |
| E13 | Route sentiment / attributes / deal_verdict → Strata; visual + embedding stay Ollama | §6.4 Question; addendum mechanics #1 | faithful | §6.4 adds "/fit summary" to the Strata text route — FR-40's new text class is a PM derivation, not a signal item; harmless but untagged. |
| E14 | Exit criteria: A/B vs qwen2.5vl:7b, ~50 listings, attribute accuracy, JSON validity, s/Property with Ollama co-resident | §6.4 Exit criteria; §4.3 exit crit. 7; addendum #4 | faithful | Addendum adds "hand labels", "first-try and after retry", "BH" — elaborations. |
| E15 | Using `scripts/dev/ab_gemini_vs_ollama.py` adapted | §6.4; §10; addendum #4 | faithful | |
| E16 | Pass ⇒ text route for FR-39/FR-40 | §6.4 Pass clause | faithful | |
| E17 | Pass ⇒ local replacement for Gemma cloud backfill on text classes | §6.4 Pass clause; addendum #5 | over-asserted (minor) | Addendum #5 adds "Gemma stays available as the quota-bounded assist" — not in signal, which says "replacement". Fix: tag `[ASSUMPTION]` or drop the parenthetical. |
| E18 | Fail consequence (NOT stated by signal) | §6.4 "Fail/defer ⇒ text classes stay on Ollama; FR-39/FR-40 ship on qwen2.5vl:7b with accuracy thresholds re-baselined" | over-asserted (minor) | Reasonable default but asserted as decided. Fix: tag `[ASSUMPTION]` (thresholds already tagged in FR-39). |

## F. Epic 2 / v0.14 wave

| # | Signal item | Where represented | Status | Note |
|---|---|---|---|---|
| F1 | v0.13 Epic 2 NOT re-litigated; fold status in as baseline/in-flight | §0, §4.2 table, §6.2; addendum Alternatives row 8, Conflicts #2 | faithful | |
| F2 | "FR-30 done" | §4.2 Status note + `[NOTE FOR PM]`; addendum Conflicts #2 | faithful | PRD records tracker truth (2-1/2-2 backlog; BIN-84 column exists) — verified against sprint-status.yaml:221-222. Correctly tagged rather than silently overriding the signal. |
| F3 | FR-32 and 2-1..2-5 still backlog | §4.2 (s2.1–s2.5 backlog, s2.6 done, s2.7 awaiting-operator); §6.2 | faithful | Matches sprint-status.yaml:205-225. |
| F4 | v0.14 wave (FR-33–FR-38) kept but RE-SCOPED | §0, §4.3 Description | faithful | |
| F5 | FR-35 promoted and redefined | FR-35 header "(promoted, redefined)"; addendum Conflicts #3 | faithful | |
| F6 | FR-36 promoted and redefined | FR-36 header "(promoted, redefined)"; addendum Conflicts #4 | faithful | |
| F7 | FR-33/34/37/38 stay as planned | §4.3 "FR-33, FR-34, FR-37, FR-38 — unchanged"; exit crit. 6; §6.3 | faithful | "FR-38 is UI-only and lowest priority in the wave" is a derivation from UI deprioritization, untagged — minor; leave priority to epics or tag. |
| F8 | Epic 2 ordering vs v0.14 (NOT stated) | §4.2 `[NOTE FOR PM]`; §9 Q3 | faithful | Properly raised as a question. |

## G. UI

| # | Signal item | Where represented | Status | Note |
|---|---|---|---|---|
| G1 | UI work deprioritized; operator reads agent dossiers + opens listing links | §1, §2.1, UJ-5 | faithful | |
| G2 | Compare stays minimal | §5, §6.5 | faithful | |
| G3 | No new screens unless an FR cannot be exercised otherwise | §1, §5, §6.3 last bullet | faithful | |

## H. Output requirements

| # | Signal item | Where represented | Status | Note |
|---|---|---|---|---|
| H1 | New versioned PRD folder under `prds/` | `prd-imoveis-2026-10-07/prd.md` (frontmatter `supersedes`) | faithful | |
| H2 | Addendum | `prd-imoveis-2026-10-07/addendum.md` | faithful | |
| H3 | Status final | frontmatter `status: draft` present | faithful (pending) | Field exists; flip to `final` at close. |
| H4 | FR numbering continues from FR-38 | §4 intro; FR-39–FR-42 | faithful | |
| H5 | Hand-off: bmad-architecture (attribute/photo schema) then bmad-create-epics-and-stories for v0.14 | §6.3 "Architecture inputs required before stories" | faithful | Chat-level instruction; PRD encodes the ordering rationale. |
| H6 | Grounding sources read | addendum §Grounding snapshot (file:line cites), §10 References | faithful | All listed sources cited. |
| H7 | Signal file `NEXT-bmad-prd-update-2026-10-07.md` absent; pasted intent is signal of record | §11 last bullet; change-signal.md header | faithful | |

## I. Items the PRD asserts that the signal did NOT lock

| # | PRD assertion | Where | Status | Note / fix |
|---|---|---|---|---|
| I1 | FR-31 un-deferral | §0 ("FR-31 returns from the debt ledger"), §4.2 ("It is un-deferred in this version"), §6.3 Foundation — untagged; FR-31 body `[NOTE FOR PM]` + §9 Q1 + addendum Conflicts #1 — tagged | over-asserted (partially tagged) | Decision is correctly surfaced for confirmation in FR-31/Q1, but §0/§4.2/§6.3 read as settled. Fix: add "(proposed — §9 Q1)" at §0 and §4.2, or tag `[NOTE FOR PM]` inline. |
| I2 | compra-2028 is BH | §1, FR-41, §9 Q5, §11 | faithful | Tagged `[ASSUMPTION]` at every occurrence. |
| I3 | Agent transport = existing REST API + API key | FR-42 `[ASSUMPTION]` + §11 — tagged; but Glossary "API-key-gated interface", §2.1 "the agent talks to a local API", NFR-3 "same API key; no new auth surface", §6.3 "read endpoints + contract tests + docs/api.md agent section" — untagged | over-asserted (partially tagged) | Fix: cross-reference the FR-42 assumption from Glossary/NFR-3, or soften to "the FR-42 interface". Addendum transport notes are fine as addendum. |
| I4 | Agent write scope = star/unstar + recheck only | FR-42 body (stated as fact); §9 Q7 (open, "default here") | over-asserted (minor) | Fix: tag the FR-42 sentence `[ASSUMPTION — §9 Q7]`. |
| I5 | FR-40 "fit summary generated by a profile-aware text class alongside deal_verdict" | FR-40; §6.4 routes it to Strata | over-asserted (minor) | New text class is a PM design choice, not a signal item. Acceptable as FR definition; consider `[ASSUMPTION]` or leave to architecture. |
| I6 | FR-39 Attribute list includes bathrooms, suites, floor, pets | FR-39 | over-asserted (minor, internal) | FR-39 says "every Attribute any Search Profile references" and declares non-referenced Attributes out of scope, yet neither profile references bathrooms/suites/floor/pets. Fix: trim to profile-referenced set or state they are kept because scrapers already supply them. |
| I7 | FR-39 85% / 100% thresholds; FR-42 ≤ 2 s / ≤ 5 s; SM-1–SM-7 numbers | FR-39, FR-42, §7, §11 | faithful | Tagged `[ASSUMPTION]`. §4.3 exit crit. 2 "≥ 90%" and SM-3 share one untagged number — minor. |
| I8 | `aulas de música` as Anchor + walk mode | FR-35, §6.5, §11 | faithful | Tagged. |
| I9 | "Gemma stays available" after Strata pass | addendum #5 | over-asserted (minor) | See E17. |
| I10 | Fail/defer outcome of the spike | §6.4 | over-asserted (minor) | See E18. |

## Totals

Items checked: 62 (A4 + B16 + C7 + D2 + E18 + F8 + G3 + H7 — I overlaps counted once).
- faithful: 55
- reinterpreted: 1 (B13)
- missing: 0
- over-asserted: 6 distinct (I1, I3, I4, I5/E13, I6, E17/E18) — all minor; none contradicts the signal.
