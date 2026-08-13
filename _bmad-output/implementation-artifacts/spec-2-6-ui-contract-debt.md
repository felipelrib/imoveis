---
title: 'Story 2.6 — UI contract debt: toast anchoring + pt-BR plural agreement'
type: 'bugfix'
created: '2026-08-13'
status: 'done'
baseline_revision: '69f1559738013a7e12925c8a002b8239fe558e24'
final_revision: '2260f6ac2a77bc08a55bdc8437c33f0834b1e79a'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-imoveis-2026-08-05/DESIGN.md'
warnings: ['multiple-goals', 'oversized']
---

<intent-contract>

## Intent

**Problem:** Two shared-surface defects that every later Epic 2 UI story would inherit and re-pin. (1) `ToastProvider` anchors top-right and stacks unbounded, while the DESIGN.md toast contract is bottom-anchored, max two stacked, never covering the filter bar (UX-DR3). (2) Four pt-BR catalog keys interpolate a count into a hardcoded plural noun, so the v0.13-s1.6 locale flip — which made pt-BR everyone's default — now shows `1 selecionados`, `1 imóveis`, `1 favoritos`, `1 quartos` to every user, and two e2e specs pin the defective singular verbatim (UX-DR1).

**Approach:** Flip the toast container to bottom-anchored, cap the rendered stack at two (newest wins, evicted timers cleared), and give container + item stable testids so position and stacking become assertable. Split the four keys into `…One`/`…Many` pairs following the catalog's existing `modal.listingCountOne`/`listingCountMany` idiom, select at the call site with `n === 1`, and lock both halves: a new Python catalog test (parity + verbatim values, runs in `validate.sh fast`) and corrected/added Playwright assertions that still pin exact copy.

## Boundaries & Constraints

**Always:**
- Every new or changed string lands in **both** `en.json` and `pt-BR.json` (NFR-7). Placeholder sets must match across catalogs.
- The pt-BR rule is `n === 1 → One`, everything else (including `0`) → `Many`.
- Plural selection happens at the **call site** (`t(cond ? 'aOne' : 'aMany', …)`) — the custom `t()` has no pluralization and must not grow one.
- Where the count is passed through `formatNumber(...)`, branch on the **raw** number, never on the formatted string.
- Corrected e2e assertions stay **verbatim exact-copy pins** (`toHaveText`) — never relaxed to regex/`toContainText`/removed.
- Toast dismiss behaviour, `role="status"`, `aria-live="polite"`, `tabIndex`, and the Enter/Space/Escape handler stay exactly as they are (BIN-157 coverage depends on them).
- Frontend changes are verified only through `bash scripts/agent/validate.sh` — never raw `npm test`/`npx playwright`.

**Block If:**
- Making the toast bottom-anchored proves to structurally collide with `.compare-bar` (fixed, `bottom: 24px`, centred, z-index 900) in a way that cannot be resolved by horizontal offset alone without coupling the provider to a page's layout.

**Never:**
- Do not add a frontend unit-test runner (vitest/jest/RTL) — a new dependency plus new gate wiring is out of scope; the catalog half is locked Python-side, the render half by Playwright.
- Do not restyle toast colours to DESIGN's `surface-elevated`/`border-hairline` tokens and do not add the optional `desfazer` action. The AC names anchoring and stack depth; the type-coded colours carry semantics DESIGN does not address. Record both as follow-ups in the feature doc.
- Do not touch the other catalog keys carrying the same defect (`properties.platformsBadge`, the `dashboard.rerun*` family, `dashboard.modelsLoaded`) — out of the story's four. Record them as a follow-up.
- No refactor of `Properties.tsx`/`MapView.tsx` beyond the call sites named below.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Singular count | `compareIds.length === 1` | `1 selecionado` / en `1 selected` | No error expected |
| Plural count | `compareIds.length === 2` | `2 selecionados` (unchanged) | No error expected |
| Zero count | `totalResults === 0` | `0 imóveis` — plural branch | No error expected |
| Formatted plural | `totalResults === 1200` | `1.200 imóveis` — branch on raw `1200`, render formatted | No error expected |
| Third toast | 3 toasts raised in sequence | Exactly 2 rendered; oldest evicted, its timer cleared | No error expected |
| Toast placement | any toast visible | Container sits in the bottom half of the viewport and its box intersects neither the filter bar nor `.compare-bar` | No error expected |

</intent-contract>

## Code Map

- `frontend/src/components/ToastProvider.tsx` -- container anchored `top:16,right:16` (L82-92), unbounded append (L71), 4000 ms default; all styles inline, no CSS module.
- `frontend/src/i18n/locales/en.json` / `pt-BR.json` -- 529 leaf keys, identical key sets and line numbers. Targets: `common.bedsShort` (L58), `properties.countProperties` (L124), `properties.countFavourited` (L125), `properties.compareSelected` (L191). Pattern to copy: `modal.listingCountOne`/`listingCountMany` (L472-473).
- `frontend/src/i18n/index.ts` -- custom `t(locale, key, params)`; `{name}` interpolation only, no plural support. Do not extend.
- `frontend/src/components/PropertyModal.tsx:405` -- the reference idiom: ternary inside the `t()` key argument.
- `frontend/src/pages/Properties.tsx` -- L490-491 header count (`n` is pre-formatted via `formatNumber`; header `<div>` has no testid), L664 compare-bar count (`data-testid="compare-count"`), L81 compare-limit warning toast.
- `frontend/src/components/MapView.tsx:283` -- sole `common.bedsShort` consumer, inside a maplibre popup built by DOM.
- `frontend/src/index.css:632-648` -- `.compare-bar` fixed `bottom:24px`, centred, z-index 900 — the bottom-edge neighbour the toast must not cover.
- `frontend/tests/e2e/compare-select.spec.js:45` and `compare-map-select.spec.js:67` -- the two defective `"1 selecionados"` pins.
- `frontend/tests/e2e/deep-links.spec.js:42+` -- favourites test; its mock returns `total: 1`, and `PROPERTIES_PAGE` is `total: 1` — the singular surfaces for `countFavourited`/`countProperties`.
- `frontend/tests/e2e/{credential-gate,properties-export,backfill-card}.spec.js` -- existing toast flows that must stay green (`backfill-card.spec.js:114` is the story-1.6 lease-conflict toast).
- `src/tests/unit/test_locale_registry_hygiene.py` -- precedent for a Python unit test that reads `frontend/` sources.
- `scripts/agent/validate.sh:189-200` -- Playwright runs in scope `all` only; `fast` covers Python unit tests.

## Tasks & Acceptance

**Execution:**
- [x] `frontend/src/components/ToastProvider.tsx` -- change container anchor `top: 16` → `bottom: 16` (keep `right: 16`, `maxWidth: 380`, column, gap 8, `pointerEvents: 'none'`); add `MAX_VISIBLE_TOASTS = 2` and trim oldest-first in `showToast`, clearing evicted timers via the existing `timersRef`; add `data-testid="toast-container"` on the container and `data-testid="toast"` on each item -- makes the contract satisfiable and assertable.
- [x] `frontend/src/i18n/locales/en.json` + `pt-BR.json` -- replace the four keys with `…One`/`…Many` pairs in both catalogs, keeping each pair adjacent at the original key's position -- one plural form per key is the catalog's established model.
- [x] `frontend/src/pages/Properties.tsx` -- L664 select on `compareIds.length === 1`; L490-491 select on raw `favouritesData.total` / `totalResults` while still passing the `formatNumber` result as `n`; add `data-testid="results-count"` to the header count `<div>` (L488) -- enables the singular header assertion.
- [x] `frontend/src/components/MapView.tsx:283` -- select on `featProps.bedrooms === 1`.
- [x] `src/tests/unit/test_i18n_catalog_parity.py` -- new: en/pt-BR key-set parity, per-key placeholder-set parity, verbatim pins for the eight new values in both catalogs, and an assertion that the four old keys are gone -- durable NFR-7 guard plus the catalog-side regression lock.
- [x] `frontend/tests/e2e/compare-select.spec.js:45`, `frontend/tests/e2e/compare-map-select.spec.js:67` -- correct the pin to `"1 selecionado"` (still `toHaveText`) -- the defect these specs currently freeze.
- [x] `frontend/tests/e2e/deep-links.spec.js` -- add verbatim `results-count` assertions: `"1 favorito"` in the favourites test, `"1 imóvel"` in the properties-list test -- covers the two singular surfaces no spec pins today.
- [x] `frontend/tests/e2e/toast-contract.spec.js` -- new: raise the compare-limit warning three times (click a 5th selection ×3 with 4 already selected), then assert exactly 2 toasts render, the container's box sits in the bottom half of the viewport, and it intersects neither the filter bar nor `.compare-bar` -- the position/stacking coverage the AC calls for and that does not exist today.
- [x] `docs/features/v0.13-s2.6-ui-contract-debt.md` -- new feature doc from `docs/features/_template.md`, all sections; Notes/Follow-ups records the deferred toast tokens + `desfazer`, the untouched sibling plural keys, and the `compare-view.spec.js` finding below.

**Acceptance Criteria:**
- Given four properties are already selected for compare, when a fifth selection is attempted three times, then exactly two toasts are rendered, both bottom-anchored, and neither overlaps the filter bar or the compare bar.
- Given the pt-BR default locale, when any of the four surfaces shows a count of exactly 1, then the noun is singular (`1 selecionado`, `1 imóvel`, `1 favorito`, `1 quarto`) and every count ≠ 1 keeps its existing plural form verbatim.
- Given the corrected specs, when the suite runs, then the count assertions still pin exact copy via `toHaveText` — none is weakened to a regex, a substring, or deleted.
- Given the shared provider changed, when the full suite runs, then every pre-existing toast flow still passes — specifically the story-1.6 lease-conflict toast (`backfill-card.spec.js:114`) and the keyboard-dismiss test (`credential-gate.spec.js:50`).
- Given NFR-7, when `validate.sh fast` runs, then the catalog parity test fails on any key present in only one catalog.
- Given the merge gate, when `bash scripts/agent/validate.sh all` runs, then it is green including the full Playwright suite.

## Spec Change Log

## Review Triage Log

### 2026-08-13 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 11: (high 0, medium 4, low 7)
- defer: 4: (high 1, medium 3, low 0)
- reject: 7: (high 0, medium 0, low 7)
- addressed_findings:
  - `[medium]` `[patch]` The new toast spec could not fail on the eviction rule it existed to prove — three identical compare-limit messages read the same whether the newest two or the oldest two survive. Rewrote it to raise two warnings then a *different* toast (a failing CSV export) and assert the surviving pair by identity and order.
  - `[medium]` `[patch]` The geometry assertions raced the 4 s auto-dismiss, and the container renders unconditionally, so a drained stack meant either a null bounding box or vacuously-true overlap checks. Froze the page clock (`page.clock.install()`), added an explicit `height > 0` guard, and turned the drain check into a deterministic `clock.runFor`.
  - `[medium]` `[patch]` The catalog test had no structural invariant and covered only the two hardcoded locales. Added a One/Many pairing check (sibling exists, same placeholders) with a documented exemption for `operations.throughputOne`/`throughputBelowOne`, which pair with `throughputLine`, and made parity glob every catalog on disk against `en`.
  - `[medium]` `[patch]` The feature doc's sibling-plural follow-up named keys that are not defective (`properties.platformsBadge` is guarded by `platformCount > 1`; `throughputLine`/`etaLine` already have singular variants) while omitting the ones that are. Corrected the list against the call sites and minted `v0.13-fu12`.
  - `[low]` `[patch]` Nothing asserted the stack was *bottom*-anchored — a low-sitting `top:`-anchored container passed. Added a bottom-inset assertion beside the bottom-half check.
  - `[low]` `[patch]` `ShowToast`'s contract drifted: the returned id may name an already-evicted toast, and a `duration: 0` toast is sticky against the timer but not against eviction. Documented both on the exported type.
  - `[low]` `[patch]` The new timer-reconcile effect owned orphaned timers but not unmount: pending timers would fire `setToasts` against a dead tree. Added a mount-scoped effect whose cleanup clears them (kept separate, since the reconcile effect's deps would clear live timers on every change).
  - `[low]` `[patch]` `MapView` compared an untyped GeoJSON property bag with `=== 1`, so a string `"1"` would re-render `1 quartos` on the one surface with no render coverage. Coerced with `Number(...)`.
  - `[low]` `[patch]` The catalog test's docstring claimed the pins were "the regression lock for that class of defect" while the feature doc correctly conceded they are not. Rewrote it to state the scope limit: these are copy locks, not agreement locks.
  - `[low]` `[patch]` `_flatten` silently dropped non-string leaves and could let two paths collide on one dotted key, making a value invisible to every check. Made both conditions assert.
  - `[low]` `[patch]` The corrected premises lived only in this spec. Recorded them in place in `epics.md` (both ACs) and in the `sprint-status.yaml` story comment so the next session does not re-derive "three compare specs".

### 2026-08-13 — Review pass (follow-up)

- intent_gap: 0
- bad_spec: 0
- patch: 9: (high 0, medium 1, low 8)
- defer: 4: (high 0, medium 4, low 0)
- reject: 21: (high 0, medium 0, low 21)
- addressed_findings:
  - `[medium]` `[patch]` The retired-key guard only ever looked at the catalogs, which is the half that cannot fail visibly: `t()` falls back to the raw key, so a resurrected `t('properties.countProperties')` renders that dotted string to a user while all four catalog assertions stay green. Added `test_no_call_site_still_names_a_retired_key`, scanning `frontend/src` for the quoted retired names (quoted so `common.bedsShort` does not match `common.bedsShortOne`) with a non-vacuity assertion on the file list.
  - `[low]` `[patch]` The One/Many pairing invariant ran in one direction only, and the missing direction is the likelier one — a `…Many` added without its `…One` leaves the call site's singular arm rendering the raw key. Added the mirror check; verified zero orphans in both catalogs today.
  - `[low]` `[patch]` The two parity tests are parametrized over the non-`en` catalogs, so losing `pt-BR.json` would turn the NFR-7 guard into a *skip* rather than a failure. Added `test_a_second_catalog_exists_to_compare_against`, which is not parametrized and so cannot be skipped away.
  - `[low]` `[patch]` `_flatten`'s docstring claims a collision fails rather than hiding a value, but `json.loads` had already collapsed duplicate JSON keys last-wins before `_flatten` saw them. Added an `object_pairs_hook` that refuses duplicates, so the claimed invariant holds at both levels.
  - `[low]` `[patch]` `MapView` coerced the bedroom count for the agreement test but still passed the raw property-bag value as `{n}`, so `"01"` or `1.0` would agree correctly and render `01 quarto` / `1.0 quarto`. Coerced once into a local and fed both the branch and the copy.
  - `[low]` `[patch]` The `_UNPAIRED_SINGULAR_KEYS` comment misdescribed its own exemptions: `operations.throughputBelowOne` is a *below*-one form (`ritmo: menos de 1 imóvel/dia`), not the `~1 imóvel/dia` singular the comment quoted, and neither key hands off to `throughputLine` in the way described. Rewrote it, and recorded the rule's other blind spot — `operations.etaOneDay` is a genuine singular the suffix match never sees.
  - `[low]` `[patch]` The bottom-inset assertion was one-sided, and `boundingBox()` still reports a box for a container pushed below the fold, where a negative inset satisfied `<= 20`. Bounded it on both sides.
  - `[low]` `[patch]` The first correction comment inserted into `epics.md` left a doubled blank line. Removed.
  - `[low]` `[patch]` The feature doc's file list stopped at the ten product/test paths and omitted the tracking artifacts changed in the same commits, and two of its descriptions no longer matched the code. Added the tracking-artifact line and corrected both descriptions.

## Design Notes

**New keys (exact values, both catalogs):**

| Key | en | pt-BR |
|---|---|---|
| `properties.compareSelectedOne` / `…Many` | `{n} selected` / `{n} selected` | `{n} selecionado` / `{n} selecionados` |
| `properties.countPropertiesOne` / `…Many` | `{n} property` / `{n} properties` | `{n} imóvel` / `{n} imóveis` |
| `properties.countFavouritedOne` / `…Many` | `{n} favourited` / `{n} favourited` | `{n} favorito` / `{n} favoritos` |
| `common.bedsShortOne` / `…Many` | `{n} bed` / `{n} beds` | `{n} quarto` / `{n} quartos` |

Two en values are identical across One/Many by design — English does not inflect there, but both keys must exist so parity and the call-site ternary stay uniform.

**Two premises in the epic text are off; correct the work, not the epic.** (1) `compare-view.spec.js` asserts only `"2 selecionados"` (L85, L114) — already-correct plural, so it needs no edit; it is re-verified, not changed. (2) No e2e asserts toast position today, so "the e2e specs asserting toast position are updated" means writing that coverage.

**`common.bedsShort` is locked catalog-side only.** Its sole surface is a maplibre popup opened by a GL-layer feature click (`MapView.tsx:246`), not by the HTML markers the map spec drives — clicking it in headless chromium needs exact canvas coordinates and would be flaky. The verbatim catalog pin plus the call-site ternary is the deliberate coverage choice.

## Verification

**Commands:**
- `bash scripts/agent/validate.sh fast` -- expected: green; the new catalog parity test passes and fails if a key is dropped from one catalog.
- `bash scripts/agent/validate.sh all` -- expected: green including the full Playwright suite (e2e runs in `all` only), covering the corrected pins, the new toast contract spec, and every pre-existing toast flow.

## Auto Run Result

Status: done

### Implemented change

No new feature work this pass — this is the independent follow-up review the previous pass
recommended (`followup_review_recommended: true`), run against the same baseline diff. The
delivered change is unchanged in substance: **toast anchoring (UX-DR3)** — `ToastProvider`'s
container moved from `top: 16` to `bottom: 16`, the rendered stack capped at two with newest-wins
eviction and orphaned-timer reclaim, container and item carrying `data-testid`s; and **pt-BR plural
agreement (UX-DR1)** — the four count-bearing keys the v0.13-s1.6 locale flip promoted to every user
split into `…One`/`…Many` pairs in both catalogs, selected at the call site on `n === 1`, branching
on the raw count where the rendered value is `formatNumber`-formatted.

What this pass added is guard strength. The retired-key lock only ever looked at the catalogs, which
is the half that cannot fail visibly — `t()` falls back to the raw key, so a resurrected
`t('properties.countProperties')` renders that dotted string to a user while every catalog assertion
stays green. The scan of the call sites is now the other half of that lock.

### Files changed

- `src/tests/unit/test_i18n_catalog_parity.py` — `test_no_call_site_still_names_a_retired_key`
  (source scan, quoted keys, non-vacuity assertion on the file list); the reverse `…Many` → `…One`
  pairing check; `test_a_second_catalog_exists_to_compare_against` so an empty parametrization
  cannot skip the NFR-7 guard away; an `object_pairs_hook` refusing duplicate JSON keys; corrected
  `_UNPAIRED_SINGULAR_KEYS` commentary.
- `frontend/src/components/MapView.tsx` — the bedroom count is coerced once and the coerced value
  feeds both the agreement branch and the copy (previously `"01"` agreed correctly but rendered
  `01 quarto`).
- `frontend/tests/e2e/toast-contract.spec.js` — the bottom-inset assertion is bounded on both sides;
  an off-screen container satisfied the one-sided bound.
- `docs/features/v0.13-s2.6-ui-contract-debt.md` — tracking artifacts added to the file list; two
  stale descriptions corrected.
- `_bmad-output/planning-artifacts/epics.md` — doubled blank line after an inserted comment.
- `_bmad-output/implementation-artifacts/deferred-work.md` — four new entries (existing entries
  untouched).

### Review findings

9 patches applied (1 medium, 8 low), 4 deferred (4 medium), 21 rejected. No intent gap and no
bad-spec loopback — `review_loop_iteration` stayed at 0. The rejects are dominated by findings that
restate the intent contract as a defect (eviction discards rather than queues — the contract says
"newest wins"; the `ShowToast` id may name an evicted toast — documented, and no caller reads the
return value, none passes `duration: 0`) and by coverage requests the existing pins already cover
(the raw-vs-formatted branch invariant is locked by the `1 imóvel` pin: branching on the formatted
string would break it). Deferred: the toast `aria-label`'s hardcoded English sentence (pre-existing,
NFR-7, invisible to catalog tests because the string is in no catalog); `test_locale_registry_hygiene.py`'s
frontend scan, which has never scanned a file because its glob uses brace expansion `Path.glob` does
not support against an extension the frontend no longer uses; follow-up key minting having no
allocator, so the parallel Wave 0 stories will both mint `v0.13-fu12`; and this worktree's absence
from the ports registry, leaving it on the bare default `PLAYWRIGHT_PORT=5177`.

Two reviewer claims were checked and rejected as wrong rather than merely low-value: `.toolbar` is
unique in the page tree (no strict-mode risk in the overlap assertion), and `favouritesData.total`
is typed from the API client rather than an untyped bag, so it needs no coercion the way the GeoJSON
property bag does.

### Verification

- `bash scripts/agent/validate.sh all` — **EXIT=0**, `[OK] VALIDATION PASSED`: lint/pre-commit,
  eslint, 2125 unit passed / 1 skipped (11 catalog-parity tests, including both new ones),
  114 integration, 51 contract, frontend build, and **110 Playwright passed** — `toast-contract.spec.js`
  with the tightened inset assertion, both corrected compare pins, both deep-links pins, and the
  pre-existing toast flows. The `alembic check` PostGIS line and the trailing dependency audit are
  advisory only.
- An earlier run of the same gate failed on the pre-commit `end-of-file-fixer`, which rewrote this
  spec file; the hook's edit was committed and the gate re-run to green, per the repo's fixer-hook rule.
- Not run: `finish-feature.sh`. This is a `bmad-loop/<run>/<story>` branch — the orchestrator owns
  merge-back and the `sprint-status.yaml` status flip.

### Residual risks

Unchanged from the previous pass, and none introduced by it: toast/compare-bar clearance is proven
at one viewport (`v0.13-fu13`); `common.bedsShort*` has no render coverage, only the catalog pin and
the call-site ternary; and the catalog tests are copy locks, not agreement locks — they cannot know
a noun ought to agree with its count, so a newly added `"{n} salvos"` would still pass. The
call-site scan added this pass narrows that last gap in one direction only: it catches a *retired*
key coming back, not a *new* unsplit key being introduced.

Newly recorded rather than newly created: `epic-2-context.md` and the `followups:` tail will both
conflict with story 2-7's parallel run, and this worktree holds the default Playwright port without
a registry reservation, so two concurrent `validate.sh all` runs in this wave can collide on it.
