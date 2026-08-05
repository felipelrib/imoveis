---
name: imoveis
description: Visual identity for the Imoveis deal-tracker frontend — dark-only "Meia-noite" palette on a warm-craft × editorial hybrid.
status: final
created: 2026-08-05
updated: 2026-08-05
colors:
  # Meia-noite (round-2 variation 4) — semantic roles + scrim utility + blend variants.
  # Several roles deliberately share a hex (green = excellent = drop = ok;
  # rust = above-market = gone) — shared meaning, shared ink.
  # Gold belongs to the favourite star alone; health-warn is its own orange-amber.
  background: '#0e1220'
  surface-card: '#151a2b'
  surface-elevated: '#1e2438'
  border-hairline: '#2b3350'
  text-primary: '#e9e9e2'
  text-secondary: '#a3a5ad'
  text-muted: '#82859a'
  accent: '#4da3ff'
  favourite-star: '#d9b35f'
  price-drop: '#74bd82'
  verdict-excellent: '#74bd82'
  verdict-good: '#d3b662'
  verdict-market: '#8b8e99'
  verdict-above: '#d05b4a'
  pending: '#82859a'
  gone: '#d05b4a'
  health-ok: '#74bd82'
  health-warn: '#d98d3f'
  poi-pin: '#4da3ff'
  scrim: '#0e1220d9'
  # Blend variants (8-digit alpha over their stated ground; flattened hex in comment).
  price-drop-tint-12: '#74bd821f'  # percentile-badge bg — flattens to #202e35 over surface-card
  price-drop-tint-35: '#74bd8259'  # percentile-badge border — flattens to #365349 over surface-card
  surface-health-chip: '#121626'   # surface-card blended 50% toward background
  surface-since-panel: '#1a1f32'   # surface-elevated blended 50% toward surface-card
typography:
  # Two families only, both system stacks (no webfont dependency) — as mocked.
  display-price:
    fontFamily: 'Georgia, "Iowan Old Style", "Palatino Linotype", "Book Antiqua", serif'
    fontSize: 26px
    fontWeight: '400'
  display-neighbourhood:
    fontFamily: 'Georgia, "Iowan Old Style", "Palatino Linotype", "Book Antiqua", serif'
    fontSize: 16px
    fontWeight: '400'
    note: 'Italic. Serif is reserved for price + neighbourhood name — nowhere else.'
  verdict-label:
    fontFamily: '"Seravek", "Segoe UI", system-ui, -apple-system, "Helvetica Neue", sans-serif'
    fontSize: 11px
    fontWeight: '400'
    letterSpacing: 0.2em
    note: 'Uppercase, 2px underline in the verdict colour.'
  body:
    fontFamily: '"Seravek", "Segoe UI", system-ui, -apple-system, "Helvetica Neue", sans-serif'
    fontSize: 14px
    lineHeight: '1.55'
  meta:
    fontFamily: '"Seravek", "Segoe UI", system-ui, -apple-system, "Helvetica Neue", sans-serif'
    fontSize: 12.5px
    letterSpacing: 0.03em
  label-caps:
    fontFamily: '"Seravek", "Segoe UI", system-ui, -apple-system, "Helvetica Neue", sans-serif'
    fontSize: 10.5px
    fontWeight: '600'
    letterSpacing: 0.16em
    note: 'Uppercase section/filter labels.'
rounded:
  sm: 7px
  md: 9px
  DEFAULT: 10px
  lg: 12px
spacing:
  # [ASSUMPTION] scale formalized from mock pixel values (4-based).
  '1': 4px
  '2': 8px
  '3': 12px
  '4': 16px
  grid-gap: 18px
  split-gap: 26px
  page-margin: 48px
components:
  property-card:
    background: '{colors.surface-card}'
    border: '1px solid {colors.border-hairline}'
    radius: '{rounded.DEFAULT}'
    shadow: '0 8px 20px #00000055, inset 0 1px 0 #ffffff08'
  verdict-label:
    typography: '{typography.verdict-label}'
    underline: '2px solid — verdict colour'
  percentile-badge:
    foreground: '{colors.price-drop}'
    background: '{colors.price-drop-tint-12}'
    border: '1px solid {colors.price-drop-tint-35}'
    radius: '{rounded.sm}'
  price-drop-badge:
    foreground: '{colors.price-drop}'
    background: '{colors.scrim}'
    note: 'Italic, on-photo. Factual price fact, never a recommendation; verdict dominates.'
  sources-badge:
    typography: '{typography.label-caps}'
    background: '{colors.scrim}'
    note: '"2 fontes" — on-photo, top-left.'
  freshness-stamp:
    foreground: '{colors.text-secondary}'
    background: '{colors.scrim}'
    note: '"visto hoje na OLX" — on-photo, bottom-right.'
  favourite-star:
    active: '{colors.favourite-star}'
    inactive: '{colors.text-secondary}'
  filter-chip:
    border: '1px solid {colors.border-hairline}'
    active-border: '{colors.accent}'
    active-foreground: '{colors.accent}'
    radius: '{rounded.md}'
  health-chip:
    background: '{colors.surface-health-chip}'
    border: '1px solid {colors.border-hairline}'
    radius: '{rounded.md}'
    dot-ok: '{colors.health-ok}'
    dot-warn: '{colors.health-warn}'
  pending-tag:
    foreground: '{colors.pending}'
    border: '1px dashed {colors.pending}'
    note: 'Dashed border, no fill — visibly "not yet".'
  poi-pin:
    fill: '{colors.poi-pin}'
    shape: 'teardrop (50% 50% 50% 4px)'
  map-point:
    note: 'Circle tinted by verdict colour; pending = muted; gone = hollow + desaturated; hover = accent ring.'
  since-panel:
    background: '{colors.surface-since-panel}'
    border: '1px solid {colors.border-hairline}'
    radius: '{rounded.lg}'
  detail-panel:
    background: '{colors.surface-elevated}'
    border-left: '1px solid {colors.border-hairline}'
    note: 'Side panel over a partial scrim; map rail stays visible. One level deep.'
  toast:
    background: '{colors.surface-elevated}'
    border: '1px solid {colors.border-hairline}'
    radius: '{rounded.md}'
    shadow: '0 8px 20px #00000055'
    note: 'Bottom of viewport; text + optional accent action (`desfazer`). Never blocks the grid.'
---

## Brand & Style

Imoveis is a private night desk for hunting a home: a deal journal read after work, on one dark screen, by one person. The character is a hybrid — **warm-craft** base (tactile cards with real shadows, soft 10px corners, tabular numbers, workshop-bench health chips) carrying an **editorial** card anatomy (photograph dominating the card, price set in a display serif, judgment spoken in words, not meters).

The stance is deliberately anti-"AI-designed": no gradients, no neon glow, no progress bars, no dashboards of gauges. Colour never paints panels — it underlines words and tints dots. The midnight-blue ground is bold and cool; the gold favourite star and the warm verdict scale hold the human side.

Dark-only. There is no light theme and none is planned.

Visual provenance: token hexes come from the Meia-noite variation in [`mockups/palette-meia-noite.html`](mockups/palette-meia-noite.html); the structural parents are [`mockups/direction-warm-craft.html`](mockups/direction-warm-craft.html) and [`mockups/direction-editorial.html`](mockups/direction-editorial.html). Spine wins on conflict.

## Colors

The Meia-noite palette: a midnight-blue ground with one electric interactive colour and a small set of warm semantic inks.

- **Background (`{colors.background}`)** — the page. Midnight blue, not black; everything sits on it tonally.
- **Surface card (`{colors.surface-card}`) / elevated (`{colors.surface-elevated}`)** — cards and raised chrome. Depth comes from these two tones plus shadow, never from colour.
- **Border hairline (`{colors.border-hairline}`)** — the only line weight. 1px, always.
- **Text (`{colors.text-primary}` / `{colors.text-secondary}` / `{colors.text-muted}`)** — warm off-white primary keeps the cold ground from feeling clinical.
- **Accent (`{colors.accent}`, electric azure)** — interactive things only: links, active filter chips, focus, map hover, POI pins (never alert, state, or verdict — see Do's and Don'ts).
- **Favourite star (`{colors.favourite-star}`, gold)** — exclusively the star and the Favoritos surface it feeds. Gold means "mine".
- **Price drop (`{colors.price-drop}`, green)** — good price news, stated **factually**, never framed as a buy signal or recommendation. Distinct by rule from every warning colour; a drop badge must never read as caution — and on an `Acima do mercado` card the rust verdict visually dominates the badge (a drop on an overpriced listing is a correction, not a deal).
- **Verdict scale** — the four worded deal verdicts, underline ink only:
  - `Excelente negócio` `{colors.verdict-excellent}` (green)
  - `Bom preço` `{colors.verdict-good}` (warm gold)
  - `Preço de mercado` `{colors.verdict-market}` (neutral grey)
  - `Acima do mercado` `{colors.verdict-above}` (rust — warm negative, never the accent's blue and never a pure alarm red)
- **Pending (`{colors.pending}`)** — the muted text tone, rendered dashed. Absence of judgment, not a fifth verdict.
- **Gone (`{colors.gone}`)** — `provavelmente alugado` / `provavelmente vendido` (per listing type) shares rust with the negative pole: the listing has left the market.
- **Health ok / warn (`{colors.health-ok}` / `{colors.health-warn}`)** — operator strip dots. Warn is its **own orange-amber** (`#d98d3f`) — deliberately distinct from the favourite star's gold and from `verdict-good` — reserved for anomaly-with-reason; it never borrows the rust of verdicts.
- **POI pin (`{colors.poi-pin}`)** — personal anchors on the map share the accent: they are *your* interactive geography.
- **Scrim (`{colors.scrim}`)** — translucent ground for on-photo labels; the only overlay treatment.

**Contrast (WCAG 2.1, computed against the token hexes):**

| Pair | Ratio | Verdict |
|---|---|---|
| `text-primary` on `background` / `surface-card` | 15.3 / 14.2 | AAA |
| `text-secondary` on `background` / `surface-card` | 7.6 / 7.0 | AAA |
| `text-muted` on `surface-card` (12.5px meta) | 4.8 | AA — small-text floor; do not darken further |
| `accent` on `background` / `surface-card` | 7.1 / 6.6 | AA |
| `verdict-excellent` / `good` / `market` on `surface-card` (11px labels) | 7.7 / 8.8 / 5.3 | AA |
| `verdict-above` + `gone` (rust) on `surface-card` (11px labels) | 4.3 | **Sub-AA at small sizes — known exception.** Tolerable only because the state is carried redundantly (underline + desaturated photo + copy); a future palette pass should lift rust toward ≥ 4.5 |
| `health-warn` on `surface-card` | 6.5 | AA |
| `favourite-star` on `surface-card` | 8.7 | AAA |

On-photo scrim minimum: `{colors.scrim}` (`#0e1220` at ~85% alpha) composites to `#323541` or darker even over a pure-white photo — worst-case ratios: `text-secondary` ≥ 5.0, `text-primary` ≥ 10.0, `price-drop` ≥ 5.4. The AA floor holds for all on-photo labels.

## Typography

Two families, both system stacks — nothing loaded from the network.

- **Serif display (Georgia stack)** is the editorial voice, reserved for exactly two things: the **price** (`{typography.display-price}`, tabular numerals) and the **neighbourhood name** (`{typography.display-neighbourhood}`, italic). The serif is the magazine moment on each card; using it elsewhere dilutes it.
- **Sans (Seravek/Segoe/system stack)** is everything else: body, labels, chips, verdicts, Operações tables.
- **Verdict labels** (`{typography.verdict-label}`): uppercase, tracked wide, 2px underline in the verdict colour. The word carries the judgment; the colour only underlines it.
- **Numbers** are always tabular (`font-variant-numeric: tabular-nums`) — prices, counts, percentages, timestamps align in columns.

No display sizes beyond the price; no webfonts; no monospace in the product surface.

## Layout & Spacing

Desktop-only, one fixed comfortable frame (~1440px content width, `{spacing.page-margin}` side margins). The dashboard is a **split view**: card grid left, map rail right (~460px), gap `{spacing.split-gap}`. Cards flow in a 2-column grid with `{spacing.grid-gap}` gaps.

Vertical order on the front door: top nav → since-panel → health strip → filter bar → split grid/map. The filter bar has a hard 2-line height ceiling — the layout above the grid never grows past it.

Spacing follows the 4-based scale; card interiors use `{spacing.4}` padding. Breathing room is editorial (generous between cards), density is craft (tight inside a card).

## Elevation & Depth

Depth is **tonal layering plus real shadow** — surfaces step `{colors.background}` → `{colors.surface-card}` → `{colors.surface-elevated}`, and raised objects cast a soft true shadow (`0 8px 20px #00000055`) with a 1px inset top highlight (`#ffffff08`) that reads as workshop light on an object. No glow, no coloured shadows.

Photos carry a bottom scrim fade into the card so on-photo labels stay legible; this functional scrim is the only gradient permitted in the system.

The detail surface is a **side panel** (`{components.detail-panel}`): it slides in from the right over a **partial** `{colors.scrim}` overlay that covers the grid only — the map rail stays visible beside it. One level deep, never stacked; there are no centered modals in the system.

## Shapes

Rounded, never bubbly. Cards and panels `{rounded.DEFAULT}` (10px); chips and health capsules `{rounded.md}`; small badges/tags `{rounded.sm}`; the since-panel and map frame `{rounded.lg}`. No pills (`9999px`) on surfaces or chips — pill shapes read "consumer app", this is a craftsman's tool. Circles exist only where the shape *is* the meaning: map points, health dots. POI pins are teardrops.

Imagery follows its container's radius exactly.

## Components

Canonical component renderings: [`mockups/key-painel.html`](mockups/key-painel.html) (Painel/card grid), [`mockups/key-detail-panel.html`](mockups/key-detail-panel.html) (detail side panel), [`mockups/key-operacoes.html`](mockups/key-operacoes.html) (Operações), [`mockups/key-favoritos.html`](mockups/key-favoritos.html) (Favoritos).

- **Property card** — photo on top (~50–60% of card height, scrim-faded at the bottom); on-photo: sources badge (top-left, `2 fontes` when cross-platform), star + dismiss actions (top-right, **separated hit targets** — enough gap that a star tap can never land on dismiss), price-drop line (bottom-left, italic green), freshness stamp (bottom-right). Card body: verdict label with underline → serif price line with percentile badge right-aligned → serif italic neighbourhood → sans meta line (`2 quartos · 68 m² · QuintoAndar + OLX`).
- **Verdict label** — one of the four worded verdicts, `{typography.verdict-label}`, 2px underline. Pending replaces it with italic lowercase `análise de IA pendente` in `{colors.pending}`, no underline, no uppercase.
- **Percentile badge** — compact chip, `entre os 25% mais baratos`, tinted `{colors.price-drop-tint-12}` with a `{colors.price-drop-tint-35}` border. Absent entirely when suppressed.
- **Gone card** — photo desaturated/darkened (`grayscale ~0.7, brightness ~0.75`), caption at ~65% opacity, rust italic note per listing type: `provavelmente alugado — sem atualização há 14 dias` (aluguel) / `provavelmente vendido — …` (venda); dual-type Properties follow the primary listing. No verdict shown.
- **Detail side panel** — `{components.detail-panel}`: right-side panel over a partial scrim (grid dimmed, map rail visible); hairline left border, real shadow. Interior: photos → verdict + explainability → price-history chart → per-platform comparison → sentiment → recheck + star. One level deep.
- **Price-history chart** — line chart on `{colors.surface-card}`; hairline axes in `{colors.border-hairline}`; per-platform series in platform-neutral inks (`{colors.text-secondary}` solid for the primary series, dashed for the second — never verdict colours); drop markers as small dots with date labels; the trailing-90-day anchor marked visibly; a `voltou ao mercado` gap bridged by a dashed segment with an annotation. No area fills, no gradients — same dataviz posture as the no-progress-bars rule.
- **Filter chip** — hairline border, accent border + text when active, `×` to remove. Segmented control (Aluguel/Venda) fills the active segment with `{colors.accent}`.
- **Health chip** — capsule with status dot; ok dot green, warn dot amber followed by an italic amber reason string. Coverage renders as **text percentage only** — no track, no bar.
- **Since-panel** — elevated panel (`{colors.surface-since-panel}`), uppercase label in `{colors.verdict-good}` (the shared warm-gold ink — a label tint here, not a verdict claim), three count items in bold with plain sentences; each count is a drill-in link; a small window statement (`desde ter, 21h`) in `{typography.meta}`.
- **Map** — dark ground; verdict-tinted listing dots with hairline dark outline; gone points hollow + desaturated; teardrop POI pins with labeled scrim capsules; dashed travel-time band outline in POI colour with a solid label chip; legend lists the four verdicts + pending, and gains a gone entry whenever the gone filter is active.
- **Backfill card** — Operações; `{colors.surface-card}`, hairline border, `{rounded.DEFAULT}`; state word in `{colors.text-primary}` (`inativo / em execução / pausado / em espera (limite da API)`); budget/throughput/ETA as tabular text lines, simply absent when there is no active run; while running, a persistent warning line in `{colors.health-warn}` with a warning glyph. No bars.
- **Run-history table** — Operações; sans, tabular numerals, hairline row separators only (no zebra fills); columns for duration, yield, deviation as signed text; anomaly rows carry the italic `{colors.health-warn}` reason string; baseline-calibrating rows use `{colors.pending}`. No sparklines, no bars.
- **Toast** — `{components.toast}`: bottom-anchored capsule, body text + optional accent action (`desfazer`); auto-dismisses; stacks at most two; never covers the filter bar.
- **Saved-search row** — `{colors.surface-card}` row, hairline separators; search name in body type, filter summary in `{typography.meta}`; notify toggle and inline drop-threshold value in accent when interactive.
- **Alerts-panel row** — hairline-separated rows; type icon in the semantic ink (green drop, accent new-match, rust gone); property line + timestamp (`há 2h`) in `{colors.text-muted}`; unread rows use `{colors.text-primary}`, read rows `{colors.text-secondary}`. Click opens the detail side panel.
- **Buttons/links** — accent text or accent-filled small buttons on dark; no gradient fills, no outlined ghost hierarchy games.

## Do's and Don'ts

| Do | Don't |
|---|---|
| Speak verdicts in words with a 2px coloured underline | Fill areas, badges, or bars with score colour, or add a fifth verdict colour |
| Green (`{colors.price-drop}`) exclusively for good price news — drops, `Excelente negócio`, health ok | Use green for anything neutral, or amber/rust for a drop |
| Keep `{colors.accent}` for interaction only | Let the accent mean state, alert, or verdict |
| Serif for price + neighbourhood only, tabular numerals everywhere | Serif body text, proportional digits in columns |
| Real shadows + tonal steps for depth | Glow, neon, chromatic gradients, coloured shadows |
| Render absence honestly: dashed pending tag, missing percentile badge, absent ETA | Progress bars, placeholder values, fake "50th percentile" |
| Rust (`{colors.verdict-above}`) for the negative pole and gone state | A pure alarm red anywhere on the surface |
| Gold star = favourite, and nothing else | Gold for warnings (health warn is its own amber role) |
| Plain-language percentile copy (`entre os 25% mais baratos`) | Statistician notation (`P25`, `≤ P25`, "percentil") — or any phrasing without the cheap-direction word |
