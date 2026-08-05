# Validation Report — imoveis

- **DESIGN.md:** `_bmad-output/planning-artifacts/ux-designs/ux-imoveis-2026-08-05/DESIGN.md`
- **EXPERIENCE.md:** `_bmad-output/planning-artifacts/ux-designs/ux-imoveis-2026-08-05/EXPERIENCE.md`
- **Run at:** 2026-08-05T05:23:16-03:00

## Overall verdict

A well-crafted pair with an unusually disciplined honesty spine (absence states, banned patterns, verdict-in-words) and a clean, fully-resolving token layer. The gaps cluster in three places: two source requirements (FR-15 semantic search, FR-30's *filter* half) are neither designed nor listed as deliberate non-designs; the Admin/modal component vocabulary that the in-flight v0.13 UI stories (s1.6, s2.2) will consume has behavioral coverage but almost no visual spec; and the visual artifacts in `.working/` are not linked from either spine (no promotion, no spines-win-on-conflict clause). Fixable in one editing pass — nothing structural is wrong.

The adversarial review materially shifts that picture: it lands **two criticals in availability-truth semantics** — the flagship `Verificar disponibilidade` interaction has no failure/unknown outcome and can render a failed recheck as fresh confidence, and a shortlisted property found gone by auto-verify alerts no one — plus a false-gone cascade under scraper outage and two designed journey beats (J1 step 4, J2 step 3) that contradict the spine's own modal-scrim and async-enrichment rules as written. The pt-BR reviewer independently confirms the flagship percentile badge `top 25% preço` breaks the spine's own cheap-direction hard rule. Availability truth, the alert economy, and the recheck interaction need a genuine design pass — more than the single editing pass the rubric alone estimated — before s1.6/s2.2 consume this pair.

## Category verdicts

- Flow coverage — adequate (J1–J4 well-built; FR-15 silently absent; failure paths merged into the adversarial recheck critical)
- Token completeness — adequate (zero dangling references; contrast claims unbacked; gold hex contradiction)
- Component coverage — thin (front door strong; Admin/modal internals — s1.6/s2.2 consumers — have no visual spec)
- State coverage — adequate (honesty states are the pair's best part; generic cold-load/empty/failure layer missing)
- Visual reference coverage — thin (promotion never happened; no artifact linked; no spines-win-on-conflict clause)
- Bloat & overspecification — strong (disciplined prose, table-first, no source restatement)
- Inheritance discipline — adequate (dense accurate citations; Watchlist vs Favourites never mapped)
- Shape fit — strong (canonical sections, earned inventions; only frontmatter `sources:` missing)

## Findings by severity

Counts after cross-reviewer dedupe: **2 critical · 15 high · 28 medium · 19 low** (64 findings).

### Critical (2)

**[Adversarial UX + Rubric: Flow/Component/State]** — `Verificar disponibilidade` has no defined outcome for a failed — or gone — recheck (EXPERIENCE.md J1 step 5; Component Patterns)
When the recheck hits Cloudflare/403/timeout (the project's own convention says these are `unknown`, and OLX blocks are routine), the spine defines only the happy path ("comes back fresh"). If `unknown` renders as no visual change, the card keeps its fresh freshness stamp and Felipe reads "I checked, it's available" — the exact trust failure the button exists to kill, now with *added* false confidence because he actively verified. The rubric independently flagged the missing flow failure paths (J1's own anti-climax — recheck comes back *gone* — undesigned; J2's listing-already-gone at click-through untreated), the recheck button's missing in-progress/result behavior, and the untreated recheck-in-progress modal state; merged here at the adversarial severity.
Fix: recheck is three-state (`disponível / indisponível / não foi possível verificar`) with its own timestamp (`verificado às 21:14` vs `verificação falhou`); `unknown` must be visually distinct from `available` and must not refresh the freshness stamp. Add `Failure:` lines to J1 and J2 — the gone-listing State Pattern gives most of the treatment already.

**[Adversarial UX]** — Auto-verify finds a shortlisted Property gone and nobody is told (EXPERIENCE.md Notifications & Recall; J1 step 6 vs J4 step 1)
Notifications lists exactly two alert types (new-match, price-drop). When Thursday's daily recheck finds a starred/roteiro item `provavelmente alugado`, no channel fires; Felipe discovers it Saturday morning — or worse, at the door. The highest-value alert in the entire product (a shortlist item dying) is missing from the alert economy.
Fix: shortlist-item-gone is a third first-class alert (push + email), on by default for starred items.

### High (15)

**[Flow coverage + Adversarial UX]** — FR-15 semantic search is nowhere — not designed, not deferred (EXPERIENCE.md IA table / Deliberate non-designs)
FR-15 (`GET /properties?q=`, a named surface in source-extract §2) appears nowhere in EXPERIENCE.md — not in the IA table, not in any flow, not in the *Deliberate non-designs* footer. The memlog records the decision but the spine doesn't carry it, so a consumer doing a readiness check reads it as an unexplained omission. Both reviewers flagged the silent cut.
Fix: one line in *Deliberate non-designs* ("semantic search: existing surface kept as-is, pt-BR queries, no redesign this pass") or an IA row / search affordance slot in the top nav.

**[Component coverage]** — FR-30's percentile *filter control* appears nowhere — story s2.2 will have to invent it (EXPERIENCE.md Component Patterns filter-bar / Deliberate non-designs)
FR-30 is "percentile on card/modal, **filterable**" (source-extract §2/§3; open question #6 explicitly flagged the control's form). The spine designs badge + modal sentence and the cheap-direction copy rule, but the filter control is neither in the filter-bar row nor deferred.
Fix: add it to the Component Patterns filter-bar row (form + how it composes with the 2-line ceiling) or explicitly defer it in *Deliberate non-designs*.

**[Component coverage]** — The price-history chart — the modal's centerpiece — has no spec in either spine (DESIGN.md Components / EXPERIENCE.md Component Patterns)
J1 step 3's centerpiece and UJ-2's confirmation beat: no visual rules (line/axis/ink on the dark ground, drop-marker treatment, the system-wide dataviz posture given "no progress bars") and no behavioral row (range, per-platform series?, hover).
Fix: one DESIGN.md.Components entry + one Component Patterns row.

**[Component coverage]** — Admin components consumed by in-flight story s1.6 have zero visual spec (DESIGN.md Components vs EXPERIENCE.md Operator Observability)
The backfill card (state, budget, throughput, day-scale ETA, start/pause/resume, collision warning line) and the run-history table have good behavioral coverage but zero DESIGN.md visual spec ("admin tables" appears only in Typography prose). The very next UI story ships against this contract.
Fix: add `backfill-card` and `run-history-table` (and the toast, also unspecced) to DESIGN.md.Components, even briefly.

**[Adversarial UX]** — Scraper outage mass-manufactures false `provavelmente alugado` (EXPERIENCE.md State Patterns "Gone listing", "Staleness")
Gone = `sem atualização há 14 dias`, but "no update" is indistinguishable from "scraper broken/circuit-open for 14 days" — a two-week OLX block flips *every* OLX listing to rust gone-state, poisoning the grid and the shortlist with false deaths. Related: FR-11 skip-unchanged means "seen but unchanged" — if that doesn't bump last-seen, perfectly available unchanged listings rot toward gone.
Fix: gone heuristic counts only *scrape runs that succeeded and did not include the listing*; skip-unchanged must bump last-seen; when a platform is degraded, its cards show `plataforma sem coleta há N dias`, not gone.

**[Adversarial UX]** — Shortlist shows no per-item verification recency or failure state (EXPERIENCE.md J4 step 1; Favoritos surface row)
J4 step 1 asserts "all availability-verified by the automatic rechecks" — but if Friday night's recheck batch failed (blocked, worker down), the shortlist looks identical to a fully verified one. The one screen where staleness costs a physical trip has no staleness display.
Fix: every shortlist row carries `disponibilidade verificada há Xh` / `última verificação falhou` — same honesty stamp the cards get.

**[pt-BR microcopy + Adversarial UX]** — `top 25% preço` violates the spine's own cheap-direction hard rule — and is not grammatical Portuguese (DESIGN.md percentile-badge, Do's table; EXPERIENCE.md Voice and Tone, J1 step 2)
The rule: "wording that could be read as 'top = most expensive' is forbidden." In pt-BR, "top" carries a premium/best-in-class connotation ("top de linha"), so "top 25% preço" plausibly reads as *the priciest quarter* — the exact inversion the rule forbids. It is also a telegraphic anglicized fragment, which the voice doc bans. The adversarial review notes the only place the rule is broken is the copy it was written to protect. Bare `25% mais baratos` is not a safe fix either: next to the `−8% desde julho` drop badge it reads as a 25% *discount*.
Fix: badge: `entre os 25% mais baratos`; modal sentence stays `entre os 25% mais baratos do bairro` — one consistent phrasing family (generic form: `entre os N% mais baratos`).

**[pt-BR microcopy]** — `provavelmente alugado` is factually wrong on sale listings (DESIGN.md Colors § Gone, Gone card; EXPERIENCE.md Voice table, State Patterns § Gone listing)
A gone *venda* listing was not "alugado" — it was sold (or delisted). The system explicitly handles both listing types (Aluguel/Venda segmented control, per-type price filters, dual-type Properties via `primaryListing`), so this string must vary by the listing type of the gone listing.
Fix: per listing type: `provavelmente alugado — …` (aluguel) / `provavelmente vendido — …` (venda); dual-type follows the primary listing.

**[Adversarial UX]** — Desktop push is the least reliable channel in a localhost deployment, and J2 leans on it (EXPERIENCE.md Notifications channels; J2 step 1)
Web push needs the browser running (and a service worker on a localhost origin); when the app tab isn't open — the exact moment an interrupt matters — push silently never arrives. Felipe interprets silence as "no matches" and a fast-moving Savassi 2-quartos goes to someone else.
Fix: email is the guaranteed interrupt channel; push is opportunistic bonus. State this ordering in the spine, or use an OS-level notifier daemon instead of browser push.

**[Adversarial UX]** — J2 contradicts the spine's own async-enrichment reality (EXPERIENCE.md J2 vs State Patterns "Enrichment pending")
New-match alerts fire on ingest; enrichment is async by architecture, so the moment the push arrives is precisely when the modal is most likely to show `análise de IA pendente` — no verdict, no percentile. J2 step 3 is the happy path of a race the design has already declared it loses.
Fix: either gate new-match alerts on enrichment-complete (delay minutes, gain a decidable modal) or design the J2 beat around a pending modal (photos + price + percentile-less triage, with "verdict chega em breve").

**[Adversarial UX]** — A scraper that stops *running* never turns amber (EXPERIENCE.md Health strip; State Patterns "Health ok")
Anomaly = per-run deviation from own baseline — but a run that never happens (dead Celery beat, both scrapers down from one shared cause) produces no run to deviate. The only signal is the recency string on a still-green dot, with no threshold at which recency alone flips the chip. Beat death is a known incident class in this project; under this design the strip stays green while the pipeline is dark and every listing quietly ages toward false-gone.
Fix: expected-cadence contract per scraper — chip goes amber on `sem run há Nh (esperado: a cada 6h)`, independent of run-level anomaly detection.

**[Adversarial UX]** — Two-way bbox sync eats the card he's reading (EXPERIENCE.md IA "synced split view"; Map component)
A drop card catches him → he pans the map toward the Igreja → bbox re-filters the grid → the drop card vanishes from under his cursor. Mandatory two-way sync with no "buscar nesta área" toggle turns every map exploration into a grid reshuffle mid-thought.
Fix: map→list sync is explicit (a "filtrar pela área do mapa" toggle or button, Zillow-style); list→map hover sync stays automatic.

**[Adversarial UX]** — The map bbox is an invisible active filter (EXPERIENCE.md Filter bar; Map)
Filter bar "shows only active filters" — but a bbox narrowed by an earlier pan is nowhere represented as a chip. Later he widens price, sees mysteriously few results, with no removable `área do mapa ×` chip explaining why.
Fix: an active bbox renders as a filter chip like any other, removable with `×`.

**[Adversarial UX + Rubric: Component coverage]** — Dismiss is "recoverable" with no recovery surface (EXPERIENCE.md Property card; IA table)
Mis-click the dismiss (it sits next to the star, top-right on-photo) and the Property vanishes optimistically. The IA has no Dismissed list, no undo toast, no filter named for it — "recoverable" is asserted, mechanism absent. A fat-fingered dismiss of tonight's best card is an unrecoverable loss as designed. The rubric flagged the same gap ("recoverable *where* is undefined", medium); merged at the adversarial severity.
Fix: immediate `desfazer` toast on dismiss + a `descartados` filter/view; and separate star/dismiss hit targets.

**[Adversarial UX + Rubric: Component coverage]** — "Since last visit" has no session semantics — the reset rule is undefined (EXPERIENCE.md since-panel; J1)
What resets the panel? If "on app open," a 30-second lunch glance zeroes the counters and the evening check — the product's core ritual — opens to `0 novos`. If it never auto-resets, counts inflate meaninglessly. The panel's entire value rides on an undefined reset rule. The rubric flagged the same gap (what counts as a "visit"? when do counts zero? — medium); merged at the adversarial severity.
Fix: explicit mark-as-caught-up action (or reset only after N minutes of active engagement), and the panel states its window: `desde ter, 21h`.

### Medium (28)

**[Token completeness]** — No contrast targets stated; Accessibility Floor's WCAG AA claim is unbacked (DESIGN.md Colors / EXPERIENCE.md Accessibility Floor)
EXPERIENCE.md claims "WCAG AA text contrast … (`DESIGN.md` token pairs chosen for it)" — a claim the referenced file never backs. Risky pairs are the load-bearing ones: `text-muted` #82859a and `verdict-market` #8b8e99 at 11–12.5px on `surface-card`, and `text-secondary` on `{colors.scrim}` over arbitrary photos.
Fix: add a short contrast table (pair → ratio → AA verdict) to DESIGN.md Colors; state a minimum for on-photo scrim text.

**[Token completeness + Adversarial UX]** — Token layer contradicts the gold hard rule: `favourite-star` = `health-warn` = #d9b35f (DESIGN.md colors frontmatter vs Do's/Don'ts)
Frontmatter blesses the sharing ("gold = star = warn") while the Do's table rules "Gold star = favourite, and nothing else / health warn is its own amber role" — implementation will pick one at random. Adversarial adds the perceptual dimension: `verdict-good` (#d3b662) is nearly the same gold, so a `Bom preço` underline, a starred photo, and an amber warn dot are three meanings in one indistinguishable hue.
Fix: split health-warn to a distinct amber (shift hue ~15° toward orange) and fix the frontmatter comment; accept star/verdict-good sharing warmth since both are positive — or rewrite the Do/Don't row to claim non-overlapping *contexts*, not distinct inks.

**[Component coverage]** — POI management is undesigned and unflagged (EXPERIENCE.md J1/J4, Map spec)
POI anchors are central to J1/J4 and the map spec, but how Igreja/Casa dos pais get created/edited, and where, is undesigned and unflagged.
Fix: defer explicitly or add a line (e.g. "POI CRUD lives in Admin, minimal form").

**[State coverage]** — No cold-load state for the Painel (EXPERIENCE.md State Patterns)
Blocking spinners over the grid are banned (correctly), but nothing says what loading *is* — skeleton cards? empty grid? Both reference examples specify cold load first.
Fix: one State Patterns row (e.g. skeleton cards matching the grid layout, no spinner).

**[State coverage]** — No empty states across surfaces (EXPERIENCE.md State Patterns)
Grid with zero filter matches, empty Favoritos/shortlist, empty Buscas salvas, empty Alertas, first-ever-visit since-panel. A pt-BR empty sentence per surface is cheap and on-voice.
Fix: one row covering the empty family with per-surface copy.

**[State coverage]** — No grid-fetch-failure state (EXPERIENCE.md State Patterns)
"Errors never block the grid" governs *action* errors; if the properties request itself fails on cold load there is nothing to not-block.
Fix: one row (toast + retained last-good data, or explicit failure copy).

**[Visual reference coverage]** — No inline visual references anywhere in either spine (DESIGN.md Brand & Style / EXPERIENCE.md IA)
The picked-direction mock (Meia-noite variation in `color-themes-2.html`) is the provenance for all 19 hexes and the card anatomy, but a consumer of DESIGN.md cannot find it. `imports/` is empty; `mockups/`/`wireframes/` do not exist — promotion has not happened.
Fix: promote the winning variation out of `.working/` (e.g. `mockups/`), then link it from DESIGN.md Brand & Style and EXPERIENCE.md IA.

**[Visual reference coverage]** — Spines-win-on-conflict is stated nowhere (DESIGN.md / EXPERIENCE.md)
Both experience examples model the "→ Composition reference: … Spine wins on conflict." line. Once mocks are linked, a consumer needs the precedence rule exactly once.
Fix: append "Spine wins on conflict." to the first composition-reference link.

**[Inheritance discipline]** — Watchlist vs Favourites never mapped (EXPERIENCE.md Foundation / Notifications)
The sources treat Watchlist (price-drop alert set, FR-16, UJ-2) and Favourite (starred shortlist) as distinct terms. EXPERIENCE.md builds Favoritos thoroughly but uses "watchlist" only once without mapping the two — is starring what puts a Property on the watchlist? Downstream story-dev for FR-16 has to guess.
Fix: one Foundation or Notifications sentence fixing the mapping (e.g. "starred = watched; there is no separate watchlist").

**[Adversarial UX]** — `2 fontes` freshness is per-Property, masking a dead source (DESIGN.md freshness-stamp; EXPERIENCE.md J1 step 5)
Stamp shows one platform (`visto hoje na OLX`) while the QuintoAndar listing — the R$200-higher one powering the J1 negotiation lever — may not have been seen in 10 days. He walks into a negotiation citing a cross-platform gap where one side is gone.
Fix: modal's per-platform comparison shows per-listing last-seen; the `2 fontes` badge downgrades (or annotates) when one source is stale.

**[Adversarial UX]** — Stale verdict beside fresh price after a drop (EXPERIENCE.md State Patterns)
A price change re-enqueues enrichment (async, AD-4), so for hours the card shows the *old* verdict next to a green drop badge computed from the *new* price — two signals from different realities on one card, nothing marks the verdict as outdated.
Fix: on material price change, verdict reverts to the dashed pending treatment until re-scored.

**[Adversarial UX]** — Green drop badge = "buy signal" even on an `Acima do mercado` card (DESIGN.md price-drop-badge; Colors)
−8% on a listing still rust-underlined as above-market is not a buy signal — it's an overpriced listing correcting. The grid scan pattern (hunt green) surfaces exactly these cards.
Fix: keep the drop badge factual (`−8% desde julho`) but strip "buy signal" framing from the spec; a drop on a rust-verdict card may render in neutral ink, or the verdict must visually dominate the badge.

**[Adversarial UX]** — Per-search new-match alerts have no batching decision (EXPERIENCE.md Notifications & Recall)
40+ matches over an absent week = 40+ single emails, overlapping with the weekly digest covering the same properties — double delivery teaches him to filter the sender to spam, killing J2 forever.
Fix: daily batch window per search for email; digest excludes already-alerted items or the spine says which system owns which property.

**[Adversarial UX]** — Drop-alert scope vs since-panel scope mismatch (EXPERIENCE.md since-panel; Notifications)
Price-drop alerts are watchlist/threshold-gated; the since-panel counts "3 quedas de preço" — over what population? If global, noise he can't act on; if scoped, unstarred saved-search matches drop silently between sessions and the panel is his only catch — with no drill-in.
Fix: since-panel counts are scoped to saved searches + favourites, and the spine says so.

**[Adversarial UX]** — Per-watchlist drop-threshold UX is deferred, but a *default* still ships (EXPERIENCE.md non-designs; source-extract Q10)
Week one runs on an invisible global default: too low → alert spam → he disables drops; too high → a R$150 drop on a R$3.000 target never fires. The deferral is acknowledged; the silent-default consequence is not.
Fix: even before the config UX exists, the alert email states the threshold that fired it ("queda de R$240 — seu mínimo: R$100") so the default is visible and correctable.

**[Adversarial UX]** — Cold-start: no baseline, no amber (EXPERIENCE.md Health anomaly)
A new scraper, or one whose baseline resets after a format change/cassette refresh, cannot deviate from a median it doesn't have — its worst early runs (the ones most likely to be broken) show green.
Fix: below N historical runs, chip shows a distinct `calibrando baseline (3/10 runs)` state, not ok-green.

**[Adversarial UX]** — Gradual drift rots the baseline (EXPERIENCE.md Health anomaly; Admin run-history)
A rolling own-median tracks slow decay: OLX yield sliding 5%/week keeps every run inside its (also sliding) band; six weeks later yield has halved with an all-green history — and reduced update frequency again feeds the false-gone machine.
Fix: run-history table compares against a *pinned* long-window baseline as well as the rolling median; drift beyond X% over Y weeks is itself a reason string.

**[Adversarial UX]** — Backfill collision warning lives in the wrong medium (EXPERIENCE.md Operator Observability, backfill card)
The persistent warning line is on the Admin backfill card — but the collision happens when Felipe types `validate.sh` in a terminal, where Admin isn't on screen. AD-13 health-strip visibility helps only if he glances at the browser first.
Fix: keep the card line, but note the real guard is the shell-side heartbeat check; the front-door backfill chip (not just Admin) carries the warning glyph so any glance says "não rode validate agora".

**[Adversarial UX]** — J1 step 4 breaks the spine's own modal rule (EXPERIENCE.md J1 step 4 vs Elevation & Depth)
The modal sits on a full-page scrim; step 4 says "Map beside it: travel-time band shows the flat is within 15 min of the Igreja." With the scrim up there is no map beside it — unless the modal embeds its own mini-map, which no component defines. The journey's location beat is unimplementable as specified.
Fix: either the modal contains a location panel (mini-map with POI bands) or the modal is a side panel that leaves the map rail visible.

**[Adversarial UX]** — Since-panel counts have no drill-in (EXPERIENCE.md since-panel; J1 steps 1–2)
"3 quedas de preço" with a single link out means he manually hunts three cards in a full grid — the panel announces news it can't take him to, every single evening.
Fix: each count is a link that applies a corresponding transient filter (`novos desde a última visita`, `quedas`, `removidos`).

**[Adversarial UX]** — Comparing two finalists is modal ping-pong by design (EXPERIENCE.md IA Comparar row; Interaction Primitives)
The one-level modal rule + "no journey lands in Comparar" means the evening endgame — A vs B — is close-modal, reopen, close, reopen, holding numbers in his head. Deprioritizing Comparar is a recorded decision, but no lightweight alternative exists either.
Fix: the shortlist view shows key numbers (price, verdict, percentile, R$/m²) in comparable rows so two starred candidates are comparable without Comparar.

**[Adversarial UX]** — Gone listings can resurrect and no state exists for it (EXPERIENCE.md State Patterns "Gone listing")
BH relisting is routine: a `provavelmente alugado` Property reappears (often at a new price, sometimes as a "new" listing dedupe folds back in). Does it un-gone? Does its price history bridge the gap? Does it fire a new-match alert as if new? Undefined — and a relisting of a previously-shortlisted flat is exactly a deal signal he'd want.
Fix: define a `voltou ao mercado` transition — clears gone state, annotates the price-history chart, and qualifies as alert-worthy for previously starred items.

**[Adversarial UX]** — Drop-badge baseline is undefined (EXPERIENCE.md Property card; DESIGN.md price-drop-badge)
`−8% desde julho` — since first-seen? peak? last change? A relisted flat that returned inflated then "dropped" to its old price shows a green badge on a net-flat listing. Combined with the resurrection gap, relist-and-discount games read as deals.
Fix: badge measures from a defined anchor (max of trailing 90 days) and the modal chart makes the anchor visible.

**[Adversarial UX]** — Shortlist notes are load-bearing and undesigned (EXPERIENCE.md J4 step 4; Favoritos surface)
J4's climax ("banheiro pior que as fotos", `fazer proposta`) requires note entry/edit and a post-visit verdict state machine — no component pattern, no states (visited? proposta feita? recusado?) exist anywhere.
Fix: define the shortlist row primitive: free-text note + a small post-visit status enum, both editable inline.

**[Adversarial UX]** — On-demand recheck has no cooldown, and it burns the shared scraping identity (EXPERIENCE.md J1 step 5)
Every `Verificar disponibilidade` click is a live hit on OLX/QuintoAndar from the same IP the nightly scrapers use; an anxious evening of rechecking the shortlist can trigger the Cloudflare blocking that then degrades the whole pipeline (feeding the false-gone cascade). A UX button with an operator-level blast radius, unmentioned.
Fix: per-listing cooldown (`verificado há 20 min`) + a modest global recheck budget surfaced in the button state.

**[pt-BR microcopy]** — `OLX: run 5× mais rápido que a mediana` — "run" is developer jargon on a pt-BR surface (EXPERIENCE.md Voice table, State Patterns § Health anomaly, J3 step 1)
Good native words exist and the voice doc bans anglicized fragments where clear pt-BR carries. Knock-on gender agreement: "coleta" is feminine, so the adjective flips.
Fix: `OLX: coleta 5× mais rápida que a mediana` ("varredura" also works; pick one and use it for "run" everywhere, including Admin run-history labels).

**[pt-BR microcopy]** — `2 anúncios removidos` is ambiguous with the user's own dismiss action (EXPERIENCE.md J1 step 1, since-panel)
"Removidos" — did the market drop them or did I? These are listings that left the source portals.
Fix: `2 anúncios saíram do ar` (alternatively `2 anúncios encerrados`).

**[pt-BR microcopy]** — Backfill states `idle / running / paused / backing-off` are English on an otherwise localized operator surface (EXPERIENCE.md Operator Observability § Backfill card)
If these render literally they break the pt-BR-only default. "Backing-off" has no good literal translation — say what it means.
Fix: `inativo / em execução / pausado / em espera (limite da API)`.

### Low (19)

**[Flow coverage]** — UJ-2's price-drop → price-history-chart confirmation beat is folded away (EXPERIENCE.md J2 / Notifications)
J2 covers the alert-interrupt shape but with a new-match, and no flow ends on the chart. Only the chart-confirmation beat is lost.
Fix: one sentence in J2 or Notifications noting the drop-alert variant lands on the modal's price-history chart.

**[Flow coverage]** — Flows renamed J1–J4 with no mapping to source UJ-1..4 / FR ids (EXPERIENCE.md Key Flows)
Fix: a parenthetical per flow, e.g. "J1 (absorbs UJ-1)".

**[Token completeness]** — Several component values are prose, not resolvable values (DESIGN.md Components)
`percentile-badge.background: 'price-drop at ~12% over card'`, `border: '1px solid price-drop at ~35%'`, `health-chip.background: 'surface-card blended toward background'`, `since-panel.background: '{colors.surface-elevated} toward {colors.surface-card}'`. A human resolves them; a token resolver doesn't.
Fix: mint alpha-variant tokens (e.g. `price-drop-tint-12`) or state the computed hex inline.

**[Token completeness]** — "warm accent" in since-panel body names no token (DESIGN.md since-panel)
The only `accent` token is cool azure; probably `favourite-star` gold is meant.
Fix: name the token.

**[Component coverage + Adversarial UX]** — Saved-search row and Alertas panel (s2.4 consumers) have behavior but no visual entry, and the Alertas interior is undesigned (DESIGN.md Components / EXPERIENCE.md IA Alertas row)
Toggle, bell badge, alert list row unspecced; row anatomy, read/unread, clearing, retention unstated; J2's "clicks straight into the modal" implies deep-linking behavior nobody specified.
Fix: small Components entries or an "inherits chip/panel rules" note; minimal Alertas row spec: type icon, property line, timestamp, click → modal, auto-read on click.

**[State coverage]** — Map tile failure untreated (EXPERIENCE.md State Patterns)
Maps require network; offline tiles are a stated non-goal, but tile failure has no treatment. (The companion recheck-in-progress gap merged into the critical recheck finding.)
Fix: fold into the failure rows above.

**[Visual reference coverage]** — Rejected `direction-*.html` explorations indistinguishable from the winner (`.working/`)
A future session could source-extract from a rejected direction.
Fix: promotion of the winner resolves this implicitly.

**[Bloat & overspecification]** — Mild editorial voice leaks into EXPERIENCE.md prose (EXPERIENCE.md prose)
"Honest absence is the system's spine", "The workshop bench, split in two" — harmless at this dose, but the rubric places that voice in DESIGN.md.
Fix: optional; trim if the pair gets another pass.

**[Inheritance discipline]** — "Score-coloured grid" survives in the IA table while colour-filled score areas are banned (EXPERIENCE.md IA table)
A consumer of the IA table alone could infer painted cards.
Fix: "verdict-coloured" or a parenthetical.

**[Inheritance discipline + Adversarial UX]** — FR-29 per-signal-type coverage detail under-carried (EXPERIENCE.md Admin bullets / Health strip)
The Admin IA row names "coverage detail" but the Operator Observability Admin bullet list — the deep spec — omits it. Adversarial adds: front-door `Cobertura IA 82%` is an undefined aggregate — if a mean, 100% embeddings + 60% visual reads as "mostly done" while the signal he cares about lags.
Fix: add per-signal-type coverage to the Admin bullets; front-door % = minimum across signal types, labeled on hover, per-type detail in Admin.

**[Shape fit]** — EXPERIENCE.md frontmatter lacks the `sources:` list (EXPERIENCE.md frontmatter)
Both experience examples carry PRD/epics/architecture paths; provenance currently lives only in `.working/source-extract.md`.
Fix: add the three source paths to frontmatter.

**[Adversarial UX]** — Gone dots on the map are ambiguous with above-market (DESIGN.md map-point; EXPERIENCE.md map legend)
With the gone filter on, a rust map point could be "overpriced" or "dead" — the legend has no gone entry.
Fix: gone map points render hollow/desaturated; legend gains a gone entry when the filter is active.

**[Adversarial UX]** — Closing the modal loses grid scroll position (EXPERIENCE.md Map viewport contract)
Not stated as preserved; the viewport-persistence contract covers only the map. Mid-grid triage restarting from the top every modal close is death by paper cuts on a 40-card evening.
Fix: extend the persistence contract: modal open/close never moves grid scroll.

**[pt-BR microcopy]** — `QuintoAndar · 2h atrás` — translated-feeling form, inconsistent with `há` used everywhere else (EXPERIENCE.md State Patterns § Health ok, Health strip)
Fix: `QuintoAndar · há 2h`.

**[pt-BR microcopy]** — `Cobertura IA 82%` — missing preposition, telegraphic (EXPERIENCE.md Operator Observability § Health strip)
Fix: `Cobertura de IA: 82%` (chip may drop the colon).

**[pt-BR microcopy]** — `Favoritos / roteiro de visitas` — mixed casing inside one nav label (EXPERIENCE.md IA table, J4 step 1)
Fix: `Favoritos / Roteiro de visitas` — or simply `Roteiro de visitas`, since favourites graduate into it and one name is calmer nav.

**[pt-BR microcopy]** — `Admin / Operações` — "Admin" is an anglicism and redundant (EXPERIENCE.md IA table)
Acceptable for a solo operator tool, but the cleaner label exists.
Fix: `Operações` alone.

**[pt-BR microcopy]** — Percentile modal sentence drops the listing-type half of the cohort on dual-type Properties (EXPERIENCE.md percentile hard rules, cohort bullet)
`entre os 25% mais baratos do bairro` encodes bairro but not bairro × tipo, which the spine itself requires; on a dual rent/sale Property the reader can't tell which cohort the 25% refers to.
Fix: per type: `entre os 25% mais baratos dos aluguéis do bairro` / `…das vendas do bairro` (single-type listings keep the short form).

**[pt-BR microcopy]** — Verdict scale axis break: three price-axis verdicts, one deal-axis (`Excelente negócio`) — optional (DESIGN.md Colors § Verdict scale; EXPERIENCE.md verdict component)
Register and naturalness are fine; the axis break is defensible as an editorial peak.
Fix: if strict parallelism is wanted: `Preço excelente` for the top verdict. Keep as-is if the emphasis is intentional.

## Reviewer files

- review-rubric.md
- review-adversarial-ux.md
- review-ptbr-microcopy.md
