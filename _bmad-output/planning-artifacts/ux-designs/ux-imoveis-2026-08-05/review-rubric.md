# Spine Pair Review — imoveis

Reviewed: `DESIGN.md` + `EXPERIENCE.md` (ux-imoveis-2026-08-05), against `.working/source-extract.md`, `.memlog.md`, the design-md spec, and the five reference examples. Severity = downstream impact on a consumer (architecture / story-dev) source-extracting from this pair.

## Overall verdict

A well-crafted pair with an unusually disciplined honesty spine (absence states, banned patterns, verdict-in-words) and a clean, fully-resolving token layer. The gaps cluster in three places: two source requirements (FR-15 semantic search, FR-30's *filter* half) are neither designed nor listed as deliberate non-designs; the Admin/modal component vocabulary that the in-flight v0.13 UI stories (s1.6, s2.2) will consume has behavioral coverage but almost no visual spec; and the visual artifacts in `.working/` are not linked from either spine (no promotion, no spines-win-on-conflict clause). Fixable in one editing pass — nothing structural is wrong.

## 1. Flow coverage — adequate

Checked every UJ/requirement surface in source-extract §1–§3 against Key Flows. J1–J4 all have a named protagonist (Felipe, in modes), numbered steps, and a bolded climax. UJ-1 (evening check → modal → star, cross-platform climax) maps to J1 with the `2 fontes` climax preserved and sharpened into a negotiation lever. UJ-3 + UJ-4 map to J3 (anomaly diagnosis + backfill glance). J4 is new UX-driven scope, well-motivated. "Comparar has no journey by design" is stated twice (IA table row + *Deliberate non-designs* footer) — the recorded decision is properly written down, not merely absent.

### Findings

- **high** FR-15 semantic search (`GET /properties?q=`, a named surface in source-extract §2) appears nowhere in EXPERIENCE.md — not in the IA table, not in any flow, and not in the *Deliberate non-designs* footer. The memlog records the decision ("nice-to-have, pt-BR") but the spine doesn't carry it, so a consumer doing a readiness check reads it as an unexplained omission. *Fix:* one line in *Deliberate non-designs* ("semantic search: existing surface kept as-is, pt-BR queries, no redesign this pass") or an IA row.
- **medium** No flow carries an explicit failure path (both examples label one per flow). J1's own anti-climax — `Verificar disponibilidade` comes back *gone* instead of fresh — is the flow's stated enemy yet its outcome is undesigned (does the card flip to the gone treatment? toast? modal note?). J2's "listing already gone at click-through" is likewise untreated. *Fix:* add a `Failure:` line to J1 and J2; the gone-listing State Pattern gives you most of the treatment already.
- **low** UJ-2's price-drop alert journey (alert → price-history chart confirmation) is folded away: J2 covers the alert-interrupt shape but with a new-match, and no flow ends on the chart. The Notifications section carries the threshold rule, so only the chart-confirmation beat is lost. *Fix:* one sentence in J2 or Notifications noting the drop-alert variant lands on the modal's price-history chart.
- **low** Flows are renamed J1–J4 with no mapping to source UJ-1..4 / FR ids (other sections cite FRs well). *Fix:* a parenthetical per flow, e.g. "J1 (absorbs UJ-1)".

## 2. Token completeness — adequate

Extracted every frontmatter token and every `{path.to.token}` reference in both files. All 20 color tokens carry hexes (scrim is 8-digit, fine). All `{colors.*}`, `{typography.*}`, `{rounded.*}`, `{spacing.*}` references in DESIGN.md prose and component objects resolve to frontmatter. All four EXPERIENCE.md token references (`{colors.favourite-star}`, `{typography.verdict-label}`, `{colors.pending}`, `{colors.gone}`) resolve to DESIGN.md by name. No dangling references anywhere — mechanically clean.

### Findings

- **medium** No contrast targets are stated anywhere in DESIGN.md, while EXPERIENCE.md's Accessibility Floor claims "WCAG AA text contrast … (`DESIGN.md` token pairs chosen for it)" — a claim the referenced file never backs. The risky pairs are exactly the load-bearing ones: `text-muted` #82859a and `verdict-market` #8b8e99 at 11–12.5px on `surface-card`, and `text-secondary` on `{colors.scrim}` over arbitrary photos. *Fix:* add a short contrast table (pair → ratio → AA verdict) to DESIGN.md Colors; state a minimum for on-photo scrim text.
- **medium** `favourite-star` and `health-warn` share hex #d9b35f while the Do's and Don'ts table rules "Gold star = favourite, and nothing else / health warn is its own amber role." The frontmatter comment even blesses the sharing ("gold = star = warn"). The token layer and the hard rule contradict each other. *Fix:* either give health-warn its own amber hex, or rewrite the Do/Don't row to say the *contexts* never overlap (strip dot vs card star) rather than claiming distinct inks.
- **low** Several component values are prose, not resolvable values: `percentile-badge.background: 'price-drop at ~12% over card'`, `border: '1px solid price-drop at ~35%'`, `health-chip.background: 'surface-card blended toward background'`, `since-panel.background: '{colors.surface-elevated} toward {colors.surface-card}'`. A human resolves them; a token resolver doesn't. *Fix:* mint alpha-variant tokens (e.g. `price-drop-tint-12`) or state the computed hex inline.
- **low** `since-panel` body spec says "uppercase label in warm accent" — "warm accent" is not a token; the only `accent` is cool azure. Ambiguous which ink is meant (probably `favourite-star` gold). *Fix:* name the token.

## 3. Component coverage — thin

Cross-referenced every component name used anywhere in either file against DESIGN.md.Components (visual) and EXPERIENCE.md.Component Patterns (behavioral). The Painel/grid vocabulary is genuinely strong — property card, verdict label, percentile badge, price-drop badge, sources badge, freshness stamp, star, filter chip, health chip, pending tag, map point, POI pin, since-panel all have real visual rules, and the covered behavioral rows carry real contracts (viewport persistence, per-type price memory, optimistic star). The misses are systematic, not scattered: DESIGN.md.Components covers only the front door, while EXPERIENCE.md sends consumers to Admin and modal internals that have no visual spec at all.

### Findings

- **high** FR-30 is "percentile on card/modal, **filterable**" (source-extract §2/§3; open question #6 explicitly flagged "the filter control's form"). The spine designs badge + modal sentence and the cheap-direction copy rule, but the percentile *filter control* appears nowhere — not in the filter-bar row, not deferred. Story s2.2 will have to invent it. *Fix:* add it to the Component Patterns filter-bar row (form + how it composes with the 2-line ceiling) or explicitly defer it in *Deliberate non-designs*.
- **high** The price-history chart — the modal's centerpiece in J1 step 3 and UJ-2's confirmation beat — has no spec in either spine: no visual rules (line/axis/ink on the dark ground, drop-marker treatment, and the system-wide dataviz posture given "no progress bars") and no behavioral row (range, per-platform series?, hover). *Fix:* one DESIGN.md.Components entry + one Component Patterns row.
- **high** Admin components consumed by in-flight story **s1.6** — the backfill card (state, budget, throughput, day-scale ETA, start/pause/resume, collision warning line) and the run-history table — have good behavioral coverage in Operator Observability but zero DESIGN.md visual spec ("admin tables" appears only in the Typography prose). The very next UI story ships against this contract. *Fix:* add `backfill-card` and `run-history-table` (and the toast, also unspecced) to DESIGN.md.Components, even briefly.
- **medium** Behavioral gaps on named interactions: dismiss/hide is "recoverable" — recoverable *where* (a filter? an Admin list?) is undefined; the `Verificar disponibilidade` button has no in-progress/result behavior; the since-last-visit panel has no reset semantics (what counts as a "visit"? when do the counts zero?) — load-bearing for its whole purpose. *Fix:* one Component Patterns row each for since-panel and recheck; one clause for dismiss recovery.
- **medium** POI anchors are central to J1/J4 and the map spec, but POI *management* (how Igreja/Casa dos pais get created/edited, and where) is undesigned and unflagged. *Fix:* defer explicitly or add a line (e.g. "POI CRUD lives in Admin, minimal form").
- **low** Saved-search row and Alertas panel (s2.4 consumers) have behavior but no DESIGN visual entry (toggle, bell badge, alert list row). *Fix:* small Components entries or an explicit "inherits chip/panel rules" note.

## 4. State coverage — adequate

Walked all seven IA surfaces against the State Patterns table. The honesty states — pending enrichment, suppressed percentile, absent ETA, gone, staleness, degraded platform, anomaly-with-reason, backfill-visible — are the best part of the whole pair and directly close source-extract open question #9. What's missing is the boring generic layer both examples carry.

### Findings

- **medium** No cold-load state for the Painel. Blocking spinners over the grid are banned (correctly), but nothing says what loading *is* — skeleton cards? empty grid? Both reference examples specify cold load first. *Fix:* one State Patterns row (e.g. skeleton cards matching the grid layout, no spinner).
- **medium** No empty states: grid with zero filter matches, empty Favoritos/shortlist, empty Buscas salvas, empty Alertas, first-ever-visit since-panel. A pt-BR empty sentence per surface is cheap and on-voice. *Fix:* one row covering the empty family with per-surface copy.
- **medium** No grid-fetch-failure state. "Errors never block the grid" governs *action* errors; if the properties request itself fails on cold load there is nothing to not-block. *Fix:* one row (toast + retained last-good data, or explicit failure copy).
- **low** Map tile failure (maps require network; offline tiles are a stated non-goal) and recheck-in-progress on the modal are untreated. *Fix:* fold into the failure rows above.

## 5. Visual reference coverage — thin

Inventory: `.working/` holds `source-extract.md`, four `direction-*.html` explorations, and `color-themes-1/2.html` (the picked Meia-noite palette lives in `color-themes-2.html` per memlog). `imports/` is empty; `mockups/` and `wireframes/` do not exist — **promotion has not happened**. Neither spine links a single visual artifact, and neither states the spines-win-on-conflict rule (both experience examples model the `→ Composition reference: … Spine wins on conflict.` line).

### Findings

- **medium** No inline visual references anywhere in either spine. The picked-direction mock (Meia-noite variation in `color-themes-2.html`) is the provenance for all 19 hexes and the card anatomy, but a consumer of DESIGN.md cannot find it. *Fix:* promote the winning variation out of `.working/` (e.g. `mockups/`), then link it from DESIGN.md Brand & Style and EXPERIENCE.md IA.
- **medium** Spines-win-on-conflict is stated nowhere. Once mocks are linked, a consumer needs the precedence rule exactly once. *Fix:* append "Spine wins on conflict." to the first composition-reference link.
- **low** The four rejected `direction-*.html` explorations are indistinguishable from the winner inside `.working/` — a future session could source-extract from a rejected direction. *Fix:* promotion of the winner (above) resolves this implicitly.

## 6. Bloat & overspecification — strong

DESIGN.md prose is editorial by license and stays disciplined — every paragraph carries a rule, no source restatement padding. EXPERIENCE.md is table-first where it should be; Foundation compresses AD-8/AD-11/AD-12 into contract anchors rather than restating the architecture.

### Findings

- **low** Mild editorial voice leaks into EXPERIENCE.md prose ("Honest absence is the system's spine", "The workshop bench, split in two") — harmless at this dose, but the rubric places that voice in DESIGN.md. *Fix:* optional; trim if the pair gets another pass.

## 7. Inheritance discipline — adequate

Glossary terms (Property/Listing/Platform capitalization, deal verdict, stat score, cohort = neighbourhood × listing type, degraded platform set, circuit-broken, skip-unchanged) are mirrored correctly and used with source meaning. FR/AD/NFR/BIN citations are dense and accurate (BIN-77 price_type, AD-13 backfill visibility, FR-27 invisible degradation). The NFR-7 pt-BR override is handled exactly right — flagged `[NOTE FOR PRD]` with the engineering rule kept intact — as are the five other `[NOTE FOR PRD]` scope flags and the `[ASSUMPTION]` markers on pending-veto patterns. Verdict wordings and pt-BR strings are identical across both spines.

### Findings

- **medium** **Watchlist** vs **Favourites**: the sources' glossary treats Watchlist (price-drop alert set, FR-16, UJ-2) and Favourite (starred shortlist) as distinct terms. EXPERIENCE.md builds Favoritos thoroughly but uses "watchlist" only once ("per-watchlist drop-threshold … undecided") without ever mapping the two — is starring a Property what puts it on the watchlist, or are they separate sets? Downstream story-dev for FR-16 has to guess the relation. *Fix:* one Foundation or Notifications sentence fixing the mapping (e.g. "starred = watched; there is no separate watchlist").
- **low** "Score-coloured grid" (the sources' only visual term) survives in the IA table while the design deliberately bans colour-filled score areas in favour of worded verdicts with underlines. Consistent once you read both files, but a consumer of the IA table alone could infer painted cards. *Fix:* "verdict-coloured" or a parenthetical.
- **low** FR-29's *per-signal-type* coverage detail is named in the Admin IA row ("coverage detail") but the Operator Observability Admin bullet list — the deep spec — omits it while listing everything else. *Fix:* add it to the Admin bullets.

## 8. Shape fit — strong

DESIGN.md: all eight body sections present in canonical spec order; frontmatter keys match the spec table; cross-reference syntax used correctly throughout. EXPERIENCE.md: all eight required defaults present (Foundation, IA, Voice and Tone, Component Patterns, State Patterns, Interaction Primitives, Accessibility Floor, Key Flows). The two invented sections earn their place — Operator Observability because the operator is half the product's user modes, Notifications & Recall because alerts span four surfaces and two systems. Responsive & Platform correctly omitted with the desktop-only decision stated in Foundation; Inspiration & Anti-patterns omitted (optional). The *Deliberate non-designs* footer is a genuinely good invention — it is what keeps most omissions honest.

### Findings

- **low** EXPERIENCE.md frontmatter lacks the `sources:` list both experience examples carry (PRD/epics/architecture paths). Provenance currently lives only in `.working/source-extract.md`. *Fix:* add the three source paths to frontmatter.

## Mechanical notes

- **Cross-refs:** zero broken `{path.to.token}` references in either file; all four EXPERIENCE→DESIGN token references resolve by name. No references to `mockups/`/`wireframes/` exist yet (nothing broken, but nothing linked either — see §5).
- **Frontmatter:** DESIGN.md carries extra keys (`status`, `created`, `updated`) beyond the spec table — harmless metadata, spec doesn't forbid. `rounded` has no `full` key, consistent with the no-pills rule. EXPERIENCE.md is missing `sources:` (§8).
- **Token/name inconsistencies:** `since-panel` (component key) vs "Since-last-visit panel" (both bodies) — resolvable but worth aligning; "warm accent" in the since-panel body spec names no token (§2); `favourite-star`/`health-warn` hex sharing contradicts the Do's and Don'ts row (§2).
- **Untokenized layout constants:** ~1440px content width, ~460px map rail, ~50–60% photo height, `grayscale 0.7 / brightness 0.75` gone treatment live only in prose. Acceptable as prose specs, but the rail width and frame width are load-bearing enough to deserve `spacing`/component tokens if the file gets another pass.
- **Deliberate hex sharing** (green = drop = excellent = ok; rust = above = gone) is documented in the frontmatter comment and consistently narrated in Colors — good practice, no action.
