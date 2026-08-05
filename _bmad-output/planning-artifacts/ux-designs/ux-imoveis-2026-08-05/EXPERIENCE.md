---
name: imoveis
description: Experience specification for the Imoveis deal-tracker frontend
status: final
created: 2026-08-05
updated: 2026-08-05
sources:
  - ../../prds/prd-imoveis-2026-08-05/
  - ../../epics.md
  - ../../architecture/architecture-imoveis-2026-07-23/
---

# Imoveis — Experience Spine

## Foundation

Desktop browser only, on Felipe's desktop — localhost, single user (single principal/owner, AD-11). Dark-only. Existing React 19 + Vite stack; `DESIGN.md` is the visual identity reference, this spine is the experience. The frontend talks **only** to the FastAPI surface (AD-8 — never Redis/DB/Ollama directly; backfill and health state arrive via API endpoints). All decisioning views (grid, detail side panel, compare, export, digest) render the single AD-12 canonical projection — no parallel flatteners. Property URLs use `public_id`. AI scores are floats in `[0.0, 1.0]`; verdicts are localized server-side.

## Information Architecture

One front door. The dashboard is the product; everything else is a satellite.

| Surface | Reached from | Purpose |
|---|---|---|
| **Painel (Imóveis)** | App open | The one dashboard: since-panel + operator health strip + filter bar + split verdict-coloured grid (the sources' "score-coloured") / map |
| **Detail side panel** | Card click, map point click, alert click | Price history, per-platform price comparison with per-listing last-seen, verdict explainability, sentiment, availability recheck, star. Slides over the grid on a partial scrim — the map rail stays visible |
| **Favoritos** | Top nav | Starred Properties and their availability — one surface, one name: comparable rows, verification stamps, and a filterable history of favourites that left the market |
| **Buscas salvas** | Top nav | Named filter presets; per-search new-match alert toggle, alert state visible at a glance |
| **Alertas** | Top nav (bell) | In-app alert history: price drops, new matches, favourites gone |
| **Busca** | Top nav | Semantic search (FR-15), kept as-is — see *Deliberate non-designs* |
| **Operações** | Top nav | Run-history analytics, backfill card, coverage detail, ingest counts, dedupe stats, scrape trigger, POI management |
| **Comparar** | Selection from grid/Favoritos | Side-by-side (2–4). Minimal by design — see *Deliberate non-designs* |

- Grid × map is a **split view**; hover-sync and bbox-filter rules live on the Map row in Component Patterns.
- **BH-default**: region filter defaults to BH/MG; opportunistic SP/Campinas data is reachable only via an explicit region filter change.
- Composition references: structure parents [`mockups/direction-warm-craft.html`](mockups/direction-warm-craft.html) + [`mockups/direction-editorial.html`](mockups/direction-editorial.html); palette provenance [`mockups/palette-meia-noite.html`](mockups/palette-meia-noite.html); front-door key mock [`mockups/key-painel.html`](mockups/key-painel.html). Spine wins on conflict.

## Voice and Tone

Neutral and clear pt-BR. Plain professional sentences, informative never chatty — no terse cockpit fragments, no warm-companion personality.

**pt-BR only** is the UI default. [NOTE FOR PRD] This overrides NFR-7's "English default"; the engineering rule stays intact — every string still lands in both en and pt-BR catalogs.

| Do | Don't |
|---|---|
| "3 imóveis baixaram de preço desde ontem" | "🔥 3 quedas!" |
| "análise de IA pendente" | "Carregando…", a spinner, or a fake score |
| "provavelmente alugado — sem atualização há 14 dias" (aluguel) / "provavelmente vendido — …" (venda) | Silently hiding the listing |
| "OLX: coleta 5× mais rápida que a mediana" | "OLX: anomalia detectada (código 7)", or the anglicism "run" on any user-facing surface |
| Full sentences where they help; counts with nouns | Exclamation marks, motivational copy |

"Coleta" is the word for a scrape run everywhere user-facing (health strip, Operações, run history); "run" survives only in code and wire enums.

**Percentile microcopy (hard rules):**

- Never statistician notation — no `P25`, no "percentil", no `≤` symbols.
- Badge form: `entre os 25% mais baratos` — the word *barato* appears on the badge itself. Sentence form (detail side panel): `entre os 25% mais baratos do bairro`; on dual-type Properties the sentence names the cohort type — `entre os 25% mais baratos dos aluguéis do bairro` / `…das vendas do bairro` (single-type listings keep the short form).
- **Unambiguous cheap-direction rule:** every percentile phrasing must make explicit that lower price = better (`mais barato`); wording that could be read as "top = most expensive" is forbidden.
- Cohort language mirrors the source: percentile is per **cohort** (neighbourhood × listing type), per listing type on dual rent/sale Properties.

## Component Patterns

Behavioral. Visual specs live in `DESIGN.md.Components`.

| Component | Use | Behavioral rules |
|---|---|---|
| Filter bar | Painel | Shows only **active** filters — including the map bbox (`área do mapa ×` chip) when the map filter toggle is on. Bairro and sentiment tags via searchable typeahead pickers (suggestions live inside the picker, not the bar). Active chips collapse (`Savassi +3`). Hard ceiling of 2 wrapped lines, then a `Filtros (N)` button opens the full panel. Header height constant by contract. Saved searches are the long-term answer to vocabulary growth. |
| Price filter | Filter bar | Remembered **per listing type**: aluguel and venda keep independent ranges, scales, and formatting; switching tipo swaps the scale and restores that type's last range (mirrors BIN-77 `price_type` no-cross-type-leakage). `tipo = ambos` shows both compact labeled ranges, editable separately. |
| Percentile filter | Filtros panel | A `Preço no bairro` select: `entre os 25% mais baratos` / `entre os 50% mais baratos` / `qualquer preço` (default). The active value renders as one chip, composing under the 2-line ceiling. Cohorts are per listing type (BIN-77): switching tipo re-evaluates against that type's cohort. |
| Sentiment tag filters | Filter bar picker | `seguro` / `reformado` / `silencioso` are **starting suggestions, not a closed set** — the filter system handles an extensible, growing tag vocabulary. [NOTE FOR PRD] sentiment-dimension filters are UX-driven scope |
| Property card | Grid | Star (`{colors.favourite-star}`) and dismiss with **separated hit targets** — optimistic semantics, `desfazer` toast, and `descartados` recovery per Interaction Primitives. Price-drop badge is factual (`−8% desde julho`), anchored to the **max of the trailing 90 days** — never framed as a recommendation; on a rust-verdict card the verdict visually dominates. Freshness stamp (`visto hoje na OLX`); `2 fontes` badge when one Property is seen on two Platforms, annotated when one source is stale. Dual-type Properties render the primary listing (`utils/primaryListing.ts`) |
| Verdict + explainability | Card → detail side panel | Card shows the worded verdict (`{typography.verdict-label}`). In the side panel, the verdict expands: which signals (stat score, visual, sentiment, percentile) produced it — "why this verdict" in plain sentences |
| Detail side panel | Card / map point / alert click | One level deep; `Esc` closes. Open/close obeys the persistence contract (Interaction Primitives). Per-platform comparison shows each listing's own last-seen. Mock: [`mockups/key-detail-panel.html`](mockups/key-detail-panel.html) |
| Price-history chart | Detail side panel | Full available range by default; hover reveals date + price; per-platform series when `2 fontes`; drop markers plus the visible trailing-90-day anchor the badge measures from; a `voltou ao mercado` gap is bridged (dashed) and annotated, never silently interpolated |
| Recheck (`Verificar disponibilidade`) | Detail side panel, Favoritos | Result states and timestamps in State Patterns (Recheck states). `não foi possível verificar` is visually distinct from available and **never refreshes the freshness stamp** (Cloudflare/403/timeout = unknown, not availability). Per-listing cooldown (`verificado há 20 min`) plus a modest global recheck budget, both surfaced in the button state — rechecks burn the shared scraping identity. [NOTE FOR PRD] cooldown + recheck budget are UX-driven backend scope |
| Since-panel | Painel | Counts are scoped to **saved searches + favourites** (stated on the panel), and each count is a drill-in link applying a transient filter: `novos desde a última visita`, `quedas`, `saíram do ar`. Resets only after **~2 minutes of active use** — never on a glance; the panel states its window (`desde ter, 21h`). |
| Favoritos row | Favoritos | Comparable columns — price, verdict, percentile, R$/m², bairro — so two starred candidates read side by side without Comparar. Every row carries its availability stamp: `disponibilidade verificada há Xh` / `última verificação falhou`. Unstar is always **one click**; at that moment an **optional** reason may be attached (`banheiro pior que as fotos`) — never a mandatory note. Mock: [`mockups/key-favoritos.html`](mockups/key-favoritos.html) |
| Favoritos history | Favoritos | Default view = live favourites only. The `mostrar indisponíveis` filter reveals favourites that went `provavelmente alugado` / `provavelmente vendido` — each dated with when it left the market — and unstarred-with-reason favourites (reason shown). Gone favourites move here; they never silently vanish. |
| Alerts panel row | Alertas | Type icon, property line, timestamp; click opens the detail side panel and marks the alert read. Rows are history — they persist after the Property changes state |
| Saved-search row | Buscas salvas | Per-search notify-on-new-match toggle + inline **minimum-drop threshold** (threshold semantics in Notifications & Recall); alert state visible at a glance |
| Map | Painel split | **POI anchors** (Igreja, Casa dos pais, Casa da namorada) with **travel-time bands** (minutes, never km) [NOTE FOR PRD] POI layer is UX-driven scope. Hover sync is automatic and two-way: card hover highlights the pin, pin hover highlights the card (Zillow pattern). Map→list filtering is **explicit, only via the `filtrar pela área do mapa` toggle** — the active bbox renders as a removable `área do mapa ×` chip in the filter bar; panning alone never reshuffles the grid. Viewport and grid scroll follow the persistence contract (Interaction Primitives); the map never flickers or resets to a default position (fights the current UI's worst bug) |
| Health strip | Painel | Composition in Operator Observability below; chips are read-only here, click-through to Operações |

## State Patterns

Honest absence is the governing rule: what the pipeline doesn't know, the UI doesn't invent.

| State | Surface | Treatment |
|---|---|---|
| Cold load | Painel | Skeleton cards matching the grid layout (photo block + text lines), map rail placeholder — no spinner, no blank flash |
| Empty | Per surface | One plain pt-BR sentence each: grid zero matches `Nenhum imóvel corresponde aos filtros ativos.` · Favoritos `Nenhum favorito ainda — favorite um imóvel para começar.` · Buscas salvas `Nenhuma busca salva. Salve os filtros atuais para receber alertas.` · Alertas `Nenhum alerta por enquanto.` · first-ever-visit since-panel `Primeira visita — as novidades aparecem aqui a partir de agora.` |
| Grid fetch failure | Painel | Toast + last-good data retained (with its honest freshness stamps); with nothing cached, `Não foi possível carregar os imóveis.` + retry link — never a dead blank grid |
| Map tile failure | Map rail | `mapa indisponível no momento` in the rail; grid unaffected; viewport restored on recovery (persistence contract) |
| Enrichment pending | Card, side panel, map | Dashed tag `análise de IA pendente` (`{colors.pending}`); no verdict, no placeholder score; map point muted. Async by architecture (AD-4) — fresh listings are visibly un-enriched for a while |
| Verdict outdated | Card, side panel | On a material price change the verdict reverts to the dashed pending treatment until re-scored — a fresh drop badge never sits beside a verdict computed from the old price |
| Percentile suppressed | Card, side panel | Cohort below min size ⇒ percentile is null ⇒ badge simply **absent**. Never a fake "50%" |
| No active backfill | Operações | Throughput/ETA fields absent or null — **never fabricated** |
| Gone listing | Card, Favoritos | `provavelmente alugado — sem atualização há N dias` (aluguel) / `provavelmente vendido — …` (venda), dual-type follows the primary listing (`{colors.gone}`); photo desaturated; map point hollow. Excluded from default grid, visible via filter; a gone favourite moves to the Favoritos history (Component Patterns) — it never silently vanishes. **Heuristic:** gone counts only **successful coletas of that platform that did not include the listing**; skip-unchanged (FR-11) bumps last-seen |
| Recheck states | Side panel, Favoritos | `disponível` / `indisponível` / `não foi possível verificar`, each with its **own timestamp** (`verificado às 21:14` / `verificação falhou`); in progress = inline `verificando…` on the button, nothing blocks; `indisponível` flips the card to the gone treatment immediately |
| Voltou ao mercado | Card, side panel | A gone Property reappearing in a coleta clears the gone state, bridges + annotates the price-history chart, and is alert-worthy for previously starred items. [NOTE FOR PRD] resurrection transition is UX-driven scope |
| Staleness | Card | Freshness stamp degrades honestly: `visto hoje` → `visto há 3 dias` → `sem atualização há 14 dias` |
| Degraded platform set | Grid, health strip | Circuit-broken platform: remaining platforms' listings still shown; health chip reflects the degraded platform; that platform's cards show `plataforma sem coleta há N dias` **instead of** the gone treatment — an outage never mass-manufactures false deaths. Cloud→local enrichment degradation is invisible by design (FR-27) except for the backend chip changing |
| Health ok | Health strip | Green dot + last-run recency (`QuintoAndar · há 2h`) |
| Health anomaly | Health strip | Amber dot **with a reason string** (`OLX: coleta 5× mais rápida que a mediana`) — deviation from the scraper's own baseline; never a bare warning. No external notification for anomalies |
| Missed cadence | Health strip | Each scraper carries an expected-cadence contract; the chip goes amber on `sem coleta há 26h (esperado: a cada 6h)` — independent of run-level anomaly detection, so a scraper that stops running still turns amber |
| Baseline calibrating | Health strip, Operações | Below N historical coletas the chip shows `calibrando baseline (3/10 coletas)` — a distinct state, not ok-green |
| Backfill active | Health strip + Operações | An active backfill is operator-visible, always (AD-13 invariant); the front-door chip carries the warning glyph while running |

## Interaction Primitives

- **Non-blocking toasts** for API errors and conflicts (e.g. starting a backfill while the lease is held ⇒ toast naming the active run). Errors never block the grid.
- **Optimistic star and dismiss** — instant UI change, revert + toast on API failure. Dismiss always shows an immediate `desfazer` toast; recovery beyond the toast lives in the `descartados` view.
- **Persistence contract** (one rule, three surfaces): map viewport, grid scroll position, and filter state survive data refreshes and side-panel open/close; the map viewport also survives filter edits.
- Keyboard-friendly desktop patterns: `Esc` closes the side panel/filter panel; tab order follows reading order; the grid and pickers are operable without a mouse. [ASSUMPTION] no full shortcut map was decided — anything beyond these basics is implementation's call.
- Hover is enhancement only (pin highlight, card actions); every action has a click path.
- **Banned:** progress bars (everywhere — including coverage and backfill, which speak in text numbers and dates), blocking spinners over the grid, detail surfaces stacked deeper than one, auto-resetting map viewport, grid scroll loss on side-panel close.

## Accessibility Floor

Pragmatic for a personal tool — stated honestly:

- WCAG AA text contrast on the dark grounds — `DESIGN.md.Colors` carries the computed contrast table; the one flagged sub-AA pair (rust at 11px) is a documented exception with redundant state cues.
- Full keyboard operability of every surface.
- **No screen-reader investment** — single sighted user; ARIA beyond native semantics is explicitly out of scope.

## Key Flows

Protagonist: Felipe, in different modes. The anti-climax every flow fights: **stale availability** — a listing that looks good in the system but is gone at the source.

### J1 — A checagem da noite (Felipe the hunter, weekday evening — absorbs UJ-1)

1. Opens the Painel. Since-panel: `7 novos imóveis nos seus filtros · 3 quedas de preço · 2 anúncios saíram do ar — desde ter, 21h`. Each count is a link that applies its transient filter.
2. A drop card catches him: `−8% desde julho`, badge `entre os 25% mais baratos`, Savassi, `Excelente negócio`.
3. Opens the detail side panel: price-history chart (drop marker + 90-day anchor visible), verdict explainability ("why"), sentiment (`seguro`, `silencioso`).
4. The map rail is still visible beside the panel: the travel-time band shows the flat is within 15 min of the Igreja.
5. **Climax:** the `2 fontes` comparison shows QuintoAndar asking R$200 more than OLX for the same Property — each listing with its own last-seen, so he knows both sides of the gap are live — a negotiation lever. But is it still real? He hits **`Verificar disponibilidade`** and it comes back `disponível · verificado às 21:14`.
6. Stars it. The Property joins Favoritos — where **automatic priority rechecks** (daily) will keep watching its availability, so a favourite never goes stale unnoticed. [NOTE FOR PRD] recheck actions (on-demand + auto-verify for favourites) are UX-driven backend scope.

**Failure:** the recheck returns `indisponível` — the card flips to the gone treatment on the spot and a toast says `anúncio saiu do ar`; no stale hope survives the evening. If it returns `não foi possível verificar`, the unknown state renders distinctly and the freshness stamp stays untouched — "I checked" is never faked.

### J2 — O alerta que valeu (Felipe interrupted, ~90 seconds — absorbs UJ-2)

1. Email (the guaranteed interrupt channel — Notifications & Recall): saved search `2 quartos Savassi até R$ 3.000` has a new match. The alert **waited for enrichment** (Notifications & Recall), so it arrives decidable.
2. Clicks straight into the detail side panel — no grid detour.
3. Verdict, percentile sentence, photos — ready on arrival by construction, not by luck.
4. **Climax:** stars it and closes. Ninety seconds from alert to favourite — the alert paid for its interruption.

The price-drop variant follows the same shape but lands on the price-history chart, drop marker and anchor in view — the confirmation beat of UJ-2.

**Failure:** the listing died between alert and click — the side panel opens in the gone treatment (`provavelmente alugado — …`) instead of pretending; the alert row remains in Alertas as history.

### J3 — O operador desconfiado (Felipe the operator, something feels off — absorbs UJ-3 + UJ-4)

1. Health strip: OLX chip shows `há 26h` against its expected cadence and an amber anomaly chip — `coleta 5× mais rápida que a mediana`.
2. Into Operações: the run-history table compares the suspect coleta against its own baseline — duration, yield, deviation.
3. Worker row shows the error; he re-triggers the scrape.
4. **Climax:** the fresh coleta lands inside its baseline band — green again, and he knows *why* it was amber, not just that it was.
5. On the way out, a glance at the backfill card: `em execução · dia 3 de ~6 · 61% da cota de hoje` — running, paced, nothing to do.

### J4 — A triagem dos favoritos (Felipe curating his favourites — new UX-driven scope)

1. Opens Favoritos: starred Properties in comparable rows, each stamped `disponibilidade verificada há 3h` by the automatic rechecks — a failed overnight batch would say `última verificação falhou`, never look identical to a verified one.
2. The favourite-gone alert already warned him by email: one favourite went `provavelmente alugado` overnight. Under the `mostrar indisponíveis` filter it sits in the history — dated, its alert noted — instead of silently vanishing.
3. The comparable rows answer A-vs-B directly — price, verdict, percentile badge, R$/m², bairro side by side — no Comparar detour.
4. **Climax:** the weaker of two candidates loses: one click unstars it, and he attaches an optional reason while the impression is fresh (`banheiro pior que as fotos`). It lands in the filterable history, reason shown. What remains on the live list is verified, comparable, and still real — availability truth, not stale hope.

**Failure:** the overnight recheck batch failed — every affected row shows `última verificação falhou` in its own amber state; nothing wears a verified stamp it didn't earn.

## Operator Observability

Split in two: a glanceable strip on the front door, depth in Operações. Key mock: [`mockups/key-operacoes.html`](mockups/key-operacoes.html).

**Health strip (Painel, always visible):**

- One chip per scraper: status dot + last-run recency; the ok / anomaly-vs-own-baseline / missed-cadence / calibrating semantics and strings live in State Patterns.
- Enrichment backend chip: cloud/local + model name (`local — qwen2.5-vl`).
- Workers chip: ok / error.
- **Coverage % as text** (`Cobertura de IA 82%`) — coverage-as-SLO on the front door; the number is the **minimum across signal types** (FR-29), labeled as such on hover; per-type detail in Operações. Derived from the DB, the single progress truth — runner Redis checkpoints are never a second metric.
- Backfill chip: per State Patterns (Backfill active) — any glance at the dashboard says "não rode validate agora".

**Operações:**

- **Run-history table** [NOTE FOR PRD] scraper run-history behavioral analytics are UX-driven scope: per coleta — duration, yield (processed/included/excluded/updated), deviation from that scraper's own rolling baseline **and** from a pinned long-window baseline, so gradual drift can't rot the comparison; drift beyond the pinned band over weeks is itself a reason string. "Finished too early" is a first-class signal, not a hunch.
- **Backfill card:** states render pt-BR — `inativo / em execução / pausado / em espera (limite da API)` (the wire enum stays `idle/running/paused/backing-off`); today's budget use; throughput; **day-scale ETA** (multi-day is normal: ~4,600 properties/day on free-tier pacing); start/pause/resume (no-run absence per State Patterns). While running, a persistent warning line makes the validate/migration collision risk unmistakable — noting that the *real* guard is the shell-side heartbeat (`backfill:gemma:active`) that `migrate-primary.sh` respects; the UI line is a reminder, not the lock ([ASSUMPTION] warning-line presentation — visibility is mandated by FR-28/AD-13, the form was not designed in session).
- **Coverage per signal type (FR-29):** the coverage detail breaks out per signal type (visual, sentiment, valuation, embeddings); the front-door % is the minimum of these.
- **Ingest counts:** recent included / excluded / updated counts.
- **Dedupe stats:** Properties seen by two Platforms, **with the record differences between the two sources** (price gap, description drift) — the same diffs that power the `2 fontes` negotiation lever in J1.
- **POI management:** POI CRUD is a minimal form here (name, point, band minutes) [ASSUMPTION] — the map consumes, Operações administers.
- Manual scrape trigger; queue/GPU status.

## Notifications & Recall

Two complementary systems: alerts push what he asked for; the front door catches what he didn't.

- **Channels:** email + in-app (Alertas bell/panel) + desktop push. **Email is the guaranteed interrupt channel; desktop push is an opportunistic bonus** — on a localhost deployment push only fires while the browser runs, so nothing critical rides on it alone. **No Telegram.** Weekly digest rides email (FR-21).
- **Saved-search new-match alerts:** per-search toggle (all-or-nothing is banned); only genuinely new Properties fire; each search × property pair notifies at most once. Alerts **wait for enrichment** — they fire only when verdict and percentile exist, so every alert click lands on a decidable panel.
- **Price-drop alerts:** threshold-gated — below the configured minimum drop, no alert (noise control). The threshold lives **per saved search / watch**, beside its notify toggle — no global setting. Every alert email states the threshold that fired it (`queda de R$ 240 — seu mínimo: R$ 100`), so even a default threshold is visible and correctable. **Starred = watched: there is no separate watchlist** — FR-16's watchlist is the starred set.
- **Favourite-gone alerts:** the third first-class alert — when a recheck or coleta finds a starred item gone, email + push fire, **on by default for starred items**. A `voltou ao mercado` resurrection of a previously starred Property is likewise alert-worthy. [NOTE FOR PRD] favourite-gone + resurrection alerts are UX-driven scope.
- **Batching:** email new-match alerts batch into one daily window per search — an absent week never becomes 40 single emails; the weekly digest **excludes already-alerted Properties**, so nothing is delivered twice.
- **Since-panel:** the passive complement — new matches, drops, and gone listings accumulated since the last real visit, scoped to saved searches + favourites, covering everything the alerts didn't push. Reset and drill-in semantics in Component Patterns.
- **Recent-filter recall:** recently used neighbourhoods, property types, and price ranges resurface as reuse suggestions inside the filter pickers. [NOTE FOR PRD] UX-driven scope.

---

*Deliberate non-designs (decided, not forgotten):* Comparar stays minimal (no journey; Favoritos' comparable rows carry the A-vs-B need). Semantic search (FR-15) keeps its existing surface as-is — pt-BR queries, no redesign this pass. Export UI (FR-21) and the auth/API-key management surface (FR-19) are **explicitly deferred** — export stays API/digest-only and auth stays the current key gate until a future pass designs them.
