---
title: 'Story 1.7 — Percentile badge on cards and percentile filter'
type: 'feature'
created: '2026-10-08'
status: done
baseline_revision: '0ad1605cdfe2d0d0f5ec504c2fb04dd27d8bcdab'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/docs/features/v0.14-s1.6-cohort-price-per-m2-percentiles.md'
warnings: ['oversized']
deferred:
  - summary: >-
      The legacy percentile_rank, percentile_rank_rent and percentile_rank_sale are still served
      beside the new price_per_m2_percentile fields, and the modal still labels them "Percentil".
    evidence: |-
      Story 1.7 added price_per_m2_percentile_rent/_sale to list, batch, detail and export and
      left the legacy fields in place (core/property_projection.py, api/schemas.py,
      api/property_export.py); no AC of the story asks for their removal and the modal that
      renders them belongs to Story 1.8. Two numbers called percentile are therefore on the wire
      with different definitions (legacy: PERCENT_RANK, cheapest = 0, rounded to 3 places,
      fabricated 0.5 on the single-property path). frontend/src/components/PropertyModal.tsx:204-224
      renders the legacy ones through the pt-BR strings "percentil {n}", "Percentil no bairro",
      "Percentil (Aluguel)", "Percentil (Venda)", which UX-DR8 forbids. docs/api.md now says which
      field to use. Same subject as ledger entry DW-47; Story 1.8 is where the modal and then the
      fields can go, and test_percentile_characterization_lock.py has to be edited by that story.
    location: >-
      src/core/property_projection.py:48
    severity: low
  - summary: >-
      On the current card the percentile badge wraps under the price instead of sitting beside it,
      and the price line is only partly the display-price of the UX contract.
    evidence: |-
      UX-DR9 puts the badge right-aligned on the serif price line. The price line of the card also
      holds the listing-type tag, the platform and the favourite / watchlist icons (in the Painel
      mock those are on the photo and in the meta line). Measured with Chrome at 1440x900: card
      438px wide, badge about 170px; the badge wraps inside its price row and stays right-aligned
      (screenshot taken during review). The e2e test accepts beside or under. .property-price got
      the Georgia family and tabular numerals only; it keeps 20px / weight 800 / gradient fill
      where DESIGN.md says 26px / 400 / plain ink. No story in epics.md owns the card anatomy
      restyle (verdict label, serif price line, on-photo actions).
    location: >-
      frontend/src/components/properties/PropertyCard.tsx:145
    severity: low
  - summary: >-
      The full validation tier cannot pass on the Windows host: the Playwright-managed Chromium is
      not installed, and the pre-merge verify of the loop runs the backend tier only, so no
      frontend story is checked by eslint, the Vite build or e2e before its merge.
    evidence: |-
      2026-10-08: validate.py --tier full fails at "e2e: playwright" with chrome-headless-shell.exe
      missing; C:/Users/Felipe/AppData/Local/ms-playwright does not exist; .run/validated in the
      primary checkout holds backend, docs and fast stamps only, never frontend or full.
      .bmad-loop/policy.toml runs validate.py --tier backend as [verify]
      (scripts/agent/validate.py:608 runs the frontend steps only for frontend / full). For this
      story the whole e2e suite was run against the installed Chrome through a temporary
      uncommitted config. Fix: npx playwright install chromium in frontend/ on the host (a
      download the dev session had no permission to make), then decide whether [verify] should be
      the full tier for stories that touch frontend/.
    location: >-
      scripts/agent/validate.py:488
    severity: medium
operator_actions:
  - "On the Windows host, install the browser the e2e step needs (a download from cdn.playwright.dev that the dev session had no permission to make): in C:\\Workfolder\\imoveis\\.run\\wt\\1-7\\frontend (or the primary checkout's frontend after the merge) run: npx playwright install chromium. Verify: C:\\Users\\Felipe\\AppData\\Local\\ms-playwright contains chromium_headless_shell-1234."
  - "Run the full gate on the story branch (about 25 minutes; the harness tests take 23): from C:\\Workfolder\\imoveis\\.run\\wt\\1-7 run C:\\Workfolder\\imoveis\\.venv\\Scripts\\python.exe scripts/agent/validate.py --tier full. Verify: exit 0, 'VALIDATION PASSED (tier=full)', and the e2e step reports 122 passed. If an e2e test of percentile-badge-filter.spec.js fails there, the story goes back to dev instead of being confirmed."
---

<intent-contract>

## Intent

**Problem:** Story 1.6 stores a trustworthy cohort price/m² percentile per Property and listing type (`metrics_scoring.price_per_m2_percentile_rent/_sale`), but nothing reads it: the API does not serve it, the grid does not show it and it cannot be filtered. The only "percentile" on the wire is the legacy `percentile_rank*`, a different number.

**Approach:** Serve the two stored values through the AD-12 projection (list, batch, detail, export), add one server-side filter on them to `GET /properties` and the export, and in the grid render the contract's badge `entre os N% mais baratos` on each price line plus a `Preço no bairro` select whose active value shows as one removable chip. Nothing is computed at read time; the legacy fields stay as they are.

## Boundaries & Constraints

**Always:**
- The wire carries the stored value unrounded (`price_per_m2_percentile_rent`, `price_per_m2_percentile_sale`; null or in (0, 1]) from the one projection (`core/property_projection.py`). The API derives nothing per Property (AD-12).
- Filter: `max_price_per_m2_percentile` (number, > 0 and ≤ 1) on the list and the export. `listing_type=rent` compares the rent column, `sale` the sale column, `both` or absent keeps a Property when either column qualifies. A NULL percentile never matches. The value is a bound parameter; the SQL is static text (BIN-135).
- Badge number: N = the smallest whole percent that keeps the sentence true (`ceil(value × 100)`, guarded against float noise, at least 1). `0.25` reads 25, `0.2001` reads 21.
- Badge is shown only when the stored value is ≤ 0.5 (the widest option of the filter). Null or above 0.5: no badge element at all.
- One badge per price line, for that line's listing type. A dual Property can carry two.
- Badge visual per UX-DR9: `price-drop` ink, `price-drop-tint-12` background, `price-drop-tint-35` border, 7px radius, right-aligned on the price line; the card price line uses the DESIGN.md `display-price` serif family with tabular numerals. Tokens are added to `:root` under their DESIGN.md names.
- Microcopy per UX-DR8: pt-BR `entre os {n}% mais baratos`; en `among the {n}% cheapest`. No new string contains `P25`, `percentil`, `percentile` or `≤`. Every new string lands in both catalogs.
- Filter control: a select labelled `Preço no bairro` in the existing advanced-filters panel with `qualquer preço` (default), `entre os 25% mais baratos`, `entre os 50% mais baratos`. An active value renders one chip in a strip that is capped at two lines; the chip's `×` clears the filter. Changing the Transaction select refetches with the new `listing_type` and the same percentile value.
- The filter value takes part in everything the other filters do: grid fetch, map fetch, export, saved searches (wire key `max_price_per_m2_percentile`), "clear all", `hasActiveFilters`.
- `test_percentile_characterization_lock.py`: only the two pinned key sets change, in the commit that changes the projection. No locked value changes.

**Never:**
- Remove, rename or change `percentile_rank*` on the wire, in the export or in the modal (Story 1.8 owns the modal); write any `metrics_scoring` column; add a migration or an index; schedule the bulk stage.
- Read the legacy `percentile_rank*` for the badge or the filter.
- Render a placeholder, `0%`, `50%` or a dash for a missing percentile.
- Restyle the rest of the card or the filter bar (existing filters do not become chips here; Story 6.3 owns chip collapse and `Filtros (N)`).
- Touch `sprint-status.yaml`, `.bmad-loop/`, the primary stack, `.env.local`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Rent filter | `listing_type=rent&max_price_per_m2_percentile=0.25`; rows rent 0.2 / 0.25 / 0.3 / NULL | 0.2 and 0.25 returned | No error expected |
| Type switch | same value, `listing_type=sale`; a Property with rent 0.1, sale 0.9 | not returned (sale column decides) | No error expected |
| Both types | no `listing_type`; rent 0.9 + sale 0.2 | returned (either qualifies) | No error expected |
| Suppressed | percentile NULL, cohort size stored | never matches an active filter; listed without a badge when no filter | No error expected |
| No scoring row | Property without `metrics_scoring` | both fields null; never matches | No error expected |
| Out of range | `max_price_per_m2_percentile=0`, `1.5`, `abc` | — | `422` |
| Export | export with the filter | same Properties as the list; CSV has the two columns last | No error expected |
| Badge rounding | 0.05 / 0.2001 / 0.25 / 0.5 | 5 / 21 / 25 / 50 | No error expected |
| Badge cutoff | 0.51 or 1.0 | no badge | No error expected |
| Dual card | rent 0.2, sale 0.4 | rent line `20%`, sale line `40%` | No error expected |
| Saved search | filter active, search saved and reopened | value restored, chip shown | A value outside (0, 1] is rejected with `422` on save |

</intent-contract>

## Code Map

- `src/core/property_projection.py` -- `_dual_score_fields` (`:30`) is shared by `map_property_list_item` (`:300`) and `map_property_detail` (`:371`): add the two keys there, unrounded. `LIST_SELECT_COLUMNS` (`:476`) feeds list, batch, export and `core/top_deals_digest.py`.
- `src/api/properties.py` -- `PropertyListFilters` (`:174`) and `PropertyExportFilters` (`:203`) duplicate the filter surface (export adapts through `_export_filters_as_list_filters`); `_build_list_filters` (`:349`) builds WHERE from static fragments; `_PROPERTIES_FROM_JOIN` already left-joins `metrics_scoring ms`. Detail SQL (`:716`) lists its columns by hand: add the two there.
- `src/api/schemas.py` -- `PropertyModel` (`:75-90`) and `PropertyDetailModel` (`:206-224`); serial surface, this story is the only one in flight.
- `src/api/property_export.py` -- `CSV_COLUMNS`; convention (1.2): new columns are appended last. `test_api_contract.py::test_export_csv_header_carries_the_deciding_columns` and `test_property_export.py::test_export_csv_deciding_columns_are_appended_last` assert `header[-3:]` and move with it.
- `src/api/saved_searches.py:46` -- `SavedSearchFilters` (`extra="ignore"`: an undeclared key is dropped silently); `_blank_numbers` validator list.
- `src/tests/integration/test_percentile_characterization_lock.py:50-106` -- `LIST_ITEM_KEYS`, `PERCENTILE_KEYS`: the pins to extend. `test_cohort_percentiles.py:1071` single-writer test scans `src/` outside `tests` for assignments only; selecting the columns is allowed.
- Test patterns: `src/tests/unit/test_property_max_price_filter.py` (builder as text), `src/tests/integration/test_total_monthly_cost_sort_filter.py` (seeded rows through `TestClient`), `src/tests/contract/test_api_contract.py:525-596` (schema fields, OpenAPI params, 422), `src/tests/unit/test_i18n_catalog_parity.py` (catalog-side copy locks).
- `frontend/src/components/properties/PropertyCard.tsx:136-158` -- price rows, one per listing type (`groupKeys`); the row's left column sits beside the icon cluster in a `space-between` flex.
- `frontend/src/components/properties/PropertiesFilterBar.tsx:263-366` -- advanced panel (button `▼ Filtros avançados`, used by existing e2e; do not rename).
- `frontend/src/hooks/usePropertiesFiltersState.ts` -- filter state, `DEFAULT_FILTERS`, `currentFilters`, `buildListQueryFilters`, `applyFilters`, both clear helpers.
- `frontend/src/pages/Properties.tsx` -- the filter set is spelled out three times: `handleBboxChange` (`:215`), `load` (`:266`) and the refetch effect deps (`:369`).
- `frontend/src/api.ts` -- `Property` (`:50`), `PropertyFilterOptions` (`:383`), `buildPropertyFilterParams` (`:566`).
- `frontend/src/savedSearchFilters.ts` -- `CAMEL_TO_SNAKE`, `fromSavedSearchWire`.
- `frontend/src/index.css:1380-1408` -- Meia-noite token block: non-colliding roles on `:root`, `--accent` redefined only inside `.meia`, radii as `--radius-meia-*`. `.property-price` at `:760`.
- `frontend/tests/e2e/helpers/apiMocks.js` (`SAMPLE_PROPERTY`, `installCommonMocks`), `properties-max-price-filter.spec.js` (URL capture pattern). E2E runs against mocked API on a free port from 5177; no frontend unit runner exists.
- UX: `DESIGN.md` `components.percentile-badge`, `components.filter-chip`, `typography.display-price`, `rounded.sm` 7px / `md` 9px; mock `mockups/key-painel.html:119-123` (`.pctl`: 11.5px, weight 600, padding 2px 9px, nowrap, `margin-left:auto`).

## Tasks & Acceptance

**Execution:**
- [x] `src/core/property_projection.py`, `src/api/properties.py`, `src/api/schemas.py`, `src/api/property_export.py`, `src/tests/integration/test_percentile_characterization_lock.py` -- the two fields in the projection (list, batch, detail), the schemas and the CSV (last two columns); the pinned key sets extended in the same commit -- the wire
- [x] `src/api/properties.py` -- `max_price_per_m2_percentile` on both filter models and in `_build_list_filters` -- the filter
- [x] `src/api/saved_searches.py` -- the key on `SavedSearchFilters`, range-checked -- a saved search keeps the filter
- [x] `src/tests/unit/test_property_percentile_filter.py` (new), `test_property_projection.py`, `test_property_export.py`, `test_saved_search_filters.py`, `test_properties_response_schema.py` -- builder per listing type, projection keys unrounded and null, CSV tail, saved-search round trip and rejection
- [x] `src/tests/integration/test_price_percentile_filter.py` (new) -- the matrix rows on Postgres through the API: rent, sale, both, suppressed, no scoring row, export, detail and batch fields
- [x] `src/tests/contract/test_api_contract.py` -- fields declared on both models and present on list, detail and batch items; the param in OpenAPI for list and export; 422 on out-of-range; CSV tail
- [x] `frontend/src/utils/percentile.ts` (new), `frontend/src/api.ts`, `frontend/src/savedSearchFilters.ts`, `frontend/src/hooks/usePropertiesFiltersState.ts`, `frontend/src/pages/Properties.tsx` -- N rule and badge cutoff in one place; types, query param, state, saved-search mapping, the three fetch sites
- [x] `frontend/src/components/properties/PropertyCard.tsx`, `PropertiesFilterBar.tsx`, `frontend/src/index.css`, `frontend/src/i18n/locales/en.json`, `pt-BR.json` -- badge, select, chip strip, tokens, strings
- [x] `src/tests/unit/test_i18n_catalog_parity.py` -- pin the pt-BR and en badge strings and the forbidden tokens for the new keys -- UX-DR8 copy lock
- [x] `frontend/tests/e2e/percentile-badge-filter.spec.js` (new) -- badge text, ink and alignment; rounding and cutoff; absence on a suppressed Property; dual card; filter request, chip, chip removal, type switch, strip height
- [x] `docs/features/v0.14-s1.7-percentile-badge-and-filter.md` (new), `docs/api.md` -- feature doc (all template sections) and the parameter / fields

**Acceptance Criteria:**
- Given stored percentiles, when the grid renders in pt-BR, then a card whose value is ≤ 0.5 shows `entre os N% mais baratos` on that listing type's price line, right-aligned, in `#74bd82` on the two tints, and the price is set in the serif family.
- Given a Property whose percentile is null, when the grid renders, then its card has no badge element and no placeholder text.
- Given the advanced-filters panel, when `entre os 25% mais baratos` is chosen, then the list request carries `max_price_per_m2_percentile=0.25`, one chip with that text is visible with the panel closed, the chip strip is at most two chip lines high, and the chip's `×` removes the parameter from the next request.
- Given an active percentile filter, when Transaction changes to sale, then the next request carries `listing_type=sale` with the same percentile value, and on Postgres the result follows the sale column.
- Given the catalogs, when compared, then `en` and `pt-BR` have the same keys and no new value contains `P25`, `percentil` or `≤`.
- Given the final commit, when `scripts/agent/validate.py` runs with the full tier, then it exits 0 including the Playwright e2e.

## Spec Change Log

## Review Triage Log

### 2026-10-08 — Review pass
- verdicts: 41 findings — high 0, medium 3, low 21, false 17, maybe-false 0
- findings:
  - `[low]` `[patch]` Blind: the filter bar and chip render in Favoritos, where no filter is applied — true (`fetchFavourites` sends only the sort; every filter behaves so). The chip is the one element that states "active"; hidden there through `filtersApplied`, e2e added, doc states it plainly.
  - `[medium]` `[patch]` Blind: with `both` a Property can pass on the stored percentile of a type it no longer lists, and its card shows no badge — true: the stored value outlives a deactivated Listing until the next scoring run (Story 1.6 notes). Each column now also requires an active Listing of its type, in every mode; integration test added.
  - `[low]` `[patch]` Blind: an unparseable saved value leaves `hasActiveFilters` true with no chip, option or parameter — true for a value outside (0, 1] or null in a stored blob. `applyFilters` now keeps only a usable share; e2e added.
  - `[low]` `[patch]` Blind: a non-standard cap is labelled with the badge's ceiling (0.245 reads 25% beside the real 25%; 0.305 reads 31%) — true. Option and chip now show the cap as applied (`filterCapPercent`); e2e added. A cap above 0.5 returning cards without a badge is documented.
  - `[low]` `[patch]` Blind: `PATCH /saved-searches/{id}` documented but untested for the key — the route shares `SavedSearchFilters`; one accept / reject test on `SavedSearchUpdate` added.
  - `[low]` `[defer]` Blind: "right-aligned on the serif price line" is not met at the real card width and the e2e accepts both layouts — true (438px card, badge wraps under the price, right-aligned). The existing card anatomy leaves no room; restyling it is outside the story. Deferred entry 2.
  - `[false]` `[reject]` Blind: follow-ups are prose, not `v0.14-fu<N>` keys — `sprint-status.yaml` is owned by the orchestrator in this run; findings go to this spec's `deferred:` list, which it mints from.
  - `[false]` `[reject]` Blind: sprint-status still `backlog`, spec untracked, branch behind `main` — the first is the orchestrator's file; the spec is committed at finalize; `main` moved by one docs commit (Story 1.6 doc, its spec, sprint-status), none of which this branch touches.
  - `[low]` `[reject]` Blind: the map e2e depends on network tiles and WebGL — true, and identical to `compare-map-select.spec.js`; the bbox fetch only fires from the loaded map, so there is no cheaper trigger. Not worth a tile stub for one test.
  - `[low]` `[reject]` Blind: between the merge and the rebuild the old API ignores the parameter while the new grid shows the chip — true for that window only; the orchestrator rebuilds after every merge. Documented under Operator steps with the order; a guard would be new surface.
  - `[low]` `[patch]` Blind: the chip's remove button is about 20px wide — true; `min-width` / `height` 24px.
  - `[false]` `[reject]` Blind: the remove button has no focus cue — `index.css` resets `outline` only on form inputs and the multi-select search (`:439`, `:532`); a button keeps the browser focus ring.
  - `[false]` `[reject]` Blind: `overflow: hidden` will clip later chips with tabbable buttons — one chip exists; chip collapse and `Filtros (N)` are Story 6.3.
  - `[low]` `[patch]` Blind: `test_badge_and_filter_options_share_one_sentence` pins an exact two-file list — true, a third legitimate use would break it; now a subset check.
  - `[false]` `[reject]` Blind: `percentile` is redundant beside `percentil` in the forbidden list, and only the five new keys are scanned — redundant but harmless; the legacy modal keys contain the word until Story 1.8 (deferred entry 1), so a catalog-wide scan would fail today.
  - `[false]` `[reject]` Blind: the contract tests for the cap pass vacuously on an empty database — true of the contract file, and not a gap: `test_price_percentile_filter.py` seeds its rows and asserts exact label sets.
  - `[low]` `[patch]` Blind: `"0.5" not in str(count_sql)` breaks on any unrelated `0.5` literal — true; narrowed to `"<= 0.5"`.
  - `[false]` `[reject]` Blind: the parameter is hand-copied into three filter literals in `Properties.tsx` — the three literals predate the story (BIN-141 note in the file); both fetch sites and the export are each asserted by e2e. A refactor of `load` is outside the story.
  - `[medium]` `[patch]` Edge: `both` / absent matches a stale column of a type with no active Listing — same defect as Blind row 2; same patch.
  - `[low]` `[patch]` Edge: chip in Favoritos — same defect as Blind row 1; same patch.
  - `[low]` `[patch]` Edge: non-standard share labels — same defect as Blind row 4; same patch.
  - `[low]` `[reject]` Edge: a price line whose best Listing has no price but a stored percentile ≤ 0.5 shows a dash beside the badge — possible only for an active Listing with a null price after it was scored (a cohort member has a price). Unlikely, and the fix is a guard for a state not demonstrated; noted in the feature doc.
  - `[low]` `[patch]` Edge: saved blob with null or out-of-range value — same defect as Blind row 3; same patch.
  - `[low]` `[patch]` Gap: the empty-state `Limpar filtros` clearing the percentile filter is unverified — e2e added (filtered list empty, click, chip gone, parameter gone).
  - `[low]` `[patch]` Gap: the select's extra option for a non-standard saved value is unverified — e2e added (select value, four options, chip, request).
  - `[medium]` `[defer]` Gap (other): the loop's pre-merge `[verify]` runs the backend tier, so nothing frontend is checked at merge — true, and on this host the full tier cannot pass at all (Playwright Chromium missing). Not this story's code. Deferred entry 3.
  - `[false]` `[reject]` Gap (other): vacuous contract tests on empty results — as Blind row 16; covered by the integration suite.
  - `[low]` `[defer]` Intent: the badge wraps under the price; e2e does not pin "beside" — same as Blind row 6. Deferred entry 2.
  - `[low]` `[defer]` Intent: the serif price keeps weight 800 and the gradient — true; part of the card anatomy restyle. Deferred entry 2.
  - `[false]` `[reject]` Intent: a second absence (values above 50%) beside suppression — a product call the dispatch left to the build (DESIGN.md reserves green for good price news); listed in the feature doc's decisions table and in the run result.
  - `[false]` `[reject]` Intent: the 2-line ceiling lives on a new strip, not on the whole filter bar; no test fills it — the contract's active-filters-only bar is Story 6.3; this story adds its one chip in a strip with the cap. Listed as a decision.
  - `[false]` `[reject]` Intent: "Filtros panel" is mapped to the existing `Filtros avançados` panel — the only filters panel that exists; `Filtros (N)` is Story 6.3.
  - `[false]` `[reject]` Intent: the filter is tested in two halves (mocked e2e for the request, Postgres integration for the rows) — how every e2e in this repo works (`helpers/apiMocks.js`); both halves assert the same parameter name and semantics.
  - `[false]` `[reject]` Intent: the cohort semantics of the type switch are asserted only in backend tests — same structure as the row above; the e2e asserts the request the backend test starts from.
  - `[low]` `[defer]` Intent: UX-DR8 is enforced on the new catalog keys only; legacy pt-BR `percentil` strings remain — true; they belong to the modal (Story 1.8). Deferred entry 1.
  - `[low]` `[defer]` Intent: the legacy fields staying on the wire is not recorded as a deferred finding — true at review time; recorded now as deferred entry 1.
  - `[low]` `[patch]` Intent: the product calls are not in one list — true; decisions table added to the feature doc.
  - `[false]` `[reject]` Intent: the favourites grid shows no badge — its endpoint has its own projection; Favoritos columns are Story 5.10. Stated plainly in the doc.
  - `[false]` `[reject]` Intent: FR-30's detail panel has no UI here — Story 1.8; the detail endpoint already carries the fields for it.
  - `[false]` `[reject]` Intent: the diff goes beyond the story text (export, saved searches, map fetch) — each is a place the grid's filter set is already consumed; leaving the new filter out of one would make the export or a saved search disagree with the grid.
  - `[false]` `[reject]` Intent: `frontend/test-results/` holds an error context from a failed run — a git-ignored leftover of a development run; the final runs are under Verification.

## Design Notes

- **Unrounded on the wire.** The legacy fields are rounded to three places in the list. A share k/n rounded down can cross a whole percent (501/2000 → 0.25 after rounding, 26% in truth), which would make the badge and the filter disagree. The new fields are served as stored, so "badge says ≤ 25" and "passes the 25% filter" are the same test.
- **Ceil, not round.** `entre os N% mais baratos` is true for N ≥ value × 100 and false below it.
- **Badge only up to 50%.** DESIGN.md reserves green for good price news; `entre os 93% mais baratos` in green is neither news nor good. The cutoff equals the widest filter option, so every card a percentile filter returns carries a badge for the filtered type. The value above the cutoff is still on the wire for Story 1.8's sentence.
- **`both` means either.** With no type selected the card shows one price line per type, each with its own badge; a Property qualifies when one of the lines does. With a type selected only that type's column is read (no cross-type leakage, BIN-77).
- **General parameter, three UI choices.** The API accepts any value in (0, 1] (the agent is a client); the UI offers 25% and 50%.
- **No index.** The predicate is evaluated on `metrics_scoring` rows the list query already joins for its sort, and at 25–50% selectivity a b-tree would not be chosen. Not measured on the primary.

## Workspace and commits

- Work only in the git worktree `C:\Workfolder\imoveis\.run\wt\1-7` (branch `feat/v0.14-s1.7-percentile-badge-and-filter`). Every read, edit and git command happens there, with absolute paths or `git -C`. `C:\Workfolder\imoveis` itself is the primary checkout: never edit it, never run git in it. Only its interpreter is used: `C:\Workfolder\imoveis\.venv\Scripts\python.exe` (the worktree has no `.venv`).
- Read `AGENTS.md` and `CLAUDE.md` in the worktree first; they bind this work.
- Conventional commits, each ending with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Suggested order: (1) `feat(v0.14-s1.7): ...` backend wire + filter + saved search + backend tests + the lock pin; (2) `feat(v0.14-s1.7): ...` frontend + e2e + catalog test; (3) `docs(v0.14-s1.7): ...`. Do not commit this spec file and do not edit its `<intent-contract>` block; leave `sprint-status.yaml` and `.bmad-loop/` alone. Never merge, push or run `ship.py`.
- Integration, contract and e2e tests need the stack that only the gate creates: run `C:\Workfolder\imoveis\.venv\Scripts\python.exe scripts/agent/validate.py --tier full` from the worktree (allow 30 minutes; run it with a long timeout). While developing, single unit test files can be run directly with `-o addopts=`, and from `frontend/` `npm ci` once, then `npx tsc --noEmit -p .`, `npm run lint` and `npx playwright test tests/e2e/percentile-badge-filter.spec.js` with `PLAYWRIGHT_PORT` set to a free port between 5180 and 5299 (the API is mocked in e2e). A Vite dev server of the primary checkout runs on :5173: never stop it and never use that port.
- Never run `docker compose` against the project `imoveis`, never run `migrate-primary.sh`, never read `.env.local`, never query the primary database. Write multi-line scripts with the Write tool, not shell heredocs. Git Bash, when needed, is `'C:/Program Files/Git/bin/bash.exe'`.
- The existing e2e suite must keep passing unchanged: do not rename existing `data-testid`s, the `Filtros avançados` button or the Transaction `label → select` nesting.

## Verification

**Commands:**
- `C:/Workfolder/imoveis/.venv/Scripts/python.exe scripts/agent/validate.py --tier full` -- expected: exit 0, `VALIDATION PASSED (tier=full)`, Playwright included
- `C:/Workfolder/imoveis/.venv/Scripts/python.exe -m pytest src/tests/unit/test_property_percentile_filter.py -q -o addopts=` -- expected: all pass (development loop only)

**Manual checks (if no CLI):**
- `git diff main -- src/tests/integration/test_percentile_characterization_lock.py` shows only the two key-set constants changed.

## Auto Run Result

Status: awaiting-operator

**Summary.** The two stored cohort percentiles of Story 1.6 are now served, unrounded, by the AD-12 projection (list, batch, detail, export). `GET /properties` and the export accept `max_price_per_m2_percentile` (> 0, ≤ 1): rent reads the rent column, sale the sale column, no type either one, and a column counts only while the Property has an active Listing of that type. In the grid each price line shows `entre os N% mais baratos` when its stored value is at or below 0.5; the advanced-filters panel has the `Preço no bairro` select, and an active value shows as one removable chip. Saved searches keep the value. The legacy `percentile_rank*` fields are unchanged. No migration.

The story is code-complete. It is parked only because the required full-tier gate cannot pass on this host: the Playwright-managed Chromium is not installed and installing it is a download this session had no permission to make. Every other gate step passes, and the whole e2e suite passes against the installed Chrome.

**Files changed.**
- `src/core/property_projection.py` — the two fields in `_dual_score_fields` (unrounded) and in `LIST_SELECT_COLUMNS`
- `src/api/properties.py` — the parameter on both filter models, the static WHERE fragments (column + active Listing of the type), the two columns in the detail SQL
- `src/api/schemas.py` — the two fields on `PropertyModel` and `PropertyDetailModel`
- `src/api/property_export.py` — the two columns appended last in the CSV
- `src/api/saved_searches.py` — `max_price_per_m2_percentile` on `SavedSearchFilters`, range-checked
- `src/tests/integration/test_percentile_characterization_lock.py` — the two pinned key sets extended; no locked value changed
- `src/tests/integration/test_price_percentile_filter.py` (new), `src/tests/unit/test_property_percentile_filter.py` (new) — the matrix on Postgres through the API; the builder as text
- `src/tests/unit/test_property_projection.py`, `test_property_export.py`, `test_saved_search_filters.py`, `test_properties_response_schema.py`, `test_i18n_catalog_parity.py`, `src/tests/contract/test_api_contract.py` — projection, CSV tail, saved-search round trip, route, copy lock, contract
- `src/tests/integration/test_total_monthly_cost_sort_filter.py` — CSV tail assertion moved (the deciding columns are no longer last); the one file outside the planned list
- `frontend/src/utils/percentile.ts` (new) — N rule, badge cutoff, filter options, cap label, parsing
- `frontend/src/api.ts`, `savedSearchFilters.ts`, `hooks/usePropertiesFiltersState.ts`, `pages/Properties.tsx` — types, query parameter, state, saved-search mapping, the three fetch sites
- `frontend/src/components/properties/PropertyCard.tsx`, `PropertiesFilterBar.tsx`, `frontend/src/index.css`, `i18n/locales/en.json`, `pt-BR.json` — badge, select, chip strip, tokens, five strings per catalog
- `frontend/tests/e2e/percentile-badge-filter.spec.js` (new) — twelve tests
- `docs/features/v0.14-s1.7-percentile-badge-and-filter.md` (new), `docs/api.md`

**Decisions taken where the story was open** (product-visible first; all are in the feature doc's decisions table).
1. N in the badge is rounded up to the next whole percent (`0.2001` reads 21, never below 1), so the sentence is never an overstatement.
2. A badge shows only for a stored value at or below 0.5. Above it the card shows nothing, exactly like a suppressed Property. Reason: DESIGN.md reserves the green ink for good price news; the cutoff equals the widest filter option.
3. One tint for every badge; no stronger tint for cheaper values (DESIGN.md has one `percentile-badge` component).
4. Filter default is `qualquer preço`; no parameter is sent.
5. Under an active filter a suppressed Property (null percentile) is left out. With `qualquer preço` it is listed without a badge.
6. With no Transação selected a Property passes when its rent line or its sale line qualifies; with a type selected only that type's column is read.
7. A percentile column counts only while the Property has an active Listing of that type (added at review).
8. A dual Property gets one badge per price line, each from its own cohort.
9. Only this filter renders a chip; the strip is capped at two chip lines. The other filters stay as controls until Story 6.3.
10. The select lives in the existing `Filtros avançados` panel.
11. The card price takes the serif family and tabular numerals; size, weight and gradient are unchanged.
12. Favoritos shows no chip (the view applies no filter) and no badge (its endpoint does not serve the fields).
13. The wire value is unrounded and the API parameter accepts any share in (0, 1]; the UI offers 25% and 50%. A non-standard saved cap is shown as applied (`30.5%`).
14. The filter also applies to the export, the map fetch and saved searches; the CSV gets the two columns last.
15. No index for the filter; not measured on the primary.
16. The legacy `percentile_rank*` fields stay (deferred entry 1).

**Review.** 41 findings from four layers: high 0, medium 3, low 21, false 17.
- Patched: 10 entries (15 rows) — medium 1 (stale column of a type without an active Listing; 2 rows), low 9 (chip in Favoritos; unusable saved value; non-standard cap label; PATCH test; remove-button size; brittle source-scan test; brittle `0.5` assertion; decisions table; empty-state clear test).
- Deferred: 3 entries (6 rows) — legacy fields and legacy `Percentil` strings (low), badge wraps under the price and partial display-price (low), full tier cannot pass on this host and the loop verifies with the backend tier (medium).
- Rejected: 17 `false` and 3 `low`; each row and its reason is in the triage log. The three rejected `low`: the map e2e uses network tiles (same as an existing spec), the merge-to-rebuild window (documented), a dash beside a badge for a null-price Listing (state not demonstrated).

The implementation subagent was not re-engaged for the patches: a resumed agent reports back asynchronously in this host, which the unattended workflow forbids waiting on, so the patches were applied in the main session.

**Follow-up review: not recommended (false).** Patched counts by entry verdict: high 0, medium 1, low 9. The one medium patch is a conjunct on two static SQL fragments with a Postgres test of its own.

**Verification.**
- `validate.py --tier full` on commit `214f6e9b` (all code of the story): exit 1. Passed: lint, unit 2387 (1 skipped), test stack, alembic upgrade, integration 243, contract 75, frontend eslint, Vite build, harness 212 (9 skipped). `contract: alembic check` reports FAIL as it does on `main` (informational; this story changes no model and no migration). Failed: `e2e: playwright` — 116 of 122 tests could not launch a browser (`chrome-headless-shell.exe` missing; `C:/Users/Felipe/AppData/Local/ms-playwright` does not exist).
- The same e2e suite against the installed Chrome (temporary config in the session scratchpad, `channel: "chrome"`, port 5240, never committed), same commit: 122 passed, including the 12 new tests.
- `validate.py --tier backend` on the final commit: run after the commit that adds this spec (the spec cannot hold the result of a run on its own commit); the outcome is in the session report. The same tier passed on `3c04165e` during implementation (integration 242, contract 75).
- Matrix audit: every row has a passing test — rent / type switch / both / suppressed / no scoring row / out of range / export in `test_price_percentile_filter.py` (ran in the integration step) and `test_property_percentile_filter.py`; badge rounding, cutoff and dual card in `percentile-badge-filter.spec.js` (ran on Chrome only); saved search in `test_saved_search_filters.py` and the e2e.
- `git diff main -- src/tests/integration/test_percentile_characterization_lock.py`: only `LIST_ITEM_KEYS` and `PERCENTILE_KEYS` changed.

**Residual risks.**
- The Playwright e2e has not run under the gate, only against Chrome. Chrome and the Playwright Chromium are the same engine at different builds.
- Nothing was checked against the primary: the badge and the filter show what Story 1.6 stored there. Whether the filter needs an index was not measured.
- Stored percentiles drift between full recalculations and nothing schedules one (ledger DW-45). This story shows the stored value and adds no writer.
- `main` moved by one docs commit after this branch was cut; it touches no file of this branch.
- After the merge the primary needs its usual rebuild; until then the old API ignores the parameter and serves no percentile fields.

## Operator Confirmation

Confirmed 2026-10-08: the external actions this story owed were carried out.

- On the Windows host, install the browser the e2e step needs (a download from cdn.playwright.dev that the dev session had no permission to make): in C:\Workfolder\imoveis\.run\wt\1-7\frontend (or the primary checkout's frontend after the merge) run: npx playwright install chromium. Verify: C:\Users\Felipe\AppData\Local\ms-playwright contains chromium_headless_shell-1234.
- Run the full gate on the story branch (about 25 minutes; the harness tests take 23): from C:\Workfolder\imoveis\.run\wt\1-7 run C:\Workfolder\imoveis\.venv\Scripts\python.exe scripts/agent/validate.py --tier full. Verify: exit 0, 'VALIDATION PASSED (tier=full)', and the e2e step reports 122 passed. If an e2e test of percentile-badge-filter.spec.js fails there, the story goes back to dev instead of being confirmed.

_Appended by hand in place of `bmad-loop confirm` (the loop was not in use that day): the agent operator carried these actions out and recorded the evidence in the feature doc, and the story was advanced from `awaiting-operator` to `done`._
