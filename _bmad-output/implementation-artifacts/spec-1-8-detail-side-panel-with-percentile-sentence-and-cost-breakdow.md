---
title: 'Story 1.8 — Detail side panel with percentile sentence and cost breakdown'
type: 'feature'
created: '2026-10-08'
status: done
baseline_revision: 'a3c37e283ae89a6f1aede3dd2d6b181c5627b7f1'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-imoveis-2026-08-05/mockups/key-detail-panel.html'
  - '{project-root}/docs/features/v0.14-s1.7-percentile-badge-and-filter.md'
warnings: ['oversized']
deferred:
  - summary: >-
      The split grid / map layout of DESIGN.md does not exist, so the contract state "grid dimmed
      under the scrim with the map rail visible beside the panel" cannot occur.
    evidence: |-
      frontend/src/pages/Properties.tsx shows the grid or the map (viewType toggle), never both.
      DESIGN.md (ux-imoveis-2026-08-05, "Layout" and line 219) describes a split front door and a
      scrim that covers the grid only. Story 1.8 delivers the panel on the layout that exists: in
      grid view the scrim dims the grid and no map is on screen; in map view there is no scrim and
      the panel covers the right part of the map (including its zoom control). No story in
      epics.md owns the split layout.
    location: >-
      frontend/src/pages/Properties.tsx:571
    severity: medium
  - summary: >-
      Map points probably do not draw since the maplibre-gl 6 upgrade: the worker script the
      library loads is not served by the Vite dev server and is not emitted by the production build.
    evidence: |-
      Unverified at runtime in production. Observed by the dev session under the Vite dev server:
      GET /node_modules/.vite/deps/maplibre-gl-worker.mjs answers 404 and the GeoJSON point layer
      never renders (raster tiles and the HTML compare markers do). Read in
      frontend/node_modules/.vite/deps/maplibre-gl.js:18442-18447: the worker URL is built at run
      time as new URL('./maplibre-gl-worker.mjs', import.meta.url), which a bundler cannot see.
      frontend/dist/assets after `vite build` holds no worker file. What would settle it: open the
      map view on the primary stack and look for points and for a 404 on maplibre-gl-worker.mjs.
      If confirmed, clicking a point (one of the three ways into the detail panel) is unavailable.
      Not caused by Story 1.8 (MapView.tsx and vite.config.js untouched; upgrade was 6b57551e).
    location: >-
      frontend/src/components/MapView.tsx:387
    severity: high (unverified)
  - summary: >-
      A favourite's card shows no percentile badge while its detail panel states the sentence,
      because the favourites endpoint does not serve the price_per_m2_percentile fields.
    evidence: |-
      Properties.tsx builds Favoritos cards from GET /favourites items (a partial Property without
      price_per_m2_percentile_rent/_sale); the panel reads GET /properties/{id}, which has them.
      The rule "sentence exactly when the card has a badge" therefore holds on the Imóveis grid
      and not on Favoritos. Story 1.7 noted the missing fields; Story 5.10 owns the Favoritos
      columns. Fixing it is an API change (favourites projection), outside this frontend story.
    location: >-
      frontend/src/pages/Properties.tsx:450
    severity: low
  - summary: >-
      The save-search dialog and the compare view are still centered or full-screen overlays,
      while DESIGN.md says the system has no centered modals.
    evidence: |-
      Story 1.8 retired the detail modal only. The save-search dialog (Properties.tsx, classes
      .dialog-overlay / .dialog, legacy glass palette) is a centered dialog, and CompareView.tsx
      is a full-screen role="dialog" aria-modal overlay. DESIGN.md line 219: "there are no
      centered modals in the system". Story 1.10 (saved-search alert management UI) touches the
      saved-search surface; no story names the compare view.
    location: >-
      frontend/src/pages/Properties.tsx:668
    severity: low
  - summary: >-
      validate.py accepts a backend stamp for a diff that requires the frontend tier, so a
      frontend-only change can be pushed without eslint, the Vite build or the e2e suite having run.
    evidence: |-
      scripts/agent/validate.py:58 orders TIERS docs < fast < frontend < backend < full and
      check_stamp (lines 326-332) accepts any stamp of equal or higher rank; the backend tier does
      not run gate.frontend() (lines 605-609). .bmad-loop/policy.toml runs the backend tier as
      [verify]. Same family as DW-51, which records the loop's verify tier; this is the stamp rule
      itself. Not caused by Story 1.8, whose diff requires and was validated at the full tier.
    location: >-
      scripts/agent/validate.py:326
    severity: medium
  - summary: >-
      In the grid view the page under the detail panel's scrim is dimmed and closed to the pointer
      but still reachable with the keyboard, so focus can sit on a card or filter that is hard to see.
    evidence: |-
      frontend/src/components/detail/PropertyDetailPanel.tsx renders the scrim as an aria-hidden
      div and makes nothing inert (a recorded decision: the panel is not a dialog, and in the map
      view the page must stay usable). The scrim ink is #0e1220d9 (85% opaque). Shift+Tab from the
      panel moves focus to the last control of the page under it; Enter on a card there swaps the
      panel content. Nothing is trapped and Esc still closes. A fix makes the grid and the
      saved-search sidebar inert while the scrim is drawn (grid view only), which changes the
      recorded "nothing is made inert" decision and the focus-restore timing, so it is not a patch.
      Found by the follow-up review of Story 1.8.
    location: >-
      frontend/src/components/detail/PropertyDetailPanel.tsx:98
    severity: low
  - summary: >-
      The price-history chart labels its Y axis in whole thousands, so a rent series between
      R$ 3.000 and R$ 3.200 shows the same tick text (R$3k) on every tick.
    evidence: |-
      frontend/src/components/detail/PriceHistorySection.tsx: tickFormatter is
      `R$${(v / 1000).toFixed(0)}k`, carried over unchanged from the retired PropertyModal.tsx
      (main, line 690), so the defect predates Story 1.8. CompareView.tsx has its own chart. The
      mock (key-detail-panel.html) labels the axis R$ 2.9k / R$ 2.65k / R$ 2.45k. The tooltip
      shows the exact value. A fix formats values below 10.000 in full or with decimals and has
      to check the axis width for sale prices.
    location: >-
      frontend/src/components/detail/PriceHistorySection.tsx:60
    severity: low
---

<intent-contract>

## Intent

**Problem:** A property opens in a centered modal that hides the grid and the map, is styled with the legacy glass palette, labels the legacy `percentile_rank*` as "Percentil" (forbidden by UX-DR8), and shows cost from the legacy `base_price` / `condo_fee` / `iptu` fields instead of the stored Total Monthly Cost of Story 1.2.

**Approach:** Replace the modal with the contract's right-side detail panel (UX-DR4): same content, Meia-noite tokens, built from independent sections so Stories 3.9, 5.9 and 5.8 add to it without rewriting it. The panel states the Story 1.7 percentile as a sentence and itemizes each Listing's stored cost. The modal component, its styles, its catalog keys and its test selectors are removed; its e2e specs are migrated.

## Boundaries & Constraints

**Always:**
- Frontend only. Every figure is read from the projection (`listings[].cost`, `deciding_listing_id`, `price_per_m2_percentile_*`); nothing is summed, defaulted or derived from legacy price fields.
- The sentence uses `badgePercent` / `pricePercentileForType` from `frontend/src/utils/percentile.ts`: present exactly when the card badge is present, same N.
- Dual-type Property (Listings of both types) names the cohort type in the sentence; single-type keeps the short form.
- `unknown` cost component reads "não informado", never 0 or a dash; a bundled figure is one labelled row; an incomplete total shows no number.
- Panel: right side, partial scrim, one level deep, `Esc` closes, URL stays `/properties/:id`. Opening and closing never refetches the list, never moves window scroll, never remounts the map, never changes filter state.
- Meia-noite tokens only (`.meia`), serif only for price and neighbourhood name, tabular numerals, no pills, no progress bars, no blocking spinner. Strings in both catalogs; wire values stay English.
- After the change no source, style, catalog key or e2e selector named after the modal remains unless something uses it.

**Never:**
- No change to `src/api/`, `src/core/`, contract tests or `sprint-status.yaml`. The legacy `percentile_rank*` stay on the wire (export CSV, contract test and `docs/api.md` still carry them); the panel stops reading them.
- No attributes-with-provenance section (3.9), availability recheck (5.9) or alert entry point (5.8).
- No split grid/map layout, no card restyle, no new microcopy for properties above the badge cutoff.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Single-type, percentile 0.2001 | rent Listings only, `price_per_m2_percentile_rent: 0.2001` | Sentence `entre os 21% mais baratos do bairro`; header badge `entre os 21% mais baratos` | — |
| Dual-type | rent 0.25, sale 0.4 | `…25% mais baratos dos aluguéis do bairro` and `…40% mais baratos das vendas do bairro` | — |
| Dual-type, one suppressed | rent 0.25, sale null | Only the rent sentence, still naming `dos aluguéis` | — |
| Suppressed or above cutoff | null, or 0.51 | No sentence and no badge element | — |
| Complete cost | rent 3000, condo 495, IPTU 165, total 3660, `complete` | Four rows with those figures | — |
| Unknown component | `iptu_state: unknown`, total null | IPTU row `não informado`; total row `incompleto`, no number | — |
| Bundled | `fees_bundled`, combined 179 in `condo_fee_monthly`, total 929 | One row `Condomínio + IPTU` 179 labelled as a single published figure; no separate IPTU row; total 929 | — |
| Annual IPTU | `iptu_periodicity_source: annual` | IPTU row carries a "converted from annual" note | — |
| Sale Listing | `rent_state` / `total_state` `not-applicable` | Condo and IPTU rows only, no rent row, no total row | — |
| Listing without `cost` | older payload | That Listing has no cost block; section absent when none has one | — |
| Detail fetch fails | 404 / 500 | Error text inside the panel; page stays intact; close works | No throw |

</intent-contract>

## Code Map

- `frontend/src/components/PropertyModal.tsx` -- DELETE. Source of the content to carry: header (price, title, star, watch control with drop % input, per-listing links, BIN-158 fallback link via `sanitizeListingUrl` / `platformFallbackUrl`), gallery, facts rows (lines 159-229, legacy percentile rows 203-227 to drop), listings table with legacy Base/Condo/IPTU columns and furnished/pets chips, three score cards with meter bars (drop the bars), deal summary, stat / visual / neighbourhood-quality / ad-claims blocks, AI flag lists, recharts price history, description. Esc handler at 146-150. `mutationId = property.id || id` (BIN-82) must survive.
- `frontend/src/pages/Properties.tsx` -- mounts the modal at 665; `openProperty` 101-108 / `closeProperty` 119-122 navigate with `state.returnTo`; `viewMode` at 157 comes from the path, so opening from `/favourites` flips it to `all` and the effect at 363-373 reloads the list (scroll and view lost). `viewType` at 167 (`grid` | `map`). Save-search dialog 644-663 borrows `.modal-overlay` / `.modal`.
- `frontend/src/utils/percentile.ts` -- `badgePercent`, `pricePercentileForType`; add the sentence view-model here.
- `frontend/src/utils/primaryListing.ts` -- `groupListings`, `bestListingForType`, `isPrimaryListingRow`, `decisioningPrice` (card uses the first two for its price lines).
- `frontend/src/api.ts:21-36` -- `PropertyListing` lacks `id` and `cost`; `PropertyDetail` lacks `deciding_listing_id`, `deciding_rule`, `total_monthly_cost`. Wire shape: `src/api/schemas.py:13-55` (`ListingCostModel`), states table in `docs/features/v0.14-s1.2-…md`.
- `frontend/src/index.css` -- modal block 930-982; `.detail-row`, `.listings-table`, `.listing-link*`, `.favourite-btn`, `.watchlist-btn` are modal-only candidates (verify by grep before deleting); Meia-noite block from 1384 (`:root` tokens, `.meia`, `.percentile-badge`). Missing tokens: `surface-elevated #1e2438`, `scrim #0e1220d9`, `favourite-star #d9b35f`, `gone #d05b4a`. Nav sidebar is fixed, 240px, hidden at `max-width: 900px`.
- `frontend/src/i18n/locales/{en,pt-BR}.json` -- `modal.*` namespace (470-515), `attr.percentile*`, `attr.zScore`, `common.percentile`. `src/tests/unit/test_i18n_catalog_parity.py` enforces parity, One/Many pairing and pins the 1.7 copy (comment at 303 names this story as owner of the legacy labels).
- `frontend/tests/e2e/` -- modal selectors in: `property-modal-listings`, `property-modal-fetch-failure`, `property-modal-fallback-link`, `deep-links`, `dashboard`, `locale-full-ui`, `primary-listing-grid`, `numeric-input-spinners`, `compare-select`, `compare-map-select` (`.modal`, `.modal-header`, `Fechar modal`, `modal-*` test ids, `property-modal-error`); `.modal` used for the save dialog in `locale-filters`, `saved-search-price-type`, `percentile-badge-filter`. `helpers/apiMocks.js` `mockPropertyDetail` stays as is. Map e2e helper pattern: `compare-map-select.spec.js` `openMapView`.
- `frontend/src/components/MapView.tsx:365-428` -- map is created once and never refits on data change; viewport survives as long as the component stays mounted.
- `docs/architecture-frontend.md:25`, `docs/component-inventory-frontend.md:18`, `docs/source-tree-analysis.md:46` -- name `PropertyModal`.
- `_bmad-output/implementation-artifacts/deferred-work.md` -- DW-47, DW-49.

## Tasks & Acceptance

**Execution:**
- [x] `frontend/src/utils/percentile.ts` -- add `percentileSentences(property, listingTypes)` returning `{ type, n, dual }[]` built on `badgePercent` -- one rule for card and panel.
- [x] `frontend/src/utils/listingCost.ts` -- NEW pure view-model: per Listing, ordered rows (`rent` / `condo` / `condoIptuBundled` / `iptu` / `total`) with `value | null` and a state; no arithmetic -- keeps the honesty rules out of JSX.
- [x] `frontend/src/api.ts` -- add `ListingCost`, `PropertyListing.id` / `.cost`, deciding fields on `Property` / `PropertyDetail`; drop legacy listing fee fields nothing reads.
- [x] `frontend/src/components/detail/` -- NEW: `PropertyDetailPanel.tsx` (shell: scrim, `aside`, fetch, Esc, focus, header, ordered section list), `PanelSection.tsx`, one file per section (verdict with percentile sentence, monthly cost, price by platform, price history, facts, neighbourhood, description), `listingUrl.ts`.
- [x] `frontend/src/pages/Properties.tsx` -- mount the panel; pass `viewType` for the scrim; keep the favourites view while a panel opened from it is showing; rename the save dialog classes.
- [x] `frontend/src/index.css` -- delete the modal block and every rule only it used; add tokens and `.detail-*` / `.dialog*` rules.
- [x] `frontend/src/i18n/locales/en.json`, `pt-BR.json` -- `modal.*` → `detail.*` (drop unused keys), sentence and cost strings, remove `attr.percentile*`, `common.percentile` and other keys left without a caller.
- [x] `frontend/src/components/PropertyModal.tsx` -- delete.
- [x] `src/tests/unit/test_i18n_catalog_parity.py` -- pin the three sentence strings, assert each starts with the badge sentence, forbid `percentil` / `P25` / `≤` in every catalog value, assert no `modal.` key remains.
- [x] `frontend/tests/e2e/` -- migrate every spec listed in the Code Map to the panel (rename the three `property-modal-*` files to `property-detail-*`); cost fixtures use `cost` objects; NEW `property-detail-panel.spec.js` covering the matrix, panel geometry (right side, scrim, map uncovered in map view), open → Esc → scroll preserved with filter state kept and no list refetch, favourites view kept, suppressed percentile absent.
- [x] `docs/features/v0.14-s1.8-detail-side-panel.md` (from `_template.md`), the three frontend docs naming `PropertyModal`, `deferred-work.md` (DW-49 resolved, DW-47 updated with what still reads the fields).

**Acceptance Criteria:**
- Given the Properties grid, when a card is clicked, then a panel appears anchored to the right edge with a scrim over the grid, the URL is `/properties/:id`, and no centered overlay exists.
- Given the map view with a panel open, when the page is inspected, then the map element is the same DOM node as before, is not under the scrim and its left part is not covered by the panel.
- Given a scrolled grid with a filter set, when a card is opened and `Esc` is pressed, then `window.scrollY`, the filter value and the number of list requests are unchanged and focus is back on the page.
- Given the Favoritos view, when a favourite is opened and closed, then the heading stays `Favoritos` and the list is not refetched.
- Given the repository after the change, when `grep -ri modal frontend/src frontend/tests` runs, then the only hits are `aria-modal` on the compare view.
- Given both catalogs, when the parity tests run, then every key exists in both and no value contains `percentil`.

## Spec Change Log

## Review Triage Log

### 2026-10-08 — Review pass
- verdicts: 44 findings — high 0, medium 10, low 22, false 11, maybe-false 1
- findings:
  - `[medium]` `[patch]` Esc on the window closes the panel even when a dropdown or the save dialog owns the key — handler returns on `defaultPrevented` or an open `.dialog-overlay`; e2e added (map view, city multiselect).
  - `[low]` `[patch]` Feature doc says an empty section is absent, but the verdict and facts sections always render — sentence corrected.
  - `[low]` `[patch]` Four dash patterns for up to six price-history series — six distinct patterns.
  - `[low]` `[patch]` `--nav-sidebar-width` duplicated the 240px literals of `.sidebar` and `.main-content` — both rules use the token.
  - `[low]` `[patch]` The 769-900px band was untested — e2e at 850px (panel at x=240, no scrim box).
  - `[low]` `[reject]` The compare bar (z 900, centered, 280px+) can overlap the bottom-left of the panel — only in compare mode with a selection and a panel open; the panel scrolls; a fix means layout rules for a combination the UX contract does not describe.
  - `[low]` `[patch]` Swapping the panel to another Property was untested — covered in the map e2e (same root as the verification-gap row below).
  - `[false]` `[reject]` Follow-ups in the feature doc are not in the ledger — its fix is this spec's `deferred` list; the underlying items are deferred in this pass on their own rows.
  - `[false]` `[reject]` The spec artifact is stale (unticked tasks, sidebar breakpoint, `gone` token) — a finding whose fix is to edit this build's spec; the code follows the real 768px breakpoint.
  - `[false]` `[reject]` Favoritos fix is partial because the nav would highlight Imóveis — `isPropertiesSurface` (routes/propertyPaths.ts) makes one nav entry cover /properties and /favourites, so the highlight never differed; a second property cannot be opened under the grid scrim.
  - `[false]` `[reject]` Property-level `total_monthly_cost` is typed but not shown in the header — the AC asks for the itemized components with the total, which the cost section shows per Listing; the types mirror the wire model.
  - `[false]` `[reject]` Bundled branch reads `condo_fee_monthly` without checking `condo_fee_state` — `_fee_state` in core/property_projection.py returns `bundled` whenever `fees_bundled` is true, so the two cannot disagree; a null figure already reads `não informado`. Its test-gap half is the deciding-mark row below.
  - `[low]` `[patch]` Toggle buttons stated their status twice (`aria-pressed` plus a swapping label) and the load error was `role="status"` — `aria-pressed` dropped, error is `role="alert"`. The empty `alt` of the main photo and a thumbnail whose image fails are carried over from the modal unchanged and left.
  - `[low]` `[patch]` English `not informed` is a calque — `not published` / `a value was not published`, pinned. `Claims do anúncio` (pt-BR) and the sentence built from a prefix key plus a bold phrase are existing or two-locale copy and left.
  - `[low]` `[patch]` `isPrimaryListingRow` had no caller left in the product — deleted with its two assertions in primary-listing-grid.spec.js. `viewType: string` and the regexp of the source scan are left (no demonstrated harm).
  - `[medium]` `[patch]` A favourite removed inside a panel opened from Favoritos stayed in the list after close, and `favouriteIds` went stale — `onFavouriteChange` updates the star set at once and the Favoritos list reloads when the panel closes; e2e added.
  - `[medium]` `[patch]` Esc in a filter dropdown or the save dialog also closed the panel — same root as the first row.
  - `[low]` `[patch]` Closing pulled focus from a page control in use back to the opener — focus is restored only from the panel or `body`; covered by the Esc e2e.
  - `[false]` `[reject]` A 200 detail response with a null body leaves the panel `ready` with no property — the route has a response model and answers 404 for a missing property; no path produces a null 200.
  - `[low]` `[reject]` Drop percentage 0 becomes 5 and values above 100 are sent — behaviour of the modal carried over unchanged, not caused by this story, and low; not worth a ledger entry.
  - `[low]` `[patch]` More than four series repeat a stroke pattern — same root as the price-history row above.
  - `[false]` `[reject]` A non-array tag field in `ai_analysis` would throw — the modal read the same fields the same way; the producers (VisualResult / SentimentResult) write lists only, so the state is not demonstrated.
  - `[low]` `[reject]` At 900px and below the panel covers the whole map — the product is desktop-only (EXPERIENCE.md); full width on narrow windows is the recorded decision.
  - `[low]` `[patch]` A Listing price of 0 read `R$ 0` in the platform row and a dash on the card — same truthiness check as the card.
  - `[low]` `[defer]` A favourite's card has no badge while its panel has the sentence — the favourites endpoint lacks the percentile fields (API change, Story 5.10 territory); deferred.
  - `[medium]` `[patch]` Neither guard of the `menor custo total` mark was tested — two negative e2e cases added.
  - `[medium]` `[patch]` Header badge cohort was only observed with a rent primary Listing — e2e with a sale primary Listing (reads 40%).
  - `[medium]` `[patch]` Favourite and watch toggles were never clicked; BIN-82 `mutationId` unverified — e2e on a Property whose UUID differs from the route id asserts the four requests and the drop percentage.
  - `[medium]` `[patch]` Panel swap to another Property (`key={id}`) unexercised — map e2e routes to a second Property and checks header, favourite state and node identity.
  - `[medium]` `[patch]` Price-history section had no assertion — e2e for a chart (two series), the single-point note and the absent section.
  - `[false]` `[reject]` The loop's pre-merge verify runs the backend tier only — already ledger entry DW-51; this session ran the auto (full) tier itself.
  - `[medium]` `[defer]` A backend stamp satisfies a frontend-required diff in `check_stamp` — pre-existing gate rule, not caused by this story; deferred.
  - `[maybe-false]` `[defer]` The map point click path into the panel is not exercised because points do not draw under the Vite dev server (worker 404) — whether production is affected is unverified (the build emits no worker file); deferred as high (unverified) with what would settle it.
  - `[medium]` `[defer]` "Map rail visible" lives at the split-view surface, which the app does not have — the invocation leaves scrim and layout calls to the story and keeps it inside its scope, so one reading applies; delivered on the existing toggle layout, recorded as a product decision, the missing split layout deferred.
  - `[low]` `[patch]` "Across data refreshes" was only tested as "no refresh happens" — map e2e refetches the list with the panel open (filter change): panel, Property and map node stay.
  - `[low]` `[reject]` Map viewport is asserted as node and canvas identity, not as centre and zoom — MapView creates the map once and never refits on data change (MapView.tsx:365-428), and a test has no handle to the map instance; listed as not observed directly.
  - `[low]` `[reject]` Cost and percentile are tested against hand-written mocks — the whole e2e suite mocks the API by design; the TypeScript `ListingCost` matches `ListingCostModel` field for field; listed as a residual risk.
  - `[false]` `[reject]` "Never percentil" is not enforced on server-written text — `reasoningStatBand` renders catalog templates, which the new catalog-wide test covers; free AI text is outside the wording rule of any story.
  - `[false]` `[reject]` The listings spec was replaced, not migrated — git records it as a rename; its assertions follow the cost surface the story redesigned (stored `cost` instead of the legacy Base / Condo / IPTU columns).
  - `[low]` `[patch]` Interior order differed from DESIGN.md (chart before the per-platform comparison) — sections reordered. The other dropped items (best-price star, header link buttons, meter bars, emoji) are disclosed decisions.
  - `[low]` `[patch]` The DW-47 update omitted saved searches, docs/data-models-api.md and three test files — added after a grep of each.
  - `[false]` `[reject]` Behaviour added beyond the story text (stricter `sanitizeListingUrl`, Favoritos view kept) — descriptive, no defect claimed; both are disclosed and tested.
  - `[low]` `[patch]` Product-visible calls were spread over the feature doc — decisions table gained the scrim / layout, URL, cutoff, wording and order rows.
  - `[low]` `[defer]` Card and panel disagree on Favoritos — same root as the favourites-badge row above.

### 2026-10-08 — Review pass (follow-up)
- verdicts: 46 findings — high 0, medium 9, low 22, false 12, maybe-false 3
- findings:
  - `[low]` `[patch]` Price-history legend swatches were identical: every series has one ink and the default recharts legend icon ignores the dash (DefaultLegendContent.js, `line` icon) — `legendType="plainline"`; the chart e2e asserts one solid and one dashed swatch.
  - `[low]` `[patch]` A watch change made in the panel did not reach the page, so the card's bell stayed stale and its next click sent the opposite request — `onWatchChange` updates `watchedIds` as `onFavouriteChange` does; the toggles e2e asserts the card bell.
  - `[medium]` `[patch]` The save-dialog branch of the Esc guard had no test — e2e added in the map view (dialog open: Esc leaves panel and dialog; dialog dismissed: Esc closes the panel). The guard still queries `.dialog-overlay`; the new test pins it.
  - `[medium]` `[patch]` With focus on a closed city or neighbourhood multiselect trigger, Esc never closed the panel, because SearchableMultiSelect called `preventDefault` on every Esc — it now consumes Esc only while its dropdown is open; the dropdown e2e presses Esc a second time and expects the panel to close with focus left on the trigger.
  - `[medium]` `[patch]` `menor custo total` was shown beside a single stated total when the other rent Listing was incomplete: the server rule picks the lowest among the complete totals, and the incomplete one was never compared — the mark now needs two rent Listings with a stored total; e2e for the mixed case.
  - `[false]` `[reject]` The Favoritos reload after a removal uses the current page and can land on an empty page 2 — Favoritos renders no pagination control (Properties.tsx: the pagination needs `viewMode === 'all'`) and entering it sets page 1, so the reload asks for the page the list was loaded with.
  - `[low]` `[patch]` The feature doc said the listings spec was "renamed" although git shows delete + add — wording corrected (same two cases, rewritten for the cost section). The second half (a card under the scrim can be opened with the keyboard) is the scrim row below.
  - `[low]` `[defer]` In the grid view the page under the scrim is dimmed but keyboard-operable — real; the fix (inert while the scrim is drawn) reverses a recorded decision and changes focus-restore timing, so it is deferred, not patched; noted in the feature doc.
  - `[low]` `[reject]` `listingCost.ts` and `percentileSentences` have no direct unit tests and some branches are unreached — the unreached states (`known` with a null figure, `complete` with a null total, bundled with a null figure) cannot be emitted by `listing_cost_view` (core/property_projection.py:126-160); there is no frontend unit runner; the mixed complete / incomplete case is now covered.
  - `[low]` `[reject]` DW-47 keeps its original reason text and names no owner — the entry carries a dated update stating the current readers; assigning an owner story is planning's call, not this review's.
  - `[maybe-false]` `[defer]` carried — The map-point path is deferred without the runtime check (MapLibre worker 404); same location and claim as the first pass row, deferred item unchanged.
  - `[low]` `[reject]` The spec artifact holds stale statements (900px sidebar breakpoint, `gone` token, status lines) — a finding whose fix is to edit this build's spec.
  - `[low]` `[reject]` Every platform-row link has the same accessible name; sections are `h3` with no heading for the Property; the loading line is not a live region — the row shows platform, type and price beside the link; unlikely to be met by the single desktop user, and the fix adds catalog keys and roles.
  - `[low]` `[reject]` `Por que este veredito` renders with three dashes when a Property has no signal — the modal showed the same three empty score cards; hiding the section adds a branch for a state enrichment makes rare.
  - `[low]` `[reject]` Copy pins cover more pt-BR keys than English ones; the jargon test checks three tokens while z-score rows remain; the legacy-field scan covers `components/detail/` only — the pinned strings are the contract's (pt-BR is the product locale); UX-DR8 forbids `P25`, `percentil` and the sign, not the z-score rows the modal already had; the scan guards the panel, which is the surface this story owns.
  - `[low]` `[defer]` The Y axis reads `R$3k` on every tick for a rent series — real and carried over unchanged from the modal (PropertyModal.tsx:690 at main), so not caused by this story; deferred.
  - `[low]` `[reject]` Closing the panel before a favourite request resolves skips the Favoritos reload — needs Esc inside one local round trip; the star set still follows; a fix adds a ref and a branch.
  - `[low]` `[reject]` A late `checkFavourite` answer can overwrite a star the user already toggled — same code and same window as the modal; the toggle is shown only after the detail fetch, which races the check on localhost.
  - `[low]` `[patch]` Watch toggled in the panel has no page callback — same root as the watch row above.
  - `[low]` `[reject]` Leaving the panel through the Favoritos nav after a favourite change fetches Favoritos twice — two identical requests; the page already double-loads on a view change (filter effect plus page effect); a fix adds a previous-view ref.
  - `[low]` `[reject]` After a favourite removed in Favoritos, focus restored to the card falls to `body` when the reload removes it — nothing is trapped; a fix adds a focus hand-off for one path.
  - `[maybe-false]` `[reject]` Esc during an IME composition also closes the panel — would be low if true; settling it needs a composition session in Chromium on this host (dead keys do not open one on Windows), and the product is a pt-BR desktop tool.
  - `[medium]` `[patch]` Claim "Esc closes" fails on a closed multiselect trigger — same root as the multiselect row above.
  - `[false]` `[reject]` Claim "closing never refetches the list" is conditional — the one reload on close is the first pass's patch for a favourite removed inside Favoritos (the list must drop it); plain open and close refetch nothing, and that is now also asserted after a favourite toggle outside Favoritos.
  - `[medium]` `[patch]` Esc guard for the open save-search dialog has no test — same root as the save-dialog row above.
  - `[medium]` `[patch]` "No list refetch on close" was not checked after a favourite change in the Imóveis view — the toggles e2e now closes the panel and compares the list request count.
  - `[low]` `[patch]` The zero-price platform row patched in the first pass had no test — e2e added (dash, never `R$ 0`).
  - `[medium]` `[patch]` Facts rows, the three scores and the description were rendered but never asserted — positive assertions added (address, per-type scores, z-score, price per m², the three scores, description, no meter element).
  - `[low]` `[reject]` The save-search dialog has no Esc handling of its own, so with the guard Esc closes neither — the dialog never handled Esc (main); it belongs to the saved-search surface of Story 1.10 and its Cancel button works.
  - `[maybe-false]` `[defer]` carried — The map e2e opens the panel with `pushState`, not through a point click; same claim as the first pass row, deferred item unchanged.
  - `[medium]` `[defer]` carried — The scrim exists only in the grid view above 900px (no split layout); first pass row and deferred item unchanged.
  - `[medium]` `[patch]` `Esc` closes only when nothing else used it, and not on a multiselect trigger — same root as the multiselect row above.
  - `[false]` `[reject]` Closing refetches Favoritos after a favourite change — same refutation as the edge-case claim above.
  - `[low]` `[defer]` carried — Badge and sentence disagree on Favoritos; first pass row and deferred item unchanged.
  - `[false]` `[reject]` A dual-type Property with no `primary_listing` gets sentences but no header badge — `select_primary_listing` returns a Listing whenever the Property has one, so `primary_listing` is null only when there are no Listings, and then there are no sentences either.
  - `[false]` `[reject]` Header price, platform prices and facts come from outside the three named projection sources — they are fields of the same AD-12 projection, shown as served; the "nothing summed or derived" rule is about cost and percentile, and no arithmetic is done on them.
  - `[false]` `[reject]` `listingCost.ts` maps states the matrix does not define — the server cannot emit them (see the unit-test row above); they fall to the honest side (words, no number).
  - `[false]` `[reject]` Dashes still appear for a missing platform price and missing facts — the words-not-dash rule of the intent is for cost components; the card uses the same dash for a missing price.
  - `[false]` `[reject]` "Frontend only" also changes a Python catalog test, docs and the ledger — the spec's own task list names them; `src/api/`, `src/core/` and the contract tests are untouched.
  - `[false]` `[reject]` Content dropped or moved against "same content" (best-price star, header link buttons, group headers, Base column, `Taxas inclusas`, emoji, sub-scores as rows) — each judged against the UX contract: DESIGN.md keeps the star for favourites alone and bans meters and bars; the links moved to the platform rows; Base / Condo / IPTU are the cost section the story's second AC asks for, with `Taxas inclusas` as the bundled row; the mock has none of the others. Nothing unlicensed was dropped.
  - `[low]` `[patch]` carried — Section order differs from the modal; reordered to DESIGN.md in the first pass, code unchanged.
  - `[false]` `[reject]` carried — Behaviour added beyond the modal's content; descriptive, no defect claimed.
  - `[false]` `[reject]` The watch control may be the excluded alert entry point of Story 5.8 — it is the modal's own control carried over (PropertyModal.tsx:255-280 at main), not a new entry point.
  - `[low]` `[reject]` carried — Expectations are tested through mocks, one filter, keyboard open and node identity; first pass rows unchanged (residual risks).
  - `[false]` `[reject]` Literal `box-shadow`, a `10px` radius and 7px tags against "tokens only, no pills" — DESIGN.md asks for a real shadow, 10px on cards and panels and small rounded tags; a pill is 9999px.
  - `[low]` `[reject]` The pure view-models have no direct unit tests — same finding as the unit-test row above.

## Design Notes

**Scrim and the map.** The app shows grid or map, not the split of DESIGN.md. Grid view: scrim from the nav sidebar's right edge to the panel's left edge; click closes. Map view: no scrim; the panel covers the right part of the map, the rest stays visible and usable, and selecting another point swaps the panel content (still one level).

**Width.** `clamp(440px, 46vw, 640px)` (640 is the mock at 1440); full width at `max-width: 900px`, where the nav sidebar is already hidden.

**Sections.** The shell renders an ordered list of section components, each taking `{ property, … }` and returning `null` when it has nothing to say. A later story adds one file and one line.

**Cost rows (pt-BR).** `Aluguel` · `Condomínio` · `IPTU` · `Total mensal`; unknown `não informado`; bundled row `Condomínio + IPTU` with note `valor único publicado pela plataforma`; incomplete total `incompleto` with note `há valor não informado`; the deciding Listing is marked `menor custo total` when a Property has more than one rent Listing.

## Verification

**Commands:**
- `C:\Workfolder\imoveis\.venv\Scripts\python.exe scripts/agent/validate.py` -- expected: exit 0, tier includes frontend (eslint, build, Playwright e2e).
- `grep -rin modal frontend/src frontend/tests` -- expected: only `aria-modal` in `CompareView.tsx`.

## Auto Run Result

Status: done

**Summary.** The centered property modal is replaced by the right-side detail panel of the UX contract. The panel is built from one section component per file, states the Story 1.7 percentile as a sentence under the same rule as the card badge, and itemizes each Listing's stored cost from the Story 1.2 projection without arithmetic. Opening and closing do not refetch the list, move the scroll, remount the map or change filters. The modal component, its styles, its catalog keys and its test selectors are gone; its three e2e specs are renamed and migrated. Frontend only: no file under `src/api/`, `src/core/` or `src/tests/contract/` changed, no migration, no operator action.

**Files changed.**
- `frontend/src/components/detail/` (new, 10 files) -- panel shell, section frame, seven sections, listing URL helpers.
- `frontend/src/components/PropertyModal.tsx` -- deleted.
- `frontend/src/utils/percentile.ts` -- `percentileSentences`, built on `badgePercent`.
- `frontend/src/utils/listingCost.ts` (new) -- cost rows view-model.
- `frontend/src/utils/primaryListing.ts` -- `isPrimaryListingRow` removed (no caller left).
- `frontend/src/api.ts` -- `ListingCost`, `PropertyListing.id` / `.cost`, deciding fields; legacy listing fee fields dropped from the type.
- `frontend/src/pages/Properties.tsx` -- mounts the panel; Favoritos stays the view behind a panel opened from it; favourite changes from the panel; save dialog classes.
- `frontend/src/components/CompareView.tsx` -- two comments.
- `frontend/src/index.css` -- modal block and modal-only rules removed; three tokens, panel width and nav width variables, `.detail-*`, `.dialog*`.
- `frontend/src/i18n/locales/en.json`, `pt-BR.json` -- `modal.*` replaced by `detail.*`; sentence and cost strings; legacy percentile labels removed.
- `src/tests/unit/test_i18n_catalog_parity.py` -- sentence and cost copy pinned, wording rule on every catalog value, no `modal.` key, source scan.
- `frontend/tests/e2e/property-detail-panel.spec.js` (new, 29 tests); `property-detail-{listings,fetch-failure,fallback-link}.spec.js` (renamed, migrated, one test added); thirteen other specs updated to the panel or the `.dialog` selector.
- `docs/features/v0.14-s1.8-detail-side-panel.md` (new); `docs/architecture-frontend.md`, `docs/component-inventory-frontend.md`, `docs/source-tree-analysis.md`.
- `_bmad-output/implementation-artifacts/deferred-work.md` -- DW-49 resolved; DW-47 updated with what still reads the legacy fields.

**Review findings.** 44 findings from four layers: 23 patched, 5 deferred, 16 rejected.
- Patched, by entry verdict: medium 7 entries (Esc owned by a dropdown or the save dialog; stale Favoritos list after a favourite change in the panel; five untested behaviours: deciding-mark guards, header badge cohort, toggles and the BIN-82 id, panel swap, price-history section), low 13 entries (doc sentence, dash patterns, sidebar width token, 769-900px test, toggle semantics and error role, English copy, dead helper, focus restore, price 0, refresh-while-open test, section order, DW-47 reader list, decisions table), high 0.
- Deferred (frontmatter `deferred`, five items; the centered-dialog item was added by the dev session, not by a reviewer): missing split grid / map layout; MapLibre worker not served or built (high, unverified); Favoritos card without the badge its panel sentence has (two rows, one entry); centered save dialog and compare overlay; backend stamp accepted for a frontend diff.
- Rejected, with the reason recorded on each row of the triage log: compare bar overlapping the panel; follow-ups not in the ledger and the stale spec artifact (fix is this spec); nav highlight on Favoritos (false); property-level total not in the header (false); bundled branch state check (false); null 200 body (false); drop percentage bounds (carried over, low); non-array AI tags (not demonstrated); panel covering the map at 900px and below (desktop-only decision); loop verify tier (already DW-51); viewport asserted by node identity; mocked API in e2e; wording rule on server text (false); listings spec "replaced" (false, it is a rename); behaviour beyond the story text (no defect claimed).

**Follow-up review: recommended (true).** Seven medium entries were patched after the review. The unverified risk is in the patch itself, which no reviewer saw: the effect in `Properties.tsx` that reloads the Favoritos list when the panel closes, the Esc guard (`defaultPrevented` / open dialog), the focus-restore condition, and ten e2e tests written in the same step.

**Verification.**
- `C:\Workfolder\imoveis\.venv\Scripts\python.exe scripts/agent/validate.py` (auto tier resolved to `full`) on the implementation commit: exit 0, `VALIDATION PASSED (tier=full)`; unit 2398 passed / 1 skipped, integration 243 passed, contract 75 passed, eslint and Vite build passed, Playwright e2e 152 passed, harness passed. An earlier full run on the pre-review tree failed outside the diff (test database refused the first connection; two harness script tests timed out) while other gate runs loaded the host; the rerun was clean.
- `grep -rin modal frontend/src frontend/tests`: one hit, `aria-modal` in `CompareView.tsx`.
- Matrix audit: every row of the I/O matrix has a passing e2e test in `property-detail-panel.spec.js`, `property-detail-listings.spec.js` or `property-detail-fetch-failure.spec.js`.

**Residual risks.**
- The panel was never run against the real API; every e2e mocks it. The TypeScript cost type matches `ListingCostModel` field for field.
- Map viewport preservation is asserted as "same map node and canvas", not as centre and zoom.
- Opening the panel by clicking a map point is not exercised by any test (points do not draw under the Vite dev server; see the deferred item).
- While focus is on a multiselect trigger, Esc does not close the panel, because that component always calls `preventDefault` on Esc.

### Follow-up review pass (2026-10-08)

Status: done

**Summary.** A fresh review of the whole diff (four layers, 46 findings) with the first pass's post-review patch read for the first time. Four behaviour fixes and one doc correction; four coverage additions for behaviour the first pass patched untested. No finding was high.

**Files changed in this pass.**
- `frontend/src/components/detail/MonthlyCostSection.tsx` -- the `menor custo total` mark needs two rent Listings with a stored total.
- `frontend/src/components/SearchableMultiSelect.tsx` -- Esc is consumed only while the dropdown is open.
- `frontend/src/components/detail/PriceHistorySection.tsx` -- legend swatches draw the stroke pattern.
- `frontend/src/components/detail/PropertyDetailPanel.tsx`, `frontend/src/pages/Properties.tsx` -- `onWatchChange`: the page's bell set follows the panel.
- `frontend/tests/e2e/property-detail-panel.spec.js` -- 32 tests (3 new, 4 extended).
- `docs/features/v0.14-s1.8-detail-side-panel.md` -- the four behaviours, the listings-spec wording, the scrim keyboard note.

**Review findings.** 46 findings: 14 rows patched (9 entries, one row carried from the first pass), 6 rows deferred (2 new items, 4 rows carried), 26 rejected.
- Patched, by entry verdict: medium 5 entries (Esc dead on a closed multiselect trigger; `menor custo total` beside a single stated total; three untested behaviours: Esc with the save dialog open, no refetch on close after a favourite change outside Favoritos, the carried-over facts / scores / description), low 4 entries (legend swatches; watch change not reaching the card; zero-price row test; feature-doc wording), high 0.
- Deferred, new: keyboard reach under the grid scrim (low); Y-axis tick text for rent series, carried over from the modal (low). Carried and unchanged: split layout, MapLibre worker, Favoritos badge.
- Rejected, with the reason on each row of the triage log.

**What the first pass's unreviewed patch looks like.**
- Favoritos reload on close (`Properties.tsx`): runs only when the panel closes after a favourite change and the view is Favoritos; the effect reads the `load` of the render that closes the panel, so no stale filter or page; no second fetch on a plain close; a panel opened by URL has no Favoritos view behind it and reloads nothing. A toggle off and on again still reloads once (harmless). Two narrow paths are logged and rejected as low: close before the request resolves, and leaving through the Favoritos nav.
- Esc guard: sound for a handled key and for the save dialog; the multiselect dead end is fixed in this pass.
- Focus: moves to the panel on open and back to the opener on close unless focus is on a page control; the panel is a labelled `aside`, not a dialog, and traps nothing.

**Dropped modal content, judged against the UX contract.** Score meter bars: banned by DESIGN.md (no progress bars; judgment in words, not meters); the three scores stay as numbers. Best-price star: DESIGN.md keeps the star for favourites; rows stay ordered by price and the cost section marks the lowest compared total. Header link buttons: moved to one link per platform row, every Listing still has its link. Base / Condo / IPTU table: replaced by the stored cost rows the story's second AC asks for. Nothing to restore.

**Modal e2e specs.** The six tests of the three `property-modal-*` specs at `main` all exist in `property-detail-*` (two titles reworded in the listings spec, whose assertions follow the cost section); one test was added (look-alike host). None disappeared or was weakened.

**Follow-up review: not recommended (false).** Follow-up pass; patched entries by verdict: high 0, medium 5, low 4. The work has converged: the fixes are small, each has a regression test that was seen to fail without it, and the rest of this pass added tests only.

**Verification.**
- `C:\Workfolder\imoveis\.venv\Scripts\python.exe scripts/agent/validate.py` (auto tier = `full`) on the final commit: exit 0, `VALIDATION PASSED (tier=full)`, Playwright e2e 155 passed.
- Before the gate: `tsc --noEmit` and eslint clean on the touched files; the three touched or dependent specs, 37 passed. With the source fixes stashed, exactly the four regression tests failed (mixed totals, legend, card bell, second Esc) and the three coverage-only tests passed.
- `grep -rin modal frontend/src frontend/tests`: one hit, `aria-modal` in `CompareView.tsx`. A scan of both catalogs and of `index.css` found no key or class left behind by the modal (the unused ones predate the story).
- `sanitizeListingUrl` against the hosts the scrapers write (`www.quintoandar.com.br`, `www.olx.com.br` and OLX state subdomains, `www.zapimoveis.com.br`): all accepted; `http:` and look-alike hosts refused.
- Cost rows against `listing_cost_view` for every state it can emit (rent known / unknown, fee known / unknown / bundled, total complete / bundled / incomplete / not-applicable, periodicity monthly / annual / unknown): no number is shown for an unknown, no arithmetic in the frontend.

**Residual risks.** Those of the first pass stand, except the multiselect one, which is fixed. Added: the Esc guard for the save dialog depends on the `.dialog-overlay` class (pinned by an e2e test now).
