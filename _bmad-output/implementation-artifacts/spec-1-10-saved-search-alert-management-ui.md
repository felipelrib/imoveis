---
title: 'Story 1.10 — Saved-search alert management UI and the per-search drop alert'
type: 'feature'
created: '2026-10-08'
status: done
baseline_revision: 'c03f16fe5c94a528b3bb13ce26ce0d54676413c2'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/docs/features/v0.14-s1.9-saved-search-new-match-detection.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-imoveis-2026-08-05/DESIGN.md'
warnings: ['oversized']
deferred:
  - summary: >-
      The watchlist path records a price as announced before anything delivered it, so a
      watchlist alert that is debounced or fails to send is never retried.
    evidence: |-
      src/core/dedupe.py _check_watchlist_alerts sets watchlist.last_notified_price right after
      send_price_drop_alert.delay(...). The task (src/adapters/queue/tasks.py
      send_price_drop_alert) returns early under the one-hour debounce key, sends through every
      channel, and EmailNotifier.send / send_batch swallow SMTP errors; with digest_mode the
      email only leaves at the 08:00 digest. The stamp also survives a later rise: a Listing
      stamped at 3000 that goes up and falls back to 3000 is 0% below the stamp and fires
      nothing. Since the follow-up review (2026-10-08) the saved-search drop pass no longer
      reads this stamp, so the defect is confined to the watchlist path's own alerts. The
      primary had 0 watchlist rows on 2026-10-08. Fix belongs there: stamp after delivery, or
      record which Listing and channel announced the price and when.
    location: >-
      src/core/dedupe.py:465
    severity: medium
  - summary: >-
      The watchlist price-drop email does not state the threshold that fired it, which the UX
      contract asks of every alert email.
    evidence: |-
      EXPERIENCE.md, Notifications and Recall: every alert email states the threshold that fired
      it. EmailNotifier.send_batch writes "Property <id>: old -> new (-x%)" with no threshold
      (src/adapters/notify/email_notifier.py). Story 1.10 covers the saved-search drop email
      only; the watchlist threshold is a percent stored per watch (watchlist.min_drop_pct) and
      PriceDropAlert does not carry it.
    location: >-
      src/adapters/notify/email_notifier.py:43
    severity: low
  - summary: >-
      The SPA has no display name for the zapimoveis platform, so the saved-search row's summary
      (and every other place that calls formatPlatform) shows the slug.
    evidence: |-
      frontend/src/labels.ts PLATFORM_LABELS has olx and quintoandar only; formatPlatform falls
      back to the slug. src/adapters/scrapers/zapimoveis.py exists, and the drop email names the
      platform ZapImóveis (core/saved_search_price_drops.py _PLATFORM_NAMES). Pre-existing in
      labels.ts; adding the label changes cards and filters outside this story.
    location: >-
      frontend/src/labels.ts:6
    severity: low
---

<intent-contract>

## Intent

**Problem:** Story 1.9 gave every saved search an alert switch and a stored minimum-drop threshold, but nothing in the SPA shows or edits them, and `min_price_drop` is read by no rule, so the drop email that must state its threshold (FR-32, UX-DR13) does not exist.

**Approach:** Turn each Buscas salvas row into the saved-search row of the UX contract (name, filter summary, alert switch, inline minimum-drop threshold, honest muted state) writing through `PATCH /saved-searches/{id}`, and add the per-search drop rule: once a day the hourly saved-search sender emails, per search, the Listings of matching decidable Properties whose own price fell by at least the search's threshold since drop alerts were switched on, each line reading `queda de R$ 240 — seu mínimo: R$ 100`.

## Boundaries & Constraints

**Always:**
- Nothing is switched on by default or in bulk: a new or existing search stays off, the save dialog gains no alert option, and a drop alert needs both the switch on and a threshold stored. An empty threshold means no drop alerts.
- The threshold is absolute reais on the Listing's headline price. `0` means any drop (more than zero).
- A drop is measured on one Listing against that Listing's own earlier price: the price of this search's last drop email for it, else the price in force when drop alerts became active for the search (`price_drop_enabled_at`), else the Listing's first recorded price after that moment. A cheaper Listing appearing on another platform is not a drop.
- Covered Properties: active, matching the search through `build_property_where` (the grid's own `WHERE`), decidable (`DECIDABLE_SQL`), search matchable. An unmatchable search (`new_match_alerts_supported: false`) sends nothing of either kind.
- One price drop never produces two emails for the same reason: a Listing whose current price is the price the watchlist path already announced for that Property (`watchlist.last_notified_price`) is left out of the saved-search drop email.
- Email channel only through `get_notifiers_for_channel("email")` (AD-9, UX-DR12), the single principal (AD-11), read-only on Property / Listing / price history (AD-3). Claim the day under the search's row lock, commit, send with no lock or transaction open, then record; a failed send gives the day back.
- The drop pass runs inside the existing hourly task `tasks.send_saved_search_new_match_alerts`; no new beat entry, no `expires`.
- UI: Meia-noite tokens inside `.meia`, hairline-separated `surface-card` rows, name in body type, filter summary in meta type, accent only on interactive controls, tabular numerals; optimistic switch with revert and a non-blocking error toast; every string in `en` and `pt-BR`.
- Rule logic in `src/core/` is written test-first; no adapter import in core; static SQL with bound values.

**Never:**
- No real email, no connection to a mail server, no read of `.env.local`.
- No global threshold, no bulk "enable all", no percent threshold for saved searches.
- No change to the new-match matcher, to the watchlist alert path, to `core/dedupe.py`, to `src/api/schemas.py`, or to the filter wire (`SAVED_SEARCH_WIRE_KEYS`).
- No Alertas panel, no desktop push (Epic 5). No dedicated Buscas salvas route: the rows stay where they are, in the Painel sidebar section of that name.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Drop at the threshold | switch on, threshold 100, Listing 3.240 at enable, now 3.000, Property matches and is decidable, window due | one email to the email channel; line `queda de R$ 240 — seu mínimo: R$ 100`; one alert row (reference 3240, new 3000, threshold 100); day stamped | none |
| Below the threshold | same, now 3.200 | no email, no row, day stays open | none |
| Cumulative drops | 3.240 → 3.190 → 3.130, threshold 100 | one email, drop 110 | none |
| Already alerted | alert row at 3.000, price still 3.000 next day | nothing; a later 2.950 with threshold 100 does nothing, 2.890 alerts with drop 110 | none |
| No threshold / switch off | `min_price_drop` null, or `notify_new_matches` false | no drop email | none |
| Threshold 0 | 3.240 → 3.239 | alert, `seu mínimo: R$ 0` | none |
| Drop before activation | price fell before `price_drop_enabled_at` | nothing | none |
| Cheaper Listing appears | second platform lists the Property lower, no Listing fell | nothing | none |
| Property not matching, inactive, or not decidable | drop exists | nothing now; alerted on a later day once it matches and is decidable and the drop still holds | none |
| Watchlist already announced it | `watchlist.last_notified_price` equals the Listing's current price | left out | none |
| Unmatchable search | filters carry `q` | counted `unsupported`, nothing sent | none |
| More than the limit | 25 drops, limit 20 | 20 largest drops in the email, `+5` line, only those 20 recorded | none |
| Send fails | notifier raises | no row, day given back, `errors` counted, task does not raise | next hourly run retries |
| No email channel | alerts disabled or no `email` channel | nothing sent, status `no_email_channel` | none |
| Activation stamp | PATCH switch on with a threshold stored, or threshold set while on | `price_drop_enabled_at` = now; changing the value while active, or switching off, leaves it | none |
| Row switch | click on an off row | PATCH `{"notify_new_matches": true}` at once, row shows on; survives reload | failure: row reverts, error toast |
| Row threshold | type `240`, Enter or blur | PATCH `{"min_price_drop": 240}`; empty sends `null`; survives reload | invalid text: not sent, field marked invalid; failure: value reverts, error toast |
| Muted row | `new_match_alerts_supported` false, switch off | no switch, no threshold field; a line says the search does not produce alerts | none |
| Muted row that is on | unsupported and `notify_new_matches` true | the same line plus the switch, so it can be switched off | none |

</intent-contract>

## Code Map

- `src/core/saved_search_alerts.py` -- 1.9 rules. Reuse `DECIDABLE_SQL`, `PROPERTIES_FROM_JOIN`, `match_filters_from_saved_search`, `window_is_due`, `local_window_date`, `_number`, `_COPY` separators, `_naive_utc`. Not changed except small public aliases if needed.
- `src/core/property_list_filters.py:203` -- `build_property_where(filters)`; first predicate `p.active = true`; aliases `p`, `ms`, `n`. Its bound names are unprefixed, so new parameters use the `pd_` prefix.
- `src/core/property_projection.py:493` -- `LIST_SELECT_COLUMNS`, `map_property_list_item` (title, neighbourhood, city, `public_id`) for the email blocks.
- `src/core/dedupe.py:318` -- `_record_price_change`: one open `price_history` interval per (`property_id`, `listing_type`, `platform`, `property_listing_id`); a change closes it (`end_ts`) and opens a new row. `:415` `_check_watchlist_alerts` sets `watchlist.last_notified_price = new_price` when it fires. Read-only for this story.
- `src/adapters/db/models.py:232` `PriceHistory` (index `ix_price_history_prop_type_platform` leads with `property_id`), `:252` `PropertyListing` (`active`, `price`), `:307` `Watchlist`, `:332` `SavedSearch`.
- `alembic/versions/f7a8b9c0d1e2_saved_search_new_match_alerts.py` -- current head; pattern for the new revision.
- `src/adapters/queue/tasks.py:1280-1610` -- 1.9 tasks; `_NEW_MATCH_LOCK_SEARCH_SQL` and the claim / send / mark / release order to mirror. `:1043` `evaluate_watchlist_alerts`, `:1113` `send_price_drop_alert` (watchlist path, untouched).
- `src/adapters/notify/base.py`, `__init__.py`, `email_notifier.py:118`, `log_notifier.py` -- `SavedSearchNewMatches`, `send_new_matches` (raises on failure, 30 s timeout), `get_notifiers_for_channel`.
- `src/infra/config.py:505` `NewMatchAlertsConfig`, `:538` `AlertsConfig`; `configs/app_config.yaml:438` `alerts`.
- `src/api/saved_searches.py` -- item / create / update models (not in `schemas.py`), `_ITEM_COLUMNS`, enable stamp at `:427`.
- `src/tests/unit/test_saved_search_alert_tasks.py` -- `_cfg`, `_session_with`, `_FakeNotifier`, `registry` fixture; exact result dicts at `:117`, `:260`.
- `src/tests/integration/test_saved_search_new_matches.py` -- Postgres seeding helpers and the fake email notifier injection to reuse.
- `src/tests/contract/test_api_contract.py:1131` -- `TestSavedSearchNewMatchContract`.
- `src/tests/unit/test_i18n_catalog_parity.py` -- parity, pairing, copy pins, jargon ban over both catalogs.
- `frontend/src/pages/Properties.tsx:156,307,433-460,479-500` -- saved-search state, handlers, sidebar rows; `:683` save dialog (`.dialog`).
- `frontend/src/api.ts:254,922` -- `SavedSearchItem`, saved-search calls.
- `frontend/src/index.css:1031-1110` sidebar rows; `:1243-1280` Meia-noite tokens and `.meia`; `:1582` `.detail-watch-input` (inline numeric field convention).
- `frontend/src/components/ToastProvider.tsx` -- `useToast()`; `frontend/src/i18n/locales/{en,pt-BR}.json` `properties.*`.
- `frontend/tests/e2e/saved-search-price-type.spec.js`, `helpers/apiMocks.js:498` -- mocked saved-search routes; e2e locale default `en`.
- `docs/api.md:143`, `docs/data-models-api.md` -- Saved Searches section and tables.

## Tasks & Acceptance

**Execution:**
- [x] `src/tests/unit/test_saved_search_price_drops.py` -- NEW, written first: the drop rule, per-Property selection, order, SQL shape, email text in both locales -- test-first for `src/core/`.
- [x] `src/core/saved_search_price_drops.py` -- NEW: `drop_amount`, `select_drops`, candidate SQL builder and `collect_drop_candidates`, `load_drop_properties`, `claim_drop_window` / `release_drop_window`, `record_drop_alerts`, `render_price_drop_email` -- the rule and its text in one pure module.
- [x] `alembic/versions/a8b9c0d1e2f3_saved_search_price_drop_alerts.py`, `src/adapters/db/models.py` -- two columns on `saved_searches` (`price_drop_enabled_at`, `price_drop_last_window_on`), table `saved_search_price_drop_alerts` with its lookup index; reversible; models mirror it.
- [x] `src/infra/config.py`, `configs/app_config.yaml` -- `alerts.price_drop` (`enabled`, `max_items_per_email`) -- tunables through `AppConfig`.
- [x] `src/adapters/notify/base.py`, `email_notifier.py`, `log_notifier.py` -- `SavedSearchPriceDrops` payload and `send_price_drops` (email raises on failure, shares the SMTP code of `send_new_matches`).
- [x] `src/adapters/queue/tasks.py` -- the drop pass, called from the hourly sender; its result under `price_drops`.
- [x] `src/api/saved_searches.py` -- stamp `price_drop_enabled_at`; return `price_drop_enabled_at` and `last_price_drop_alert_on`.
- [x] `src/tests/unit/test_saved_search_alert_tasks.py`, `test_new_match_notifier.py`, `test_config.py`, `test_saved_search_filters.py`, `src/tests/contract/test_api_contract.py`, `src/tests/integration/test_saved_search_price_drops.py` (NEW) -- task happy and error paths, notifier, config, API stamp, contract fields, the matrix on Postgres.
- [x] `frontend/src/api.ts`, `frontend/src/components/properties/SavedSearchRow.tsx` (NEW), `frontend/src/utils/savedSearchRow.ts` (NEW), `frontend/src/pages/Properties.tsx`, `frontend/src/index.css` -- the row, its summary, switch and threshold.
- [x] `frontend/src/i18n/locales/en.json`, `pt-BR.json`, `src/tests/unit/test_i18n_catalog_parity.py` -- strings in both catalogs, row copy pinned.
- [x] `frontend/tests/e2e/saved-search-alerts.spec.js` -- NEW: switch on + threshold edit persist after reload; failed PATCH reverts with a toast; muted row.
- [x] `docs/features/v0.14-s1.10-saved-search-alert-management-ui.md` (NEW), `docs/api.md`, `docs/data-models-api.md` -- feature doc (all template sections), API fields, tables.

**Acceptance Criteria:**
- Given saved searches exist, when the Painel sidebar shows Buscas salvas, then each row renders name, filter summary, alert switch and inline minimum-drop field whose values come from and are written to `/saved-searches`, with no global setting anywhere.
- Given a row is switched on and its threshold edited, when the page is reloaded, then both values are shown as stored.
- Given a drop alert fires, when the email is rendered, then every Property block states `queda de R$ <drop> — seu mínimo: R$ <threshold>` with the threshold stored for that search at send time, and the same threshold is recorded on the alert row.
- Given `python scripts/agent/validate.py` runs on the final commit, then it exits 0 including the backend tier (alembic check, contract tests) and the frontend tier (Playwright e2e).

## Spec Change Log

### 2026-10-08 — Follow-up review: the watchlist exclusion is withdrawn

- **Trigger.** The follow-up review was dispatched with an explicit ruling to make on the watchlist exclusion (keep it deferred, or take a safer rule when one is cheap inside the story). Verification found that the exclusion can leave a drop unannounced with no delivery failure involved: `watchlist.last_notified_price` survives a rise, so a Listing stamped at 3.000 that goes to 3.300 (the search's floor) and falls back to 3.000 fires no watchlist alert (0% below the stamp, `core/dedupe.py:451`) and was left out of the search's email by `_NOT_ANNOUNCED_BY_WATCHLIST`. The stamp is also written at enqueue, before the one-hour debounce and before delivery.
- **What changed.** The candidate statement no longer reads `watchlist`. The `<intent-contract>` text above is left as written (it is frozen); its "Always" bullet on the watchlist and the matrix row "Watchlist already announced it" no longer describe the code. Everything else in the contract holds. The epic (Story 1.10 in `epics.md`) never asked for the exclusion; it was this spec's own reading of "one drop, one email".
- **Known-bad state avoided.** A drop the user asked a search to announce, announced by nobody.
- **Failure direction taken.** A Property that is both watched and covered by a search with drop alerts can get two emails for one drop (the watchlist alert, then the search's email at the next window). The primary had 0 watchlist rows and 0 saved searches on 2026-10-08.
- **KEEP.** Everything else in the candidate statement and the claim / send / record order; the `pd_` parameter prefix; the threshold applied only by `drop_amount`.

## Review Triage Log

### 2026-10-08 — Review pass
- verdicts: 38 findings — high 0, medium 14, low 17, false 5, maybe-false 2
- findings:
  - `[medium]` `[patch]` Blind: two concurrent PATCHes (threshold on blur, switch on click) both read "inactive" and neither stamps `price_drop_enabled_at` — `update_saved_search` read the row without a lock; the read is now `FOR UPDATE`.
  - `[medium]` `[patch]` Blind: an active search with a NULL floor never sends while its row says it alerts — the migration now stamps the floor of searches that already have the switch on and a minimum stored; with the row lock no other path leaves an active search without a floor.
  - `[medium]` `[patch]` Blind: a Property with two Listings that fell is emailed again the next day for the smaller drop — only the shown Listing was recorded; `drops_to_record` now records every qualifying Listing of an emailed Property (unit test, integration test runs the next day).
  - `[medium]` `[patch]` Blind: the announced Listing is not held to the search's Listing-level filters (a Listing above `max_price`, or of the other type, on a Property another Listing qualifies) — confirmed in `build_drop_candidates_sql`; predicates `dl.listing_type = :price_type AND dl.price <= :max_price` and `dl.platform = :platform` added, reusing the shared bound values (unit and integration tests). Design Notes amended below; routed as patch, not as a spec loopback, because the fix is three predicates on one statement.
  - `[medium]` `[defer]` Blind: the watchlist exclusion can turn one drop into no email (stamp written at enqueue, before debounce and delivery; per Property) — true of the pre-existing watchlist path; deferred with the evidence.
  - `[maybe-false]` `[defer]` Blind: the candidate statement is unbounded and re-runs hourly for a search with nothing to send — the cost on the primary is unknown; `EXPLAIN ANALYZE` there settles it; deferred as medium (unverified).
  - `[low]` `[reject]` Blind: editing the filters or lowering the threshold of an active search releases old drops — real and the same rule as Story 1.9 (a filter edit does not move the floor); the SPA cannot edit stored filters and a lowered threshold is the user asking for those drops. Stated in the feature doc; a floor reset on edit would add a rule nobody asked for.
  - `[low]` `[patch]` Blind: out-of-order PATCH responses leave the row showing the other field's old value — `handlePatchSavedSearch` now takes only the written field (and the server stamps) from each response.
  - `[low]` `[patch]` Blind: focus is signalled by colour only on the name and delete buttons; the invalid message is not tied to the field — `outline: none` removed from both `:focus-visible` rules, `aria-describedby` added. The touch-size and hover-reveal remarks are rejected: desktop-only product, the delete button appears on focus.
  - `[low]` `[patch]` Blind: `parseDropThreshold` has no coverage of the comma grouping — covered by the e2e additions below (same root as the verification-gap finding). The "three decimals read as thousands" remark is `false` as a defect: centavos have two decimals, and both locales read `1.500` / `1,500` as grouping on purpose.
  - `[low]` `[reject]` Blind: the English email says "open Buscas salvas" — same wording as the shipped Story 1.9 English email, which a unit test pins; changing one of the two would make them disagree.
  - `[low]` `[reject]` Blind: platform display names are duplicated in core and core imports private names of the 1.9 module — a platform not in the map is shown as its slug (stated in the doc); no caller diverges today.
  - `[low]` `[reject]` Blind: the row does not show whether alerts are actually being sent — UX-DR13 lists name, summary, switch and threshold; the dates are in the API. Recorded as a decision in the feature doc.
  - `[false]` `[reject]` Blind: known defects are prose only, `deferred: []` — the list is filled by this pass; a fix that edits this spec is not a code finding.
  - `[low]` `[patch]` Blind: a rise after an alert leaves the reference at the last alerted price and nothing says it is intended — it is intended (an alert announces a price below the last announced one); now stated in the feature doc.
  - `[medium]` `[patch]` Edge: pre-migration active search has no floor — carried into the migration backfill above (same root).
  - `[medium]` `[patch]` Edge: concurrent PATCHes lose the stamp — same root as the row-lock patch above.
  - `[low]` `[patch]` Edge: out-of-order responses overwrite the row — same root as the merge patch above.
  - `[medium]` `[patch]` Edge: a platform search announces another platform's Listing — same root as the Listing-level predicates above.
  - `[medium]` `[patch]` Edge: an untyped search with a sale cap announces a rent Listing — same root as the Listing-level predicates above.
  - `[low]` `[reject]` Edge: the threshold can change between the claim and the send — a window of milliseconds to seconds; the email states the value that selected its drops, which is the coherent one. A re-read after the claim adds a branch for a case nobody meets.
  - `[low]` `[patch]` Edge: the drop pass raising outside its per-search handling loses the new-match result — the wrapper now catches it, logs `saved_search_price_drop_alerts_failed` and returns `price_drops` with status `error` (unit test).
  - `[medium]` `[defer]` Edge (claim): "the watchlist path already announced this price" rests on a stamp written at enqueue — same root as the deferred watchlist finding.
  - `[low]` `[defer]` Edge (claim): the watchlist stamp is per Property, compared with each Listing — same root, same deferred entry.
  - `[low]` `[reject]` Edge (claim): "threshold stored at send time" is the value read under the lock — same as the rejected claim-to-send window above.
  - `[medium]` `[patch]` Verification gap: the filter summary is asserted for one filter shape only — new e2e test with a sale search without a stored price type, a search carrying every summary part, a cap with no type and an empty search.
  - `[low]` `[patch]` Verification gap: comma-grouped input is never typed — the threshold e2e now types `1,500.50` (no write) and `1,600` (writes 1600).
  - `[medium]` `[patch]` Verification gap (other): the second Listing's smaller drop is emailed the next day — same root as `drops_to_record` above.
  - `[low]` `[patch]` Intent: the drop rule is only tested against hand-inserted `price_history` rows — integration test added that writes the change through `core.dedupe._record_price_change`.
  - `[medium]` `[defer]` Intent: the "never two emails" guard reads a stamp, not a delivery — same deferred watchlist entry.
  - `[false]` `[reject]` Intent: "round-trip ... persisting after reload" is proven against a mocked store — the repository's e2e convention (every spec mocks `/api`); the real API round trip of the same fields is in the integration tests.
  - `[medium]` `[patch]` Intent: the state line can say a search alerts while the backend would not send (NULL floor) — same root as the backfill and row-lock patches. Config switches off or no email channel remain invisible on the row, as in Story 1.9.
  - `[false]` `[reject]` Intent: Buscas salvas is a top-nav surface in EXPERIENCE.md — a recorded product call; the acceptance criteria ask for the row.
  - `[false]` `[reject]` Intent: two daily windows per search instead of one — a recorded product call (FR-32 batches new-match email; drops are a second reason).
  - `[false]` `[reject]` Intent: repeat alerts instead of once per pair — a recorded product call; a further drop of the threshold is news.
  - `[maybe-false]` `[defer]` Intent: the hourly task now re-runs the candidate statement for due searches — same deferred measurement entry.
  - `[low]` `[defer]` Intent: only the saved-search email states its threshold; the watchlist email does not — pre-existing path, deferred.
  - `[low]` `[patch]` Intent: the feature doc's decision table does not enumerate the product calls — table rewritten, product-visible calls first.

### 2026-10-08 — Review pass (follow-up, pass 2)
- verdicts: 41 findings — high 0, medium 8, low 24, false 9, maybe-false 0
- findings:
  - `[low]` `[reject]` Blind: the search's row lock is held while the candidate statement runs, and the PATCH's `FOR UPDATE` waits for it — real, and the same order as the Story 1.9 sender. Measured on the primary: the statement takes 0.46 to 0.70 s for a search without filters, once an hour per due search. Moving the statement out of the lock means a second read and a re-validation at claim time; not worth it for a sub-second wait. Stated in the feature doc.
  - `[medium]` `[patch]` Blind: three fixes of pass 1 (the PATCH row lock, the migration backfill, the per-field merge in `handlePatchSavedSearch`) have no test that fails without them — three tests added (rows of the verification-gap layer below); the first two were run against their mutants in the gate's backend tier and failed, the third fails by construction when the response replaces the row.
  - `[low]` `[reject]` Blind: the spec carries no evidence of the full gate on the final tree — true of pass 1's record, and a fix that edits this spec. The full tier is run on this pass's final commit; the commit that is validated contains this file, so the result is in the session report.
  - `[low]` `[patch]` Blind: the table is documented as "every row is a drop that was emailed" while `drops_to_record` also stores sibling Listings the email did not show — model docstring, migration docstring, core docstrings and `docs/data-models-api.md` now say one row per alerted Listing of an emailed Property.
  - `[low]` `[patch]` Blind: the core comment cites `frontend/src/labels.ts` as the source of three platform names and it has two; the feature doc's reason was wrong — comment and doc corrected. The missing `zapimoveis` label in the SPA is pre-existing and deferred.
  - `[low]` `[patch]` Blind: keyboard focus is invisible on a switch that is on (accent ring on an accent track) — the ring is an offset outline.
  - `[low]` `[patch]` Blind: the invalid-amount message is announced three times — the `title` is removed; `aria-describedby` and the `role="alert"` line stay.
  - `[low]` `[reject]` Blind: a muted row that is still on hides its stored threshold and is counted `searches_due` / `unsupported` every hour — counters only; the row offers the switch so it can be switched off, which is what ends it. Claiming a day for a search that sends nothing would add a write for a log number.
  - `[low]` `[reject]` Blind: no retention on the alert table and no index leading on `property_listing_id` for the cascade — at most `max_items_per_email` rows per search per day plus siblings; an index or a pruning rule is not warranted at that size.
  - `[low]` `[reject]` Blind: the threshold has no upper bound — a twenty-digit slip is visible in the field and in the state line it produces; a bound would be an arbitrary number.
  - `[low]` `[patch]` Blind: the parser is covered by a handful of typed inputs — the e2e now also types `1.500` (1500, never 1.5) and `1500,5` (1500.5).
  - `[false]` `[reject]` Blind: open ledger entries DW-55 and DW-63 are not mentioned — neither is a defect of this change: DW-55 is the save dialog (the intent leaves it untouched), DW-63 is the beat queue (the intent forbids a new beat entry or `expires` here). Both stay open in the ledger.
  - `[low]` `[patch]` Blind: the email's `+N` line counts a Property that went away since the statement ran — `remaining` is now what did not fit the limit (unit test).
  - `[medium]` `[patch]` Edge: a search for one listing type capped on the other (`listing_type: sale`, `price_type: rent`, reachable in the filter bar by changing the price type after the listing type) binds `dl.listing_type` to both values: no candidate ever, while the row says it alerts — the Listing-level cap is added only when the search type is absent or equals the cap's type (unit and integration tests).
  - `[low]` `[patch]` Edge: the alert row is dated at the run's clock, which can be earlier than a floor stamped after the run started; the row is then not read as a reference and the drop leaves again the next day — recorded with `max(now, floor)` (unit test).
  - `[low]` `[reject]` Edge: a PATCH waits for the unmeasured scan under the row lock — same root as the first Blind row; measured, under a second.
  - `[low]` `[reject]` Edge: a field holding only `R$` reads as empty and clears the threshold — the field never shows the prefix (it is in the label); typing only the prefix and leaving is an empty field in every sense the user can see.
  - `[low]` `[reject]` Edge (claim): "the threshold stored at send time" is the value read under the lock — carried from pass 1 (claim-to-send window, same code): the email states the value that selected its drops. The same holds for a switch turned off in that window: the decision is the read under the lock, as in the Story 1.9 sender.
  - `[medium]` `[patch]` Verification gap: the migration's backfill and its downgrade are never executed by a test — `TestPriceDropMigration` downgrades to `f7a8b9c0d1e2`, seeds five searches (on with a minimum, on with 0, on without, off with, off), upgrades and asserts which got a floor; fails with the backfill predicate inverted.
  - `[medium]` `[patch]` Verification gap: the PATCH row lock is not exercised — `test_api_patch_waits_for_a_concurrent_write_and_stamps_from_what_it_left` holds the row in a second connection, starts the PATCH in a thread, switches the search on and commits; fails without `FOR UPDATE`.
  - `[medium]` `[patch]` Verification gap: the SPA's "take only the written field" merge cannot be told from "replace the row" — e2e "two writes in flight" holds the switch answer, lets the threshold answer first, releases a stale switch body.
  - `[low]` `[patch]` Verification gap (other): "the reference only moves down" has no test with a rise in it — two integration tests (rise after an alert; rise then a fall short of the price at activation).
  - `[low]` `[patch]` Verification gap (other): both passes raising is untested — unit test: the new-match error is the one raised.
  - `[false]` `[reject]` Intent: drops have their own daily window, so two emails per search per day — carried from pass 1: a recorded product call.
  - `[false]` `[reject]` Intent: the announced Listing must satisfy the search's Listing-level filters, narrower than the literal contract — carried from pass 1 (patched there, Design Notes); this pass relaxes it for the crossed-type search only.
  - `[false]` `[reject]` Intent: the last-alert reference is discarded after an off/on cycle — the documented rule ("switching off and on starts the comparison over"), tested on Postgres.
  - `[low]` `[reject]` Intent: more than `max_items` rows can be written, and a sibling's next reference is a price no email stated — the decision of pass 1 (a Property is not emailed twice for one fall); the table's documentation now says so.
  - `[false]` `[reject]` Intent: the migration makes pre-existing switch-plus-threshold searches active — they were already on with a minimum stored; without a floor the row would say it alerts and never send. Nothing is switched on: the test asserts the three other states stay without a floor. The primary has no saved search.
  - `[low]` `[reject]` Intent: `no_email_channel` is reported only when a due search has a drop — the same rule as the Story 1.9 sender; a run with nothing to send has nothing to report.
  - `[false]` `[reject]` Intent: additions outside the contract (sidebar width, removed CSS, row lock, opening line, platform names) — each is a recorded decision in the feature doc.
  - `[low]` `[reject]` Intent: the task and `EmailNotifier.send_price_drops` are never joined in one test — joining them means an SMTP connection, which the story forbids; each side is tested against the same payload type.
  - `[low]` `[reject]` Intent: price history is hand-inserted — carried from pass 1 (a persist-path test was added there).
  - `[low]` `[reject]` Intent: the task glue is mostly asserted on mock sessions — the integration file runs the real task on Postgres for every matrix row, including the lock (search deleted mid-send).
  - `[false]` `[reject]` Intent: the Postgres tests of the pass-1 patches are not recorded as run — they ran in this pass (backend tier: 331 integration tests passed) and run again in the full tier on the final commit.
  - `[false]` `[reject]` Intent: "survives reload" is proven against a mocked store — carried from pass 1: the repository's e2e convention; the API round trip is in the integration tests.
  - `[medium]` `[patch]` Intent: the activation stamp under overlapping PATCHes and the out-of-order merge have no test — same root as the two verification-gap rows above.
  - `[medium]` `[patch]` Intent: the migration backfill has no test — same root as the verification-gap row above.
  - `[medium]` `[patch]` Intent: "the watchlist already announced it" reads a stamp, never a delivery (carried as deferred in pass 1) — re-verified at the dispatch's request and found worse than recorded: the stamp survives a rise, so a fall back to a stamped price is announced by neither path with no delivery failure at all. The exclusion is removed (Spec Change Log); the failure direction is one extra email. The watchlist path's own stamp-before-delivery stays deferred, reworded.
  - `[low]` `[reject]` Intent: the Meia-noite tokens are not asserted — a pixel assertion per token is not how this repository tests CSS; the e2e pins text, roles and requests.
  - `[false]` `[reject]` Intent: "written test-first" is not observable in a diff — it is in the history: `21fa60cf` (tests) precedes `b568de2c` (rule).
  - `[low]` `[reject]` Intent: "no bulk enable" rests on a source scan and one e2e — there is no endpoint or control that could enable in bulk to test against.
- measurements made by this pass (the dispatch's deferred items):
  - the candidate statement on the primary: 0.70 s (floor 30 days back, 1,575 rows) and 0.46 to 0.68 s (floor before all history, 2,756 rows) for a search without filters; `price_history` 321,691 rows, 32,983 closed. No index added; deferred item removed.
  - `price_history` rows without `property_listing_id` on the primary: 0; active Listings without a listing-scoped open interval: 0 of 288,164. Deferred item removed.

## Design Notes

- **Why the drop is detected at send time.** A drop is a comparison of two stored prices, so nothing has to be recorded when it happens. The sender computes the qualifying drops at the window, which gives the hold for free (a Property that is not decidable or does not match yet is looked at again the next day) and never emails a drop that was undone before the window.
- **Reference price**, per search × Listing: `COALESCE(new_price of the search's latest alert row for the Listing sent at or after price_drop_enabled_at, price_history price in force at price_drop_enabled_at, first price_history price after it)`. Recording the alerted price is what makes the next alert need a further drop of at least the threshold. Switching off and on moves `price_drop_enabled_at`, which starts the comparison over.
- **Candidates are bounded by changes, not by the search.** Only Listings that have a `price_history` interval closed after the floor (`end_ts > floor`) are examined, so a search without filters does not probe the history of every Property.
- **One email per search per local day for drops, separate from the new-match email**, same window hour and timezone (`alerts.new_match.window_*`), own stored date (`price_drop_last_window_on`). The 1.9 sender code path is not edited; the task runs the drop pass after it.
- **Row copy (pt-BR).** Switch label `Avisos por e-mail`; field label `Queda mínima` with `R$` prefix and placeholder `sem aviso`; state line `Avisos desligados` / `Avisa imóveis novos` / `Avisa imóveis novos e quedas a partir de R$ 100` / `Avisa imóveis novos e qualquer queda de preço`; muted `Busca por texto não gera avisos por e-mail.` (filters carry `q`) or `Esta busca não gera avisos por e-mail.`.
- **Email (pt-BR).** Subject `2 quedas de preço na busca “Savassi 2q”`. Block: title, place, `R$ 3.240/mês → R$ 3.000/mês · QuintoAndar`, `queda de R$ 240 — seu mínimo: R$ 100`, link when `app_base_url` is set. Footer says why the email was sent and where to change it.

- **Listing-level filters (added in review pass 1).** The announced Listing itself is of the search's listing type, within `max_price` for its `price_type`, and on the search's `platform`, when the search has those filters; `build_property_where` alone only says that some Listing of the Property is. Every qualifying Listing of an emailed Property is recorded (`drops_to_record`), not only the one shown.

- **Follow-up review (pass 2) amendments.** (1) The watchlist is not read: the `NOT EXISTS (... watchlist ...)` predicate and the `pd_owner` parameter of the candidate statement described below are gone, and `collect_drop_candidates` takes no `owner` (see the Spec Change Log). (2) The Listing-level price cap is added only when the search's listing type is absent or equals the cap's `price_type`; a search for one type capped on the other announces Listings of its own type. (3) `record_drop_alerts` is called with `now = max(run clock, floor)`. (4) The email's `remaining` is `max(len(drops) - max_items, 0)`.

### Working rules for the implementer (binding)

- Work only in the git worktree that contains this spec (`C:\Workfolder\imoveis\.run\wt\1-10`, branch `feat/v0.14-s1.10-saved-search-alert-management-ui`). Every shell call starts elsewhere: `cd` there first and pass absolute paths. Never touch the primary checkout `C:\Workfolder\imoveis` (except using its interpreter `C:\Workfolder\imoveis\.venv\Scripts\python.exe`; the worktree has no `.venv`), `.bmad-loop/`, `sprint-status.yaml`, `.env.local`, or the primary docker project `imoveis`. The primary Vite dev server on :5173 and the primary stack are live: leave them alone. Never run `migrate-primary.sh`, `ship.py`, a merge or a push.
- Read `AGENTS.md` and `CLAUDE.md` first. Never f-string SQL (a unit lint enforces it: concatenate static fragments, bind values). `get_logger` kwargs must not be `name`, `msg`, `args`, `level`.
- Never send a real email and never open a connection to a mail server. Tests patch `smtplib.SMTP` or inject a fake notifier through the registry.
- Single unit test files may be run with `C:\Workfolder\imoveis\.venv\Scripts\python.exe -m pytest <file> -p no:cacheprovider` from the worktree. Integration tests need Postgres and run only inside the gate. Frontend: `npm ci` then `npx eslint .`, `npm run build`, and single specs with `npx playwright test tests/e2e/<spec>` inside this worktree's `frontend/` (Playwright starts its own Vite on :5177).
- The gate is `C:\Workfolder\imoveis\.venv\Scripts\python.exe scripts/agent/validate.py` from the worktree (auto tier resolves to `full` for this diff, 30 to 40 minutes: run it with a long timeout or in the background and wait; if an unrelated test fails once under host load, run it again before concluding). It must exit 0 on the final commit with a clean tree.
- Commits: conventional (`test(v0.14-s1.10): ...`, `feat(v0.14-s1.10): ...`, `docs(v0.14-s1.10): ...`), the core rule's failing tests before or with the core module, everything committed on the branch, tree clean at the end. Do not edit the `<intent-contract>` or the frontmatter of this spec; tick the task boxes when done and commit this spec with the work.
- A shell heredoc whose body contains a single quote fails to parse on this host: write such files with the file-writing tool.
- Scope: more than 3 files outside the task list means stop and report instead of widening the change.

### Schema (revision `a8b9c0d1e2f3`, down_revision `f7a8b9c0d1e2`; models mirror it exactly so the alembic check is clean)

- `saved_searches`: `price_drop_enabled_at TIMESTAMP NULL` (naive UTC, the drop floor), `price_drop_last_window_on DATE NULL`.
- `saved_search_price_drop_alerts`: `id UUID PK default gen_random_uuid()`, `saved_search_id UUID NOT NULL FK saved_searches ON DELETE CASCADE`, `property_id UUID NOT NULL FK properties ON DELETE CASCADE` (indexed), `property_listing_id UUID NOT NULL FK property_listings ON DELETE CASCADE`, `owner VARCHAR NULL`, `listing_type VARCHAR NOT NULL`, `platform VARCHAR NULL`, `reference_price DOUBLE PRECISION NOT NULL`, `new_price DOUBLE PRECISION NOT NULL`, `threshold DOUBLE PRECISION NOT NULL`, `sent_at TIMESTAMP NOT NULL DEFAULT now()`; CHECK `ck_saved_search_price_drop_alerts_drop` (`new_price < reference_price AND threshold >= 0`); index `ix_saved_search_price_drop_alerts_lookup` on (`saved_search_id`, `property_listing_id`, `sent_at`). Every row is an alert that was emailed; there is no pending state.

### Core (`core/saved_search_price_drops.py`): no adapter imports, no lazy imports, SQLAlchemy `Session` allowed as in `core/saved_search_alerts.py`

- `MIN_DROP = 0.01`. `drop_amount(reference, current, threshold) -> float | None`: `None` unless all three are finite numbers, `reference > 0`, `current > 0`, `threshold >= 0`, and `reference - current` (rounded to centavos) is at least `MIN_DROP` and at least `threshold`.
- `select_drops(candidates, threshold) -> list[dict]`: `candidates` are the rows of the candidate query (`property_id, listing_id, listing_type, platform, current_price, reference_price`). Keeps the rows `drop_amount` accepts, one per Property (the largest drop; ties: lower current price, then listing id), each with `drop` added, ordered by drop descending, then property id. Pure.
- `build_drop_candidates_sql(filters, *, listing_type) -> (sql, params)` and `collect_drop_candidates(session, *, search_id, owner, filters, listing_type, floor)`: `SELECT p.id, dl.id, dl.listing_type, dl.platform, dl.price, COALESCE(<last alert>, <at floor>, <first after>) ...` over `PROPERTIES_FROM_JOIN` joined to `property_listings dl ON dl.property_id = p.id`, `WHERE <build_property_where predicates> AND <DECIDABLE_SQL> AND dl.active = true AND dl.price > 0 AND dl.id IN (SELECT ph.property_listing_id FROM price_history ph WHERE ph.end_ts > :pd_floor AND ph.property_listing_id IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM watchlist w WHERE w.property_id = p.id AND w.owner = :pd_owner AND w.last_notified_price IS NOT NULL AND abs(w.last_notified_price - dl.price) < 0.005)`, plus `AND dl.listing_type = :pd_listing_type` only when the search's `listing_type` is `rent` or `sale`. The three reference subqueries: last alert = `a.new_price` of `saved_search_price_drop_alerts a` for this search and `dl.id` with `a.sent_at >= :pd_floor`, latest first; at floor = `ph.price` with `ph.property_id = dl.property_id AND ph.property_listing_id = dl.id AND ph.start_ts <= :pd_floor AND (ph.end_ts IS NULL OR ph.end_ts > :pd_floor)`, latest `start_ts` first; first after = the same Listing's row with the earliest `start_ts > :pd_floor`. All new bound names start with `pd_`; alias `dl` (not `pl`). The threshold is applied by `select_drops`, not in SQL, so the rule has one implementation.
- `load_drop_properties(session, property_ids) -> dict[id, item]`: `LIST_SELECT_COLUMNS` over `PROPERTIES_FROM_JOIN WHERE p.id = ANY(CAST(:pd_property_ids AS uuid[]))`, mapped with `map_property_list_item`, `property_type` added as `collect_pending` does.
- `claim_drop_window`, `release_drop_window` on `saved_searches.price_drop_last_window_on` (same shape as `claim_window` / `release_window`).
- `record_drop_alerts(session, *, search_id, owner, drops, threshold, now) -> int`: one `INSERT ... SELECT` per drop from `saved_searches s JOIN property_listings dl ON dl.id = CAST(:pd_listing_id AS uuid) WHERE s.id = CAST(:pd_search_id AS uuid)`, so a search or Listing deleted during the send inserts nothing instead of failing.
- `render_price_drop_email(*, search_name, drops, properties, threshold, remaining=0, app_base_url="", locale="pt-BR") -> (subject, body)`: plain text, `pt-BR` and `en`. Per drop: `N. title` (title, else capitalised stored type, else `Imóvel`), place, `R$ old → R$ new` with `/mês` on both for rent and ` · <platform>` when stored, the threshold sentence, link `<app_base_url>/properties/<public_id>` only when the base URL is set. Money: whole reais without decimals, otherwise two decimals; pt-BR `1.234,50`, en `1,234.50`. pt-BR sentence exactly `queda de R$ {drop} — seu mínimo: R$ {threshold}`; en `drop of R$ {drop} — your minimum: R$ {threshold}`. Subject `1 queda de preço na busca “{name}”` / `{count} quedas de preço na busca “{name}”` (name collapsed to one line); en `1 price drop in “{name}”` / `{count} price drops in “{name}”`. Intro `1 imóvel desta busca baixou de preço.` / `{count} imóveis desta busca baixaram de preço.` `+{count} nesta busca chegam no próximo aviso.` when `remaining > 0`. Footer: `Você recebe este e-mail porque os avisos estão ligados para esta busca, com queda mínima de R$ {threshold}. Para mudar, abra Buscas salvas.`

### Config (`alerts.price_drop`, class `PriceDropAlertsConfig`)

`enabled: true` (switch of the drop pass; it also needs `alerts.new_match.enabled`, the master switch of the hourly sender task) and `max_items_per_email: 20` (>= 1). Window hour, timezone and `app_base_url` are read from `alerts.new_match`. The YAML comment says that nothing is sent while no search has both the switch on and a threshold.

### Notifier registry

- `base.py`: `SavedSearchPriceDrops(principal_id, search_id, search_name, subject, body, property_ids, generated_at)`; `Notifier.send_price_drops(batch)` non-abstract, raises `NotImplementedError`.
- `EmailNotifier.send_price_drops`: same behaviour as `send_new_matches` (empty recipient raises, 30 s timeout, re-raises on failure); factor the shared SMTP code into one private method instead of copying it, without changing `send_new_matches` behaviour (its unit tests stay unedited). Log events `saved_search_price_drops_email_sent` / `_failed`. `LogNotifier.send_price_drops` logs ids.

### Task (`adapters/queue/tasks.py`)

- `_send_saved_search_price_drop_alerts(cfg, now) -> dict` with keys `status` (`ok` / `skipped` / `no_email_channel`), `searches_due`, `emails_sent`, `properties_alerted`, `unsupported`, `errors`. `skipped` when `getattr(cfg.alerts, "price_drop", None)` is missing or its `enabled is not True` (the 1.9 unit tests build a config without it and must keep passing; only their exact-result assertions gain the `price_drops` key).
- Searches: `owner = auth.principal_id AND notify_new_matches AND min_price_drop IS NOT NULL AND price_drop_enabled_at IS NOT NULL`. Per search, in its own try block: lock the row (`FOR NO KEY UPDATE SKIP LOCKED`) re-reading `notify_new_matches, min_price_drop, price_drop_enabled_at, price_drop_last_window_on, name, filters`; skip when another run holds it, when it is no longer active, or when `window_is_due` (with `price_drop_last_window_on`) is false; count `searches_due`; translate the filters (`None`: count `unsupported`, continue); `collect_drop_candidates` then `select_drops` with the threshold read under the lock; none: continue with the day open; no email notifier: `no_email_channel`, continue; `claim_drop_window` + commit; cut to `max_items_per_email`; `load_drop_properties`; `session.rollback()` so no transaction is open; render; `send_price_drops` on each email notifier (failure: `errors` + log `saved_search_price_drop_alert_notifier_error`); at least one delivered: `record_drop_alerts` + commit, count; none delivered: `release_drop_window`. The `finally` mirrors the 1.9 sender (rollback, then give the day back when claimed and not delivered). Never raises for one search.
- `send_saved_search_new_match_alerts` keeps its body as it is in a helper or in place; after it (also when the master switch is on and the new-match part raised) the drop pass runs and its dict is returned under `result["price_drops"]`. With `alerts.new_match.enabled` off the task returns as today plus `"price_drops": {"status": "skipped", ...zeros}`. One info log `saved_search_price_drop_alerts_run` with the dict.

### API (`/saved-searches`, models stay in `src/api/saved_searches.py`)

- `SavedSearchItem` adds `price_drop_enabled_at: str | None` (naive UTC) and `last_price_drop_alert_on: str | None` (date). Read-only.
- Drop alerts are active when `notify_new_matches` is true and `min_price_drop` is not null. `POST` creating an active search, and a `PATCH` after which the search is active when it was not before, stamp `price_drop_enabled_at = now` (naive UTC). Any other write leaves the stamp. The existing `notify_enabled_at` rule is unchanged.

### Frontend

- `api.ts`: `SavedSearchItem` gains `notify_new_matches?`, `min_price_drop?`, `notify_enabled_at?`, `new_match_alerts_supported?`, `last_new_match_alert_on?`, `price_drop_enabled_at?`, `last_price_drop_alert_on?`; `updateSavedSearch(id, patch)` sends `PATCH`. `saveSearch` is unchanged (nothing is created on).
- `utils/savedSearchRow.ts` (pure): `savedSearchSummaryParts(filters)` returning ordered descriptors the row localises (listing type, property type, `max_price` with its `price_type`, min bedrooms, min parking, neighbourhood, city, percentile cap, platform, furnished, pets, min score, `q`), and `parseDropThreshold(text) -> { ok: true, value: number | null } | { ok: false }`: empty is `null`; accepts `240`, `1.500`, `1500,50`, `R$ 240`; rejects negatives, letters, non-finite. `formatDropThreshold(value, locale)` for the field and the state line.
- `components/properties/SavedSearchRow.tsx`: props `search`, `onApply`, `onDelete`, `onPatch(id, patch) => Promise<SavedSearchItem>`. Name is a `<button>` that applies the search (the existing e2e clicks the name text); delete button as today. Switch: `<button type="button" role="switch" aria-checked>` with `data-testid="saved-search-notify-<id>"`, optimistic, reverts and toasts `properties.toastAlertUpdateFailed` on failure, ignores clicks while its request is in flight. Threshold: text input `inputMode="decimal"`, `data-testid="saved-search-drop-<id>"`, commits on blur and Enter only when the parsed value differs from the stored one, `aria-invalid` on unparsable text (nothing sent), reverts and toasts on failure; `Escape` restores the stored value. State line `data-testid="saved-search-alert-state-<id>"`. Muted rows per the matrix (`data-testid="saved-search-alerts-muted-<id>"`). Row root `data-testid="saved-search-row-<id>"`.
- `Properties.tsx`: the list container carries `meia`; rows replace the inline `.sidebar-item` markup; `handlePatchSavedSearch` calls `updateSavedSearch` and replaces the item in state with the response. The save dialog is untouched.
- `index.css`: `.saved-search-list` (no max-height clipping of controls; scroll kept), `.saved-search-row` (`background: var(--surface-card)`, `border-bottom: 1px solid var(--border-hairline)`, first / last radius `var(--radius-meia-md)`), name 14px / 1.55, summary and state line 12.5px with `letter-spacing: 0.03em` in `var(--text-secondary)` / `var(--text-muted)`, switch track `var(--radius-meia-sm)` with `var(--accent)` when on, threshold field styled like `.detail-watch-input` with the value in `var(--accent)`; `font-variant-numeric: tabular-nums`. Sidebar width 220px to 272px so the control line fits. No gradient, no glow, no pill badge.
- Strings (`properties.*`, both catalogs; `…One` / `…Many` pairs where a count is interpolated): `savedSearchNotify`, `savedSearchMinDrop`, `savedSearchMinDropPlaceholder`, `savedSearchAlertsOff`, `savedSearchAlertsNew`, `savedSearchAlertsNewAndDrops` (`{amount}`), `savedSearchAlertsNewAndAnyDrop`, `savedSearchAlertsUnsupported`, `savedSearchAlertsUnsupportedQuery`, `savedSearchNoFilters`, the summary fragments, `toastAlertUpdateFailed`, `savedSearchMinDropInvalid`.

### Tests that must exist

- Unit, test-first (`test_saved_search_price_drops.py`): `drop_amount` (at, below and above the threshold, threshold 0, centavo noise, non-positive and non-finite inputs, price rise); `select_drops` (one per Property, tie-breaks, order); the candidate SQL carries every predicate of `build_property_where` for the same filters, `DECIDABLE_SQL`, the `end_ts > :pd_floor` bound, the watchlist exclusion, the listing-type predicate only for `rent` / `sale`, and no parameter name collides with the shared `WHERE`; email text in `pt-BR` and `en` (exact threshold sentence, `/mês` only for rent, decimals, `+N`, link only with a base URL, subject on one line).
- Unit (`test_saved_search_alert_tasks.py`): drop pass happy path (fake email notifier called once, log / redis never, rows recorded, day claimed before the send), notifier failure (not recorded, day released, no raise), no channel, not due, nothing qualifying, unsupported, pass disabled / config absent; the sender returns `price_drops`.
- Unit: `EmailNotifier.send_price_drops` with `smtplib.SMTP` patched; config defaults and validation; API stamp rule (`test_saved_search_filters.py` or the integration round trip).
- Contract: the two new item fields and their OpenAPI presence.
- Integration (`test_saved_search_price_drops.py`, Postgres through the gate, seeded like `test_saved_search_new_matches.py`): every matrix row from "Drop at the threshold" to "Activation stamp" except the SMTP-level one, with real `price_history` rows and the fake email notifier in the registry; models versus schema.
- Catalog: the row copy pinned in both locales in `test_i18n_catalog_parity.py`.
- e2e (`saved-search-alerts.spec.js`, mocked API store with `PATCH`): switch on and threshold `240` persist after `page.reload()`; a failing `PATCH` reverts the switch and shows the error toast; an unsupported row shows the muted line and no switch; the existing `saved-search-price-type.spec.js` still passes.

## Verification

**Commands:**
- `C:\Workfolder\imoveis\.venv\Scripts\python.exe scripts/agent/validate.py` -- expected: exit 0, tier `full` (lint, unit, integration, contract, alembic check, frontend lint + build + Playwright e2e, harness tests).
- `C:\Workfolder\imoveis\.venv\Scripts\python.exe -m pytest src/tests/unit/test_saved_search_price_drops.py -p no:cacheprovider` -- expected: all pass (development loop only).

## Auto Run Result

Status: done

**Summary.** Each Buscas salvas row in the Painel sidebar is now the saved-search row of the UX contract: name, filter summary, one alert switch and an inline minimum price drop, both written at once through `PATCH /saved-searches/{id}`, with an honest muted state for a search that cannot alert. Behind the field is the per-search drop rule: once per local day the hourly saved-search sender emails, per search, the Listings of matching decidable Properties whose own price fell by at least the search's minimum since drop alerts became active, each block reading `queda de R$ 240 — seu mínimo: R$ 100`. Nothing is on by default.

**Files changed.**
- `src/core/saved_search_price_drops.py` (new): the rule (`drop_amount`), selection, candidate statement, window claim, alert rows, email text.
- `alembic/versions/a8b9c0d1e2f3_saved_search_price_drop_alerts.py` (new), `src/adapters/db/models.py`: two columns on `saved_searches`, table `saved_search_price_drop_alerts`, one backfill.
- `src/adapters/queue/tasks.py`: the drop pass, run by `tasks.send_saved_search_new_match_alerts` after the new-match part; result under `price_drops`.
- `src/adapters/notify/base.py`, `email_notifier.py`, `log_notifier.py`: `SavedSearchPriceDrops`, `send_price_drops`.
- `src/infra/config.py`, `configs/app_config.yaml`: `alerts.price_drop`.
- `src/api/saved_searches.py`: activation stamp under a row lock; `price_drop_enabled_at`, `last_price_drop_alert_on`.
- `frontend/src/components/properties/SavedSearchRow.tsx` (new), `frontend/src/utils/savedSearchRow.ts` (new), `frontend/src/pages/Properties.tsx`, `frontend/src/api.ts`, `frontend/src/index.css`, both locale catalogs.
- Tests: `test_saved_search_price_drops.py` (unit, new; integration, new), `test_saved_search_alert_tasks.py`, `test_new_match_notifier.py`, `test_config.py`, `test_saved_search_filters.py`, `test_i18n_catalog_parity.py`, `test_api_contract.py`, `frontend/tests/e2e/saved-search-alerts.spec.js` (new).
- Docs: `docs/features/v0.14-s1.10-saved-search-alert-management-ui.md` (new), `docs/api.md`, `docs/data-models-api.md`.

**Review.** One pass, four layers, 38 findings: 14 medium, 17 low, 5 false, 2 maybe-false (several share a root).
- Patched entries: 4 medium (activation stamp lost to concurrent writes or to a pre-migration search; a second fallen Listing emailed the next day; announced Listing outside the search's price cap, type or platform; summary line under-tested) and 7 low (stale row after out-of-order responses, focus outline and `aria-describedby`, comma-grouped input untested, drop pass failure losing the new-match result, persist-path integration test, doc decision table, the reference rule stated).
- Deferred: 4 entries in the frontmatter (watchlist stamp before delivery; candidate statement unmeasured on the primary; watchlist email without its threshold; Listings without listing-scoped price history).
- Rejected, with reasons in the triage log: floor not moved by a filter edit; English email wording shared with Story 1.9; platform names in core; no last-email date on the row; threshold changing between claim and send (two rows); mocked e2e store; Buscas salvas as a sidebar section; two daily windows; repeat alerts; touch-size remarks; the `deferred: []` remark.

**Follow-up review: recommended (true).** Patched this pass, by entry: high 0, medium 4, low 7. The medium patches changed the rule after the reviewers read it: the candidate statement gained Listing-level predicates, the task now records sibling Listings, the API takes a row lock and the migration backfills a floor. None of that was seen by a reviewer.

**Verification.**
- Gate on the pre-review commit `51aa0d78`: `validate.py`, tier `full`: 2682 unit, 322 integration, 80 contract, 162 Playwright e2e passed.
- After the patches: the four touched unit files (184 tests), `eslint`, and the two saved-search e2e specs (7 tests) passed.
- The gate on the final commit is run after this file is committed (the commit it validates contains this file), so its result is in the session report, not here.
- No email was sent and no mail server was contacted: tests use a recorder notifier or a patched `smtplib.SMTP`.

**Residual risks.**
- The drop statement's cost on the primary is unknown (deferred).
- A watchlisted Property's drop can be emailed by nobody when the watchlist path stamps and does not deliver (deferred, pre-existing path).
- Switching a search on is what lets real email leave on a configured host; with a minimum stored, drop emails start the next morning window.
- The primary needs the migration `a8b9c0d1e2f3` and a rebuild of API, workers, beat and frontend after the merge (the orchestrator's routine step; nothing else is required of the operator).

### Follow-up review pass (2026-10-08)

Status: done

**What this pass did.** A fresh four-layer review of the whole diff (41 findings), plus the checks the dispatch asked for: the drop rule against each state `price_history` can hold, the activation stamp, the sender's failure directions, the watchlist overlap, the statement's cost on the primary, the migration, the API contract, the row and the email text.

**Changed by this pass.**
- `src/core/saved_search_price_drops.py`: the watchlist is no longer read; the Listing-level cap is skipped for a search of one type capped on the other; docstrings say what a row is.
- `src/adapters/queue/tasks.py`: alert rows dated `max(run clock, floor)`; `remaining` counts what did not fit the limit; `collect_drop_candidates` without `owner`.
- `src/tests/unit/test_saved_search_price_drops.py`, `test_saved_search_alert_tasks.py`: the statement's new shape, the two task cases, both passes raising.
- `src/tests/integration/test_saved_search_price_drops.py`: a watched Property is announced; the crossed cap; a rise after an alert; a rise then a fall short of the price at activation; the PATCH row lock against a concurrent write; the migration round trip with its backfill.
- `frontend/src/index.css`, `SavedSearchRow.tsx`, `frontend/tests/e2e/saved-search-alerts.spec.js`: offset focus ring on the switch, no `title` on the invalid field, the two-writes-in-flight e2e, `1.500` and `1500,5`.
- `docs/features/v0.14-s1.10-...md`, `docs/api.md`, `docs/data-models-api.md`, `src/adapters/db/models.py` and the migration (docstrings only): the measurements, the watchlist decision, the table's rows.

**Review.** 41 findings: 8 medium, 24 low, 9 false.
- Patched entries, by root: 5 medium (watchlist exclusion removed; crossed-type cap; three untested pass-1 fixes now tested: migration backfill, PATCH row lock, per-field merge) and 9 low (table wording, platform-name comment, focus ring, triple announcement, parser inputs, `+N` count, alert row date, rise tests, both-passes-raising test). No high.
- Deferred: the list now has three entries: the watchlist path stamping before delivery (reworded: it no longer reaches this story's email), the watchlist email without its threshold (kept), the missing `zapimoveis` label in the SPA (new, pre-existing). Two entries were removed as settled by measurement: the statement's cost on the primary and Listings without listing-scoped price history.
- Rejected, with reasons in the triage log: the row lock held during the statement (measured); no full-gate record in pass 1; muted row that is on; retention and FK index; upper bound; ledger entries DW-55 / DW-63; `R$` alone; claim-to-send window (carried); the recorded product calls (two windows, Listing-level filters, off/on restart, sibling rows, backfill, additions); the test-surface remarks (SMTP not joined, hand-inserted history, mock sessions, mocked e2e store, tokens, test-first, bulk enable).

**Ruling on the watchlist exclusion.** Removed. It could leave a drop unannounced by both paths without any delivery failure (the stamp survives a rise), and on debounce or a failed watchlist send. No evidence of delivery exists to exclude on, and the watchlist path is out of scope. The failure direction is now one extra email for a Property that is both watched and covered by a search with drop alerts. This departs from one "Always" bullet and one matrix row of the frozen intent contract; see the Spec Change Log.

**Follow-up review: not recommended (false).** Patched this pass, by entry: high 0, medium 5, low 9. On a follow-up pass only a patched high asks for another; there was none.

**Verification.**
- Primary, read-only session (`default_transaction_read_only=on`): the measurements in the triage log.
- Gate, backend tier, on the working tree with every code patch of this pass: exit 0; 2693 unit, 331 integration, 80 contract passed; `alembic check` informational as before.
- The same tier against two mutants (the PATCH read without `FOR UPDATE`; the backfill predicate inverted): exactly the two new tests failed. The files were restored.
- The two saved-search e2e specs: 8 passed. `eslint` clean on the touched files.
- The gate's full tier on the final commit runs after this file is committed (the commit it validates contains this file); its result is in the session report.
- No email was sent and no mail server was contacted. `.env.local` was not read.

**Residual risks.**
- The watchlist removal and the crossed-type cap changed the rule in this pass and were read by no second reviewer; both are covered on Postgres.
- A watched Property can get two emails for one drop.
- The statement's cost was measured with 2.5 months of history, of which 2,756 changed Listings belong to decidable Properties; it grows with the number of Listings that changed since a search's floor and with how many of their Properties are decidable.
- Unchanged from pass 1: switching a search on is what lets real email leave on a configured host; the primary needs migration `a8b9c0d1e2f3` and a rebuild after the merge.
