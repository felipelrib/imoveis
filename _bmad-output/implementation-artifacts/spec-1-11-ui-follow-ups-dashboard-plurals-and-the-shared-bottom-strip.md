---
title: 'Story 1.11 — UI follow-ups: dashboard plurals and the shared bottom strip'
type: 'bugfix'
created: '2026-10-08'
status: done
baseline_revision: 'ee846be8b54f133bfc9d98b2e7273b8f305f1143'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/docs/features/_template.md'
  - '{project-root}/docs/features/v0.13-s2.6-ui-contract-debt.md'
warnings: ['oversized']
deferred:
  - summary: >-
      The e2e suite has no catch-all for unmocked /api calls, so a spec that forgets a mock
      silently sends the request through the Vite proxy to whatever listens on API_PORT.
    evidence: |-
      frontend/vite.config.js proxies /api to http://localhost:${API_PORT || 8000}, and
      frontend/tests/e2e/helpers/apiMocks.js installCommonMocks registers one route per endpoint
      with no fallback. Found on this story: every Dashboard case issued GET /api/system/alerts
      (frontend/src/api.ts fetchAlerts) unmocked, because the common mock matched /api/alerts**
      only; Vite logged proxy errors for it in an isolated run with API_PORT set to a dead port.
      That one read is mocked now. On this host port 8000 is the live primary API, and
      scripts/agent/validate.py passes API_PORT through its .env.local allowlist, so an unmocked
      write in a future spec could reach real data. Fix: a first-registered page.route("**/api/**")
      that fails the test (or aborts the request) for anything no later route claims.
    location: >-
      frontend/tests/e2e/helpers/apiMocks.js:415
    severity: medium
  - summary: >-
      In a window narrower than about 460px the compare bar's buttons overflow the bar's right
      edge.
    evidence: |-
      frontend/src/index.css .compare-bar now has max-width: calc(100vw - 32px), white-space:
      nowrap and a fixed height, and its pt-BR content with four selected is about 428px wide on
      one line; nothing wraps or shrinks. Before this story the bar had no max-width and ran off
      both sides of such a window instead, so the width was never supported; the product is
      desktop-only (EXPERIENCE.md) and the narrowest e2e width is 640px. Not covered by DW-55,
      which is about the save-search dialog and the compare view. A fix lets
      .compare-bar-actions shrink or wrap and makes the toast offset follow the bar's real
      height.
    location: >-
      frontend/src/index.css:632
    severity: low
  - summary: >-
      A toast can cover the lower right of the detail side panel for the four seconds it is up;
      the bottom-strip rule covers toast against compare bar only.
    evidence: |-
      .toast-stack is fixed at right: 16px with z-index 9999 and each toast takes pointer events;
      .detail-panel is z-index 500 and reaches the bottom of the viewport on the right (full
      content width at 900px and below). This has been so since the panel shipped (Story 1.8);
      with the compare bar on screen the stack now sits 65px higher over the panel. A click
      dismisses the toast. Whether toasts should move left of the panel or the panel should
      reserve the strip is a UX decision.
    location: >-
      frontend/src/index.css:1252
    severity: low
  - summary: >-
      DESIGN.md's toast line does not state the bottom-strip sharing rule; it still says only
      that a toast never covers the filter bar.
    evidence: |-
      _bmad-output/planning-artifacts/ux-designs/ux-imoveis-2026-08-05/DESIGN.md line 243. The
      rule chosen by Story 1.11 (the compare bar owns the strip; the stack starts 8px above it
      while it is on screen, at every width) is recorded in
      docs/features/v0.14-s1.11-ui-follow-ups-plurals-and-bottom-strip.md, in the index.css
      comment block and in the toast-contract e2e header. Editing a planning artifact from a
      story branch also invalidates the cached epic context for stories running in parallel.
    location: >-
      _bmad-output/planning-artifacts/ux-designs/ux-imoveis-2026-08-05/DESIGN.md:243
    severity: low
  - summary: >-
      Scraper Control still interpolates counts into fixed plurals (1 processados, 1 pulados,
      1 erros).
    evidence: |-
      frontend/src/i18n/locales/pt-BR.json scraper.activeProgress
      ("— {processed} processados, {skipped} pulados, {errors} erros") and scraper.logCounts
      ("{processed} processados, {skipped} pulados, {errors} falharam") carry three counts each
      with no One/Many selection. Outside Story 1.11, which names the dashboard keys; the same
      fragment-per-count split used for dashboard.enrichSkippedNoImages applies.
      locale-stale-polling.spec.js pins the plural form of logCounts.
    location: >-
      frontend/src/i18n/locales/pt-BR.json:405
    severity: low
---

<intent-contract>

## Intent

**Problem:** Two v0.13 UI follow-ups are still open. `v0.13-fu12`: the dashboard interpolates a count into a fixed plural, so one queued Property reads `1 enfileirados` in pt-BR. `v0.13-fu13`: the toast stack and `.compare-bar` share the bottom of the viewport and only stay apart by geometry proven at 1280×720; in a narrower window a toast can cover the compare bar and take its clicks for the 4 s it is up.

**Approach:** Split every live dashboard count key into the catalogs' existing `…One` / `…Many` pair selected with `n === 1` at the call site, delete the keys no call site names, and pin the result in the catalog-parity unit test. Give the bottom strip one structural rule in CSS — while the compare bar is on screen the toast stack sits above it, at every width — and pin it with narrow-viewport e2e cases.

## Boundaries & Constraints

**Always:**
- Work only in the git worktree `C:\Workfolder\imoveis\.run\wt\1-11` (branch `feat/v0.14-s1.11-ui-follow-ups`). Never touch the primary checkout `C:\Workfolder\imoveis`, anything under `.bmad-loop/`, `sprint-status.yaml`, `.env.local` or `deferred-work.md`.
- On this host `localhost:6379`, `:5433`, `:8000` and `:5173` are the LIVE primary stack. Never run raw `pytest` or `npx playwright test` against it. Tests run through `C:\Workfolder\imoveis\.venv\Scripts\python.exe scripts/agent/validate.py --tier frontend` from the worktree root. A single Playwright spec may be run while developing only with `PLAYWRIGHT_PORT` set to a free port in 5200–5299 and every `/api` call of the spec mocked. No docker compose command against project `imoveis`.
- Plural convention is the existing one: `…One` when `n === 1`, `…Many` otherwise (0 included), both keys in `en` and `pt-BR` with identical placeholders.
- Every string lands in both catalogs; no catalog value contains `percentil`, `P25` or `≤`.
- The sharing rule lives in `frontend/src/index.css`; `ToastProvider` and the page do not import or measure each other.
- Toasts stay bottom-anchored, at most two, clear of the filter bar (DESIGN.md toast contract).
- Conventional commits on the branch; do not merge, push or run `ship.py`.

**Never:**
- No new i18n plural mechanism or library; no change to `frontend/src/i18n/index.ts`.
- No restyling of toasts to DESIGN tokens, no `desfazer` action, no dismiss API.
- No redesign of the save-search dialog or the compare view (DW-55) and no inert/focus change under the detail scrim (DW-57); neither may get worse.
- Scraper Control count strings (`scraper.activeProgress`, `scraper.logCounts`) are outside this story.
- No backend, API schema or config change.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Enrich-missing, one queued | `queued_enrichments: 1, skipped_no_images: 0` | pt-BR result line `✔ 1 enfileirado para enriquecimento` | No error expected |
| Enrich-missing, many + one skipped | `queued_enrichments: 3, skipped_no_images: 1` | `✔ 3 enfileirados para enriquecimento (1 pulado — sem imagens)` | No error expected |
| Enrich-missing, one + many skipped | `queued_enrichments: 1, skipped_no_images: 2` | `✔ 1 enfileirado para enriquecimento (2 pulados — sem imagens)` | No error expected |
| Re-run, one queued, one photo-gated | `queued: 1, skipped_too_few_photos: 1` | result line contains `Enfileirado 1` and `1 bloqueado pelo filtro de fotos` | No error expected |
| Re-run, many | `queued: 2, skipped_too_few_photos: 3` | contains `Enfileirados 2` and `3 bloqueados pelo filtro de fotos` | No error expected |
| Dry run | `would_queue: 7` | contains `Enfileiraria 7` (unchanged) | No error expected |
| Ollama models | 1 model / 2 models loaded | `1 modelo carregado` / `2 modelos carregados` | No error expected |
| Toasts, no compare bar | any width | stack rests on the 16px bottom inset, right-aligned | No error expected |
| Toasts + compare bar, 900×720 and 640×720 | compare mode, ≥1 selected, 2 toasts up | stack's lower edge is above the bar's top edge; boxes do not intersect; `compare-clear` and `compare-open` receive their clicks while the toasts are up | No error expected |
| Toasts + compare bar + detail panel, 900×720 | panel open (full content width), bar visible | same rule holds; bar still clickable | No error expected |
| Compare view open | bar unmounted | stack back on the bottom inset | No error expected |

</intent-contract>

## Code Map

- `frontend/src/i18n/locales/pt-BR.json`, `en.json` — `dashboard` namespace, lines ~285 and ~315–328. Live: `modelsLoaded`, `enrichResultOk`, `enrichResultOkSkipped`, `rerunSkipPhotoGate`, `verbQueued`. Unreferenced anywhere in `frontend/src` (grep, no dynamic `t(\`…\`)` key exists): `rerunWouldQueue`, `rerunQueued`. Invariant, leave: `rerunSkipNoImages`, `rerunSkipMissingPrior`, `verbWouldQueue`, `rerunResultOk`, `toastRerunOk`.
- `frontend/src/pages/Dashboard.tsx` — `:89` `modelsLoaded`; `:269-274` `handleEnrichMissing` (`enrichResultOk*`); `:300-310` `handleEnrichmentRerun` (`verb`, `rerunSkipPhotoGate`). Result lines render under `data-testid="enrich-missing-result"` / `"enrichment-rerun-result"`; the Ollama sub-line in the services card.
- Call-site pattern to copy: `frontend/src/pages/Properties.tsx:745` (`compareIds.length === 1 ? '…One' : '…Many'`).
- `src/tests/unit/test_i18n_catalog_parity.py` — `_PLURAL_PINS`, `_RETIRED_KEYS` (drives both the catalog check and the quoted-key source scan), pairing test. Append a Story 1.11 block in the style of the 1.7/1.8/1.10 blocks.
- `frontend/src/components/ToastProvider.tsx:119-136` — container is inline-styled `position: fixed; bottom: 16; right: 16; zIndex: 9999; maxWidth: 380; pointerEvents: none`; each toast `pointerEvents: auto`. `data-testid="toast-container"` / `"toast"`.
- `frontend/src/index.css:632-648` — `.compare-bar` (`fixed; bottom: 24px; left: 50%; translateX(-50%); z-index: 900; min-width: 280px`, content-sized, no max-width). Layers: `.detail-scrim` 499, `.detail-panel` 500 (full content width at ≤900px, `:1484`), `.compare-view` 950, `.dialog-overlay` 1000, toasts 9999. `:root` token block near `:1224`.
- `frontend/src/pages/Properties.tsx:741-768` — the bar mounts only when `compareMode && compareIds.length > 0 && !compareOpen`; it stays mounted over the detail panel and under the save-search dialog overlay.
- `frontend/tests/e2e/toast-contract.spec.js` — the 2.6 case (1280×720, frozen clock, two compare-limit toasts + export failure). It asserts the stack rests within 20px of the viewport bottom **with the compare bar visible**; that assertion changes with the new rule. `frontend/tests/e2e/dashboard.spec.js:76-165` — pins `3 enfileirados para enriquecimento`, `Enfileiraria 7`, `Enfileirados 2`. Helpers: `frontend/tests/e2e/helpers/apiMocks.js` (`installCommonMocks`, `mockPropertiesList`, `mockPropertyDetail`, `mockPropertiesExport`, `PROPERTIES_PAGE_FIVE`, `SYSTEM_STATUS`).
- `docs/features/_template.md` — feature doc template; `docs/features/v0.13-s2.6-ui-contract-debt.md` — where both follow-ups were recorded.

## Tasks & Acceptance

**Execution:**
- `frontend/src/i18n/locales/pt-BR.json`, `frontend/src/i18n/locales/en.json` -- replace `enrichResultOk`, `enrichResultOkSkipped`, `rerunSkipPhotoGate`, `verbQueued`, `modelsLoaded` with `…One`/`…Many` pairs; `enrichResultOkSkipped{One,Many}` take `{n}` and `{skipNote}`, the note coming from a new pair `enrichSkippedNoImages{One,Many}` (`{n} pulado — sem imagens` / `{n} pulados — sem imagens`); delete `rerunWouldQueue` and `rerunQueued` -- the count and its noun agree; dead copy is not split.
- `frontend/src/pages/Dashboard.tsx` -- select each pair with `n === 1` (the verb by the queued count, the skip note by the skipped count) -- only the call site knows the count.
- `src/tests/unit/test_i18n_catalog_parity.py` -- pin the new pairs verbatim in both locales, add the seven replaced/removed keys to the retired list, and assert `Dashboard.tsx` names every new key -- AC1's pin.
- `frontend/src/index.css`, `frontend/src/components/ToastProvider.tsx` -- move the container's position to a `.toast-stack` class reading `bottom: var(--toast-stack-bottom)`; give the compare bar a tokenised bottom and height and a `max-width` inside the viewport; raise `--toast-stack-bottom` above the bar with `:root:has(.compare-bar)`; clamp the stack's width to the viewport -- one rule, no geometry luck.
- `frontend/tests/e2e/toast-contract.spec.js` -- adapt the 1280 case to the rule; add narrow cases (900×720, 640×720, 900×720 with the detail panel open, compare view open) asserting non-intersection, stack above bar, and that the bar's buttons take clicks while toasts are up -- AC2's pin.
- `frontend/tests/e2e/dashboard.spec.js` -- cover the matrix rows for the dashboard (singular and plural result lines, models line) with mocked `/api` routes.
- `docs/features/v0.14-s1.11-ui-follow-ups-plurals-and-bottom-strip.md` -- feature doc from the template, all sections; record the closure of `v0.13-fu12` and `v0.13-fu13`, the sharing rule and why, the keys split and removed.

**Acceptance Criteria:**
- Given both catalogs, when swept, then no `dashboard.*` value interpolates a count into a fixed plural noun or uses an `(s)` dodge, the five keys named by the story are either split into One/Many or removed as unreferenced, and the parity unit test fails if a retired key returns to a catalog or a call site.
- Given a viewport narrower than 1100px with the compare bar and two toasts on screen, when the user clicks a compare-bar button, then the click reaches the bar and no toast overlaps it — also with the detail panel open.
- Given no compare bar on screen (plain grid, compare view, Dashboard), when a toast is raised, then it rests on the bottom inset as before.
- Given the frontend gate, when `validate.py --tier frontend` runs on the final commit, then it exits 0.

## Spec Change Log

## Review Triage Log

### 2026-10-08 — Review pass
- verdicts: 34 findings — high 0, medium 3, low 21, false 10, maybe-false 0
- findings:
  - `[low]` `[patch]` Blind: the re-run e2e rows cannot detect a selection wired to the wrong count (both counts singular or both plural) — added mixed rows 1 queued / 2 gated and 2 queued / 1 gated to `dashboard.spec.js`.
  - `[medium]` `[patch]` Blind: "a drift in the bar's height fails the gate" is untrue, the bar's height and the stack's offset come from one token so the gap is 8px for any value — `expectStackAboveTheCompareBar` now asserts the count and both buttons lie inside the bar's box; e2e header and feature doc reworded.
  - `[low]` `[defer]` Blind: below about 460px the buttons overflow the bar, and the doc pointed at DW-55, which does not cover it — the width was never supported (the bar ran off the viewport before); deferred item added, doc pointer corrected.
  - `[low]` `[patch]` Blind: the feature doc's Changes table omitted `apiMocks.js` and the save-search dialog case — table and Notes updated.
  - `[medium]` `[defer]` Blind: the `/api/system/alerts` mock fixes a separate leak silently and no catch-all stops the next one — the leak predates this story; BUG note added to the feature doc, the missing catch-all deferred.
  - `[false]` `[reject]` Blind: `_DASHBOARD_PLURAL_PINS` duplicates `_PLURAL_PINS` — the file keeps one pin table and one test block per story (1.7, 1.8, 1.10); a per-story block is the file's convention and no caller diverges.
  - `[low]` `[patch]` Blind: `test_story_1_11_retired_keys_are_in_the_shared_retired_list` compares two copies of one literal — tuple and test deleted.
  - `[low]` `[patch]` Blind: the `(s)` guard was limited to `dashboard.*` — no catalog value contains `(s)` any more, so the guard is catalog-wide (`test_no_catalog_value_dodges_agreement`).
  - `[low]` `[patch]` Blind: the source-scan docstring implied it checks the `n === 1` selection — docstring now says what it checks and names the e2e rows that check the rest.
  - `[low]` `[patch]` Blind: the singular re-run toast (`toastRerunOk`) had no coverage — the re-run rows assert the toast text.
  - `[low]` `[patch]` Blind: the detail-panel case ended without a position assertion — `expectStackOnTheBottomInset` added after `compare-clear`.
  - `[low]` `[reject]` Blind: the `n === 1 ? One : Many` selection is inlined five times, a helper would be safer — the repo inlines it at every call site (Properties, SavedSearchRow, MapView); a helper is new public surface and the spec forbids a new plural mechanism.
  - `[low]` `[defer]` Blind: the rule is not recorded in DESIGN.md — recorded in the feature doc, CSS and e2e header, which satisfies the AC; the planning-artifact edit is deferred.
  - `[false]` `[reject]` Blind: nothing closes the tracker keys and the owner may not exist — this run's orchestrator owns `sprint-status.yaml` and the merge; the story branch must not write it.
  - `[low]` `[patch]` Blind: wording contradictions (a "rejected" width clamp that is in the patch; "neither surface knows about the other") — doc says the clamp was rejected as the sharing mechanism, comment says neither component imports the other.
  - `[low]` `[defer]` Edge: bar content overflows below about 460px — same root cause as the blind finding above; one deferred item.
  - `[false]` `[reject]` Edge: taller button text spills past the fixed 57px box — the bar is `box-sizing: border-box` with 12px padding and `align-items: center`, so content must grow by more than 24px before it leaves the box; the new containment assertion covers the tested widths.
  - `[low]` `[reject]` Edge: a response without `queued_enrichments` renders a literal `{n}` — `src/api/admin.py:449` always sends it; the behaviour predates this change and a `?? 0` guard would report "0 queued" for a malformed response.
  - `[low]` `[reject]` Edge: a re-run response without `queued` / `would_queue` renders `{n}` — same reasoning, unchanged by this story.
  - `[medium]` `[patch]` Gap: the 8px-gap assertion cannot see a wrong `--compare-bar-height` and nothing checks the bar fits its content — same root cause as the blind height finding; containment assertion added.
  - `[low]` `[reject]` Gap: the stack's viewport width clamp is not exercised below 412px — the product is desktop-only, the narrowest supported e2e width is 640px, and a case would need a contrived long message to prove a one-line guard.
  - `[false]` `[reject]` Gap (other): the loop's pre-merge verify runs the backend tier, so the e2e does not run there — this run was told to gate on the frontend tier and did; `.bmad-loop/policy.toml` is the orchestrator's file.
  - `[low]` `[patch]` Gap (other): the source scan is not behavioural coverage — docstring corrected (same entry as the blind docstring finding).
  - `[low]` `[patch]` Gap (other): the 900px panel case does not assert the stack's position after `compare-clear` — assertion added (same entry as the blind finding).
  - `[false]` `[reject]` Intent: keys beyond the five named were split (`verbQueued`, `modelsLoaded`, new `enrichSkippedNoImages`) — the AC says the catalog is swept and the fu12 note names `modelsLoaded`; `verbQueued` renders in the same sentence as a named key and the skip note is the second count of a named key. Disclosed in the feature doc.
  - `[false]` `[reject]` Intent: `en` strings are not rendered by an e2e case — `en` pairs are pinned verbatim by the unit test and five of six hold identical text.
  - `[false]` `[reject]` Intent: the dry-run path has no new case — `verbWouldQueue` is unchanged and the BIN-95 case pins `Enfileiraria 7`.
  - `[low]` `[patch]` Intent: `toastRerunOk` is not pinned — same entry as the blind toast finding.
  - `[false]` `[reject]` Intent: toasts move at 1280 too, outside "narrower than ~1100px" — the follow-up asked for a decision on how the strip is shared and the AC asks for the chosen rule to be recorded; ~1100px is where the defect shows, and a breakpoint would repeat the geometric luck. Product-visible, reported.
  - `[low]` `[patch]` Intent: nothing runs between 901 and 1099px, where the panel is a side panel over a scrim — the panel case now runs at 900 and 1000.
  - `[low]` `[defer]` Intent: the toast-over-panel relationship is neither defined nor asserted — predates this story (Story 1.8); deferred as a UX decision.
  - `[false]` `[reject]` Intent: saved-search-row and Scraper Control toasts are not raised by a new case — the rule is caller-agnostic CSS on the one container; a Dashboard toast and two Properties toasts are measured.
  - `[low]` `[defer]` Intent: "recorded" could mean the design contract — same entry as the blind DESIGN.md finding.
  - `[false]` `[reject]` Intent: in the panel case only `compare-clear` is clicked and in the dialog case no bar button is — both buttons are clicked at 1280, 900 and 640; under the dialog overlay the bar is not meant to be clickable.

## Design Notes

**Sharing rule.** The compare bar owns the bottom strip. While `.compare-bar` is in the document the toast stack starts above it (`bar bottom + bar height + 8px`); otherwise it rests on the 16px inset. It is one rule at every width, not a breakpoint: the bar is content-sized and its width depends on the locale, so any pixel threshold repeats the geometric luck `v0.13-fu13` was filed for. Rejected: a width clamp on the toast (no room left beside a centred bar below ~700px), moving the compare bar (it is pinned by three compare specs and by muscle memory), and a page-measured offset pushed into the provider (couples the app-root provider to one page). `:has()` keeps both components ignorant of each other; the bar's height becomes a token so the offset is arithmetic, and the e2e measures real boxes so a drift in either fails.

```css
:root { --toast-stack-bottom: 16px; --compare-bar-bottom: 24px; --compare-bar-height: 56px; }
:root:has(.compare-bar) {
  --toast-stack-bottom: calc(var(--compare-bar-bottom) + var(--compare-bar-height) + 8px);
}
```

Pick `--compare-bar-height` from the bar's measured natural height (padding 12px + `btn-sm` + 1px borders) so the bar does not visibly change; keep its content on one line.

**Two extra keys.** `verbQueued` (`Enfileirados 1`) sits in the same rendered sentence as `rerunSkipPhotoGate`, and `modelsLoaded` (`modelo(s) carregado(s)`) was named in the fu12 note as the dodge; the AC says the catalog is swept, so both are split here. In `en` a pair may hold the same text twice (`Queued`), as `countFavourited*` already does.

## Verification

**Commands:**
- `C:\Workfolder\imoveis\.venv\Scripts\python.exe scripts/agent/validate.py --tier frontend` (from the worktree root) -- expected: exit 0, with eslint, vite build and the Playwright e2e all run.
- `C:\Workfolder\imoveis\.venv\Scripts\python.exe scripts/agent/validate.py` (auto tier, final commit, clean tree) -- expected: exit 0.

## Auto Run Result

Status: done

**Summary.** Both v0.13 follow-ups are closed. `v0.13-fu12`: every live dashboard count string is a `…One` / `…Many` pair selected with `n === 1` in `Dashboard.tsx`; two unreferenced keys are deleted. `v0.13-fu13`: the compare bar owns the bottom strip — while `.compare-bar` is in the document the toast stack starts 8px above it, at every width; otherwise it rests on the 16px inset. The rule is CSS only (`:root:has(.compare-bar)`), pinned by e2e at 1280, 900 and 640px, with the detail panel open (900, 1000), the save-search dialog open and the compare view open.

**Catalog keys (`dashboard.`).** Split: `enrichResultOk`, `enrichResultOkSkipped`, `rerunSkipPhotoGate` (named by the story), `verbQueued`, `modelsLoaded` (found by the sweep). New pair: `enrichSkippedNoImages{One,Many}`, the second count of `enrichResultOkSkipped`, passed as `{skipNote}`. Removed as unreferenced: `rerunWouldQueue`, `rerunQueued`.

**Files changed.**
- `frontend/src/i18n/locales/pt-BR.json`, `en.json` — the pairs above; two keys deleted.
- `frontend/src/pages/Dashboard.tsx` — selects each pair by its own count.
- `frontend/src/index.css` — strip tokens, `:root:has(.compare-bar)` rule, `.toast-stack`; the compare bar gets a tokenised bottom and height (57px, its measured natural height), a max-width and one-line content.
- `frontend/src/components/ToastProvider.tsx` — container position moved from inline style to `.toast-stack`.
- `src/tests/unit/test_i18n_catalog_parity.py` — verbatim pins for the 12 keys in both locales, 7 retired keys, catalog-wide `(s)` guard, source scan of `Dashboard.tsx`.
- `frontend/tests/e2e/toast-contract.spec.js` — strip cases; the 2.6 case adapted to the rule.
- `frontend/tests/e2e/dashboard.spec.js` — result lines, re-run toast and models line in singular, plural and mixed counts.
- `frontend/tests/e2e/helpers/apiMocks.js` — `installCommonMocks` mocks `GET /api/system/alerts` (one unexpected file).
- `docs/features/v0.14-s1.11-ui-follow-ups-plurals-and-bottom-strip.md` — feature doc; records the closure of both follow-ups.

**Decisions.**
- One rule at every width, so toasts on `/properties` sit 65px higher whenever the compare bar is up, also at 1280px where they used to rest beside it. Product-visible.
- `verbQueued` and `modelsLoaded` are split although the story names five keys; in `en` a pair may hold the same text twice.
- The `{skipped}` placeholder of `enrichResultOkSkipped` became `{skipNote}`, a fragment that already agrees with its own count.
- The compare bar's height became a fixed token; the e2e asserts its content fits.
- DW-55 and DW-57 are untouched and not worse; the dialog and the compare view are covered by e2e with toasts up.
- No operator action.

**Review.** One pass, four layers, 34 findings: 14 rows patched (10 entries: 1 medium, 9 low), 6 rows deferred (4 entries; a fifth deferred item, the Scraper Control plurals, comes from planning), 14 rejected (10 false, 4 low) — each reason is in the triage log. No intent gap, no spec loopback. The patches were applied by the parent session: resuming the implementation subagent is asynchronous on this host, which the workflow forbids.

**Follow-up review recommendation: false.** Patched entries by verdict: high 0, medium 1, low 9.

**Verification.**
- `validate.py --tier frontend` on the reviewed tree: exit 0 — pre-commit, 2874 unit tests, eslint, vite build, 189 Playwright tests passed.
- The two changed specs also ran alone on an isolated Vite (`PLAYWRIGHT_PORT` 5243) with `API_PORT` pointed at a dead port: 38 passed, no proxy error.
- The gate is run again on the final commit by the session; its result is in the session's final report.

**Residual risks.**
- `:has()` carries the rule; a browser without it falls back to the old overlap.
- The fixed bar height is correct for the current button and padding metrics; the e2e containment check guards the tested widths in pt-BR only.
- Not checked by eye in a real browser window; the geometry is asserted by Playwright in headless Chromium.
