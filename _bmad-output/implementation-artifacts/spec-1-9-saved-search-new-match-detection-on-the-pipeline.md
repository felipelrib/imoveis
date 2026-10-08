---
title: 'Story 1.9 — Saved-search new-match detection on the pipeline'
type: 'feature'
created: '2026-10-08'
status: awaiting-operator
baseline_revision: '619f7e2323d358a57296548e1f9d68f9c53b193f'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/docs/features/v0.14-s1.6-cohort-price-per-m2-percentiles.md'
  - '{project-root}/docs/features/v0.14-s1.7-percentile-badge-and-filter.md'
warnings: ['oversized']
deferred:
  - summary: >-
      No Property on the primary has received a deal verdict since 2026-08-13, so every new match
      stays held and no new-match email leaves.
    evidence: |-
      Read-only on the primary, 2026-10-08: 28,140 of 200,727 metrics_scoring rows carry
      meta.deal_verdict, newest meta.enriched_at 2026-08-13T16:47; of 23,229 active Properties
      first seen in the last 7 days (all with images) none is decidable;
      pipeline_metric_snapshots shows ai_queue 0 and enriched_properties flat at 26,947 while
      scraper_queue is about 10,400. All 199,840 percentile stamps come from the bulk run of
      2026-10-08 10:10, none from the single-property path. The code path that releases a match
      exists and is tested (run_enrichment -> _persist_ai_scores -> score_single_property stamps,
      _write_deal_verdict stores the verdict, one transaction, no bulk recalculation). What is
      missing is enrichment actually running for new Properties. Why it stopped is not visible
      from Postgres (Redis pause flags, worker logs and Ollama were outside the allowed probe).
      A typical search (rent, up to R$ 4.000, 2+ bedrooms, cheapest half) would have had 1,234
      candidates in 7 days. ai_enrich also gives up after 5 retries one minute apart, and nothing
      re-enqueues a Property whose enrichment was dropped except the operator endpoint
      POST /admin/enrichment/rerun (mode missing) and the backfill runner. Since review pass 2 a
      hold has no time limit: nothing expires, held_overdue reports the state, and the held
      Properties are alerted (20 per search per day, oldest first) once verdicts exist.
    location: >-
      src/adapters/queue/tasks.py:796
    severity: high
  - summary: >-
      The saved-search filter wire accepts min_price and max_bedrooms, which neither the SPA nor
      GET /properties applies.
    evidence: |-
      src/api/saved_searches.py SavedSearchFilters declares both; frontend/src/savedSearchFilters.ts
      CAMEL_TO_SNAKE has neither and PropertyListFilters has no such parameter. A search stored
      through the API with them lists, and now alerts, as if they were absent. The matcher ignores
      them on purpose so that it agrees with the grid. docs/api.md does not list the two keys.
    location: >-
      src/api/saved_searches.py:72
    severity: low
  - summary: >-
      The email notifier logs in to SMTP without STARTTLS or SSL, so a mail provider that
      requires TLS refuses every send.
    evidence: |-
      src/adapters/notify/email_notifier.py: send_batch, send_digest and the new
      send_new_matches all open smtplib.SMTP(host, port) and call server.login(user, password)
      with no starttls() and no SMTP_SSL; AlertsConfig has no key for either. The pattern
      predates Story 1.9, which reused it. With real credentials for a public provider (port 587
      or 465) the login is refused; send_new_matches then raises, the matches stay pending and
      an error is counted every hour (the two older methods swallow the error). Unit tests patch
      smtplib.SMTP, and this run was forbidden to contact a mail server, so it was read, not run.
      Fix: a config key (alerts.smtp_starttls / smtp_ssl) honoured by all three methods, with
      unit tests on the patched SMTP object.
    location: >-
      src/adapters/notify/email_notifier.py:134
    severity: medium
  - summary: >-
      A saved search does not store the Total Monthly Cost cap, so neither a reopened search nor
      its new-match alert applies it.
    evidence: |-
      frontend/src/savedSearchFilters.ts CAMEL_TO_SNAKE and SavedSearchFilters
      (src/api/saved_searches.py) have no max_total_monthly_cost / include_incomplete_totals,
      while the grid sends both to GET /properties (frontend/src/api.ts). A search saved with
      the cap set comes back without it, and the matcher (which reads the stored blob) alerts
      without it too: alert and reopened search agree with each other, not with the grid at the
      moment of saving. Predates Story 1.9 (the cap is Story 1.2). The matcher treats the key as
      unknown (never fires) if a blob carries it, pinned by a unit test, so adding the key to
      the wire must also add it to SAVED_SEARCH_WIRE_KEYS and the translation.
    location: >-
      frontend/src/savedSearchFilters.ts:11
    severity: low
operator_actions:
  - >-
    AGENT-RUNNABLE. Migrate the primary database from the primary checkout in Git Bash:
    bash scripts/agent/migrate-primary.sh . Verify read-only: SELECT version_num FROM
    alembic_version; returns f7a8b9c0d1e2, and SELECT count(*) FILTER (WHERE notify_new_matches)
    AS on_, count(*) AS total FROM saved_searches; returns on_ = 0. Record under "Operator
    results" in docs/features/v0.14-s1.9-saved-search-new-match-detection.md.
  - >-
    AGENT-RUNNABLE. Rebuild and restart the API, the workers and beat after the migration
    (./scripts/restart.sh --build), so the new tasks and beat entries run. Verify: the beat log
    lists match-saved-search-new-matches and send-saved-search-new-match-alerts; a worker log
    shows saved_search_new_match_run with searches 0 within 15 minutes (later if the scrapers
    queue is backed up: the beat tasks wait behind scrape tasks; record how late);
    GET /saved-searches returns notify_new_matches on every item;
    GET /properties?accepts_pets=true&page_size=1 returns 200 (it was a 500 before this story).
    Record in the same section.
  - >-
    AGENT-RUNNABLE. Measure whether anything can be released, read-only: SELECT count(*) AS
    new_active, count(*) FILTER (WHERE ms.percentile_evaluated_at IS NOT NULL AND
    NULLIF(btrim(ms.meta->'deal_verdict'->>'verdict'), '') IS NOT NULL) AS decidable FROM
    properties p LEFT JOIN metrics_scoring ms ON ms.property_id = p.id WHERE p.active AND
    p.first_seen >= now() - interval '7 days'; (2026-10-08: 23,229 and 0). Record in the same
    section.
  - >-
    HUMAN-ONLY (decision). Enrichment has produced no verdict on the primary since 2026-08-13;
    while that holds, every new match stays held and no new-match email leaves (nothing is
    lost: a hold has no time limit, and held_overdue in the matcher log shows the state).
    Decide how new Properties get enriched again (live ai_enrich on the host GPU, or a backfill
    pass that includes the verdict stage) and confirm with the query of the previous step that
    decidable is above 0. Do this before switching a search on, or expect a backlog: everything
    created after a search is switched on is alerted once it has a verdict, 20 per search per
    day, oldest first.
  - >-
    HUMAN-ONLY (credential). Set the real mail settings for the primary in .env.local
    (IMOVEIS_ALERTS__DIGEST_EMAIL, IMOVEIS_ALERTS__SMTP_HOST, IMOVEIS_ALERTS__SMTP_PORT,
    IMOVEIS_ALERTS__SMTP_USER, IMOVEIS_ALERTS__SMTP_PASS) and optionally
    IMOVEIS_ALERTS__NEW_MATCH__APP_BASE_URL for the link; the committed values are
    localhost:1025 and admin@example.com. The notifier logs in over plain SMTP, without
    STARTTLS or SSL (deferred finding): use a server or local relay that accepts that, or the
    send fails every hour and the matches stay pending. Verify after a restart: no
    saved_search_new_matches_email_failed in the worker log once a search is on.
  - >-
    HUMAN-ONLY (decision). Switch a saved search on (Story 1.10 toggle, or PATCH
    /saved-searches/<id> with {"notify_new_matches": true}); this is what lets real email leave.
    Verify read-only: SELECT status, count(*) FROM saved_search_new_matches GROUP BY status;
    and SELECT name, new_match_last_window_on FROM saved_searches WHERE notify_new_matches;
---

<intent-contract>

## Intent

**Problem:** A saved search is only a filter preset: nothing tells the user that a new home matching it appeared (FR-32). The notifier stack knows price drops and the weekly digest only.

**Approach:** Two Celery beat tasks on the `scrapers` queue. A matcher records, per notification-enabled saved search, each newly created Property that matches the search once it is decidable (verdict stored and percentile evaluated). A daily-window sender emails the recorded matches of each search in one message through the single notifier registry, email channel only. The saved-search API exposes the per-search flag and stored threshold so Story 1.10 is a UI story.

## Boundaries & Constraints

**Always:**
- Matching is read-only on Property / Listing / `metrics_scoring` (AD-3, AD-10). The only tables this story writes are `saved_searches` (API) and the new `saved_search_new_matches`.
- The match predicate is the list endpoint's own `WHERE` (one builder shared by `GET /properties` and the matcher); no second interpretation of a filter.
- "New" = the Property row was created (`properties.first_seen`) at or after the moment the search's notifications were enabled, and no more than `alerts.new_match.max_age_hours` ago. A Listing appearing, reappearing or reactivating on an existing Property is never a new match, so a platform outage and its recovery cannot produce one.
- Held, not dropped: an undecidable new Property is re-examined on every matcher run until it is decidable or older than `max_age_hours`; holding needs no queue message. Past that age it is reported (log + task result), never alerted.
- At most one row per search x Property (unique constraint); at most one email per search per local day (stored window date); a failed send leaves the rows pending for the next hourly tick.
- All outbound mail goes through `adapters.notify` registry notifiers of channel `email`; owner is the single principal (`auth.principal_id`); searches of another or NULL owner are ignored.
- `notify_new_matches` defaults to false for existing and new saved searches.
- Tunables live in `alerts.new_match` (`AppConfig`); both beat tasks are in `task_routes`.

**Never:**
- No hook inside `core/dedupe.py` or `scrape_listings` (shared persist path).
- No real SMTP connection in tests or by hand; no reading of `.env.local`.
- No Story 1.10 UI, no drop-alert rule or drop email (the threshold is stored and round-tripped only).
- No in-app Alertas panel or desktop push (Epic 5). No re-enqueue of `ai_enrich` from the matcher.
- No change to `sprint-status.yaml`; no merge, push or `ship.py`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| New decidable match | search enabled at T0; Property created after T0, active, matches, verdict + `percentile_evaluated_at` set | one `pending` row; next due window sends one email listing it; row `sent` | none |
| Suppressed percentile | as above, percentile NULL but stamp set | decidable; matches unless the search filters on the percentile | none |
| Not decidable | no `metrics_scoring` row, or no verdict, or stamp NULL | no row; counted in `held`; matched on a later run once decidable | none |
| Held too long | undecidable and older than `max_age_hours` | never alerted; counted in `expiring_24h` before it ages out | warning log |
| Existed before enabling | Property created before `notify_enabled_at` | never fires | none |
| Disabled search | `notify_new_matches=false` | matcher skips it; its pending rows become `withdrawn` at the window | none |
| Outage recovery | old Property deactivated then reactivated, or gains a Listing of the searched type | no row | none |
| Twice the same pair | matcher runs again / a second worker | still one row, one email | `ON CONFLICT DO NOTHING` |
| Second run in the same local day | sender invoked again after sending | no second email for that search | none |
| Send fails | email notifier raises | rows stay `pending`, window date not stamped, error counted | logged, retried next tick |
| No email channel configured | `alerts.enabled=false` or no `email` channel | nothing sent, rows stay `pending`, reason reported | none |
| Semantic search | saved filters carry `q` | not matchable: skipped, API says `new_match_alerts_supported=false` | none |
| Property gone before the window | pending row, Property inactive at send time | row `withdrawn`, not emailed | none |
| Weekly digest | Property with a `sent` row (or pending under an enabled search) | excluded from `select_top_deals` for that owner | none |

</intent-contract>

## Code Map

- `src/api/properties.py:146-205,335-475` -- the only definition of list filter semantics (`_build_list_filters`, cap constants, `_append_*`). Moves to core; the module keeps its private names as aliases (unit tests import them).
- `src/core/property_list_filters.py` -- NEW. `PropertyMatchFilters`, `build_property_where()`, the moved constants.
- `src/core/saved_search_alerts.py` -- NEW (TDD). Saved-wire to `PropertyMatchFilters`, decidable SQL fragment, newness floor, window arithmetic, `record_new_matches()`, `collect_due_batches()`, `mark_sent()`, hold report, email text.
- `frontend/src/hooks/usePropertiesFiltersState.ts:66-88`, `frontend/src/api.ts:636-649` -- how the SPA turns a saved search into list parameters; the translation mirrors it (read-only reference).
- `src/api/saved_searches.py` -- item/create/update models and SQL; gains `notify_new_matches`, `min_price_drop`, read-only `notify_enabled_at`, `new_match_alerts_supported`, `last_new_match_alert_on`.
- `src/adapters/db/models.py:332` -- `SavedSearch` columns; NEW `SavedSearchNewMatch`.
- `alembic/versions/` -- head is `e6f7a8b9c0d1`; NEW `f7a8b9c0d1e2`.
- `src/adapters/notify/{__init__,base,email_notifier,log_notifier}.py` -- the registry (`get_notifiers`); gains channel lookup and `send_new_matches`.
- `src/adapters/queue/tasks.py:1222` (`send_top_deals_digest`), `src/core/top_deals_digest.py:58` -- weekly digest selection; gains the already-alerted exclusion.
- `src/adapters/queue/celery_app.py:17,223` -- beat schedule and `task_routes`.
- `src/infra/config.py:489-519`, `configs/app_config.yaml:438` -- `AlertsConfig`; gains `new_match`.
- `src/adapters/queue/tasks.py:664-708,774-787` -- release path evidence: `run_enrichment` -> `_persist_ai_scores` -> `score_single_property` stamps `percentile_evaluated_at` and `_write_deal_verdict` stores the verdict in one transaction; no bulk recalculation involved.
- `src/adapters/metrics/scoring.py:274-301,950` -- the only writer of the stamp (read-only here).

## Tasks & Acceptance

**Execution:**
- [x] `src/tests/unit/test_property_list_where_lock.py` -- NEW, own commit first: exact `WHERE` text and params of `_build_list_filters` for a filter set covering every membership filter -- characterization lock before moving brownfield SQL.
- [x] `src/core/property_list_filters.py`, `src/api/properties.py` -- move the `WHERE` builder to core, API delegates, aliases kept -- one definition for API and matcher.
- [x] `src/tests/unit/test_saved_search_alerts.py` then `src/core/saved_search_alerts.py` -- test-first: translation, unsupported `q`, floor, window due / date, email text, SQL assembly reuses the shared `WHERE`.
- [x] `alembic/versions/f7a8b9c0d1e2_saved_search_new_match_alerts.py`, `src/adapters/db/models.py` -- `saved_searches.notify_new_matches` (NOT NULL default false), `notify_enabled_at`, `min_price_drop` (CHECK >= 0), `new_match_last_window_on`; table `saved_search_new_matches` (unique search x property, status CHECK, FK search `SET NULL`, FK property `CASCADE`).
- [x] `src/infra/config.py`, `configs/app_config.yaml` -- `alerts.new_match` section with validation.
- [x] `src/adapters/notify/*` -- `SavedSearchNewMatches` payload, `Notifier.send_new_matches` (default: unsupported), email implementation that raises on failure, `get_notifiers_for_channel`.
- [x] `src/adapters/queue/tasks.py`, `src/adapters/queue/celery_app.py` -- `tasks.match_saved_search_new_matches`, `tasks.send_saved_search_new_match_alerts`, routes, beat entries; digest task passes the owner.
- [x] `src/core/top_deals_digest.py` -- exclusion of already-alerted Properties.
- [x] `src/api/saved_searches.py` -- flag / threshold round trip; enabling stamps `notify_enabled_at`.
- [x] `src/tests/unit/test_saved_search_alert_tasks.py`, `test_new_match_notifier.py`, `test_celery_app.py`, `test_config.py`, `src/tests/integration/test_saved_search_new_matches.py` -- I/O matrix on Postgres, list-endpoint parity, task happy + error path, migration shape.
- [x] `docs/features/v0.14-s1.9-saved-search-new-match-detection.md`, `docs/api.md` -- feature doc (all sections), API fields.

**Acceptance Criteria:**
- Given an enabled search and a matching Property created after enabling, when it becomes decidable and the window is due, then exactly one email is handed to the registry's email notifier and to no other channel, carrying the principal id.
- Given the same data, when `GET /properties` is called with the parameters the SPA derives from that saved search, then the matcher's matched set equals the listed set restricted to new decidable Properties.
- Given any saved search created before this story or without the flag, when the tasks run, then no row is written and no notifier is called.
- Given the migration, when the gate runs the alembic check, then models and schema agree.

## Spec Change Log

- 2026-10-08, review pass 1 (patches, no re-derivation). Two Design Notes lines are superseded by the code: (1) `max_price` without a stored `price_type` passes no `price_type`, so the list builder applies the endpoint default (listing type, else rent) instead of forcing `rent`; a blob written through the API then matches what `GET /properties` returns for it. (2) The email link is `<app_base_url>/properties/<public_id>`, the SPA route; `/?property=` is not handled by the SPA. Added rule: a stored blob that is not an object or carries a key outside the saved-search wire is not matchable. KEEP: pull design with no persist hook, the shared `WHERE`, the stored window date, raising email notifier.
- 2026-10-08, follow-up review (pass 2; patches, no re-derivation). Three statements inside `<intent-contract>` are superseded by the story's acceptance criterion ("the alert is held until the verdict exists and the percentile has been evaluated ..., never dropped") on the ruling the orchestrator asked this pass to make; the block itself is left as written. (1) "New ... and no more than `alerts.new_match.max_age_hours` ago": the floor is the enable moment alone. (2) "Held, not dropped: ... or older than `max_age_hours` ... Past that age it is reported, never alerted": a hold has no end other than decidability; a hold longer than `alerts.new_match.hold_warning_hours` (the renamed key, default 168) is reported as `held_overdue` and stays held. (3) Matrix row "Held too long": such a Property is counted in `held_overdue`, logged as a warning and alerted when it becomes decidable. Also superseded outside the contract: the Design Notes lines that mention `max_age_hours`, `expiring_24h`, `newness_floor(enabled_at, now, max_age_hours)`, "every pending row is still marked sent" (only the rows an email shows are marked; the rest stay pending for the next day) and the `max_items` argument of `render_new_match_email` (now `remaining`). Added: the sender locks the search row (`FOR NO KEY UPDATE SKIP LOCKED`) and re-reads its state under the lock. Known-bad states avoided: a match that silently expires while enrichment is down (every match on the primary today); matches marked sent without having been shown; two sender runs emailing the same rows. KEEP: everything pass 1 kept, plus the endpoint default for a missing `price_type` and the unknown-key rule (both confirmed in this pass).
- 2026-10-08, follow-up review (pass 3; narrow, the three commits of pass 2 only; patches, no re-derivation). Superseded: the pass 2 sentence "the sender locks the search row ... and holds it until `mark_sent` commits", and the Design Notes line of the sender task that reads "render, `send_new_matches` on each email notifier, `mark_sent` + commit". The sender now claims the day (stamps `new_match_last_window_on` under the row lock and commits), sends with no lock and no transaction open, then marks the rows; a failed send gives the day back (`claim_window` / `release_window` in `core/saved_search_alerts.py`). Also: `collect_pending` orders by `matched_at`, then `first_seen`, then id. Known-bad state avoided: a `PATCH` or `DELETE` of a saved search waiting for the mail server. KEEP: one sender per search, the stored window date, "only what the email shows is marked sent", the hold without a time limit, the pets predicate as fixed.

## Review Triage Log

### 2026-10-08 — Review pass
- verdicts: 41 findings — high 4, medium 7, low 24, false 6, maybe-false 0
- findings:
  - `[low]` `[patch]` Blind: a search name with a line break makes the Subject header invalid, so that search never emails — the subject now collapses whitespace (`render_new_match_email`); unit test added.
  - `[low]` `[reject]` Blind: pending rows are not re-checked against the filters at send time — real, at most one day of staleness, the email shows the current price; the SPA cannot edit a saved search today; a re-check adds a second evaluation path. Documented.
  - `[low]` `[reject]` Blind: pending rows have no age limit while no email can be sent, and the digest leaves them out meanwhile — this is "held, not dropped" working as decided; a bound would drop matches. Documented.
  - `[high]` `[defer]` Blind: an `accepts_pets` search is reported as supported although its predicate fails — pre-existing list-endpoint bug, confirmed on the primary; deferred with evidence.
  - `[low]` `[reject]` Blind: no CHECK ties the flag to its stamp — the API always writes both; only manual SQL reaches the state, and the result is a search that never fires.
  - `[low]` `[reject]` Blind: the `expiring_24h` warning repeats every run and counts everything when `max_age_hours` < 24 — a state log on a worker; throttling it needs stored state. Documented.
  - `[low]` `[reject]` Blind: the held line in the email is not per search — by design: membership is unknown before a Property is decidable; the sentence says "the ones that match". Documented.
  - `[false]` `[reject]` Blind: no index supports the time-window scans — measured read-only on the primary (206k Properties): hold report 58-133 ms, matcher SELECT 153 ms. Recorded in the feature doc.
  - `[low]` `[reject]` Blind: the table has no retention and pending rows of a deleted search stay pending — one small row per match; nothing reads them wrongly. Documented.
  - `[false]` `[reject]` Blind: switching off and on discards pending matches earlier than "at the window" — the outcome the matrix states (a disabled search never fires, rows withdrawn) is what happens; the hourly tick is the sender's window check.
  - `[medium]` `[patch]` Blind: parity table lacks a sale search with `max_price` and no `price_type` (and lists of places) — translation changed to leave the endpoint default; two parity cases added.
  - `[low]` `[patch]` Blind: bookkeeping (unit of `min_price_drop` undocumented; spec status) — unit documented as reais in `docs/api.md` and the feature doc; the status was in flight.
  - `[low]` `[reject]` Edge: a row withdrawn while its Property was inactive never comes back on reactivation — needs an upsert branch for a rare sequence inside one day. Documented.
  - `[low]` `[reject]` Edge: email delivered, then `mark_sent` fails, so it is sent again — chosen direction (at least once on a database failure rather than a lost alert); a claim-before-send protocol is more than a correction. Documented.
  - `[low]` `[reject]` Edge: two overlapping sender runs send duplicates — beat queues one run per hour; with the SMTP timeout below a run cannot outlast the hour.
  - `[low]` `[reject]` Edge: filters edited while rows are pending — same root as the send-time re-check above.
  - `[low]` `[patch]` Edge: a stored blob that is not an object is read as an empty search — now not matchable (`saved_search_is_matchable`); unit test.
  - `[medium]` `[patch]` Edge: sale search with `max_price` and no `price_type` caps rent Listings — same root as the parity finding; fixed there.
  - `[low]` `[patch]` Edge: CR/LF in the name — same root as the subject finding; fixed there.
  - `[medium]` `[patch]` Edge: SMTP without a timeout can block the task and its session — `timeout=30` on the new-match send; unit test asserts it.
  - `[low]` `[reject]` Edge: the digest excludes pending rows that were never emailed — same root as the age-limit finding.
  - `[low]` `[reject]` Edge: `PATCH true` does not repair a flag without a stamp — same root as the CHECK finding.
  - `[false]` `[reject]` Edge: a non-UTC database session shifts the floor — the primary runs `TimeZone=UTC` (measured) and so does the test stack; Story 1.6 relies on the same clock. Noted in the feature doc.
  - `[low]` `[patch]` Edge: the sender raises when loading the searches fails although its docstring said it never raises — docstring corrected; a database outage failing the task is the wanted behaviour.
  - `[low]` `[reject]` Edge: `max_age_hours` below 24 makes everything "expiring" — a configuration nobody has; the count is then literally true.
  - `[medium]` `[patch]` Edge (claim): a legacy or non-normalised blob matches more broadly than the grid — a blob with a key outside the saved-search wire is now not matchable; key set pinned against the API model and the SPA key table.
  - `[high]` `[defer]` Verification gap: the pets predicate is never executed on Postgres by any test — same root as the deferred pets bug. The "failing search does not stop the others" claim is now tested on a real session with another failing statement.
  - `[medium]` `[patch]` Verification gap: the translation does not adopt the SPA's legacy-key reading — same root as the unknown-key finding; fixed there with tests.
  - `[low]` `[patch]` Verification gap: nothing proves the sender passes `listing_type`, `app_base_url` and `locale` — task-level unit test with non-default values added.
  - `[low]` `[patch]` Verification gap: the `property_type` title fallback of `collect_pending` is unobserved — integration test with an untitled Property added.
  - `[high]` `[defer]` Verification gap (other): the pets predicate itself — same deferred entry.
  - `[false]` `[reject]` Verification gap (other): value-level divergence from the SPA (`Boolean(...)`, non-canonical listing type) — every write goes through `SavedSearchFilters.to_wire`, which stores booleans and canonical types; the primary has no saved search at all.
  - `[medium]` `[patch]` Intent: the premise that `first_seen` is written only at creation is pinned by no test of the real persist path — integration test added that runs `match_or_create_property` twice and matches only the creation.
  - `[low]` `[patch]` Intent: the release-path test hand-writes the verdict — it now calls the production `_write_deal_verdict` with a stub model client.
  - `[low]` `[reject]` Intent: "never dropped" versus a 168-hour expiry reported in logs — the request left "released or reported" to the implementer; decision recorded in the feature doc and the run report.
  - `[low]` `[patch]` Intent: the Python translation is a second reading of frontend logic with no tie — a unit test now reads the SPA key table and fails when it stores a key the matcher does not know.
  - `[high]` `[defer]` Intent: `accepts_pets` searches never fire — same deferred entry.
  - `[medium]` `[patch]` Intent: the email link `/?property=` is not a route the SPA handles — changed to `/properties/<public_id>` (`frontend/src/routes/propertyPaths.ts`).
  - `[false]` `[reject]` Intent: process claims a squashed diff cannot show — `git log` shows the lock test in its own first commit; the gate ran the alembic step and the models-versus-schema test; `tzdata` is pinned in `requirements.txt`.
  - `[false]` `[reject]` Intent: tasks are exercised in process, not through a broker — no bad outcome claimed; routes and beat entries are asserted on the real `make_celery()`.
  - `[low]` `[patch]` Intent: the operator steps tell the reader to switch a search on, which lets real mail leave — steps split into agent-runnable and human-only in the feature doc and in `operator_actions`.

### 2026-10-08 — Review pass 2 (follow-up)
- verdicts: 38 findings — high 4, medium 6, low 25, false 3, maybe-false 0
- findings:
  - `[medium]` `[patch]` Blind: two sender runs that overlap email the same pending rows (the scrapers worker has two processes; queued hourly runs can start together behind a scrape backlog) — the sender now takes the search's row lock (`FOR NO KEY UPDATE SKIP LOCKED`) before reading pending rows, re-reads the search's state under it and holds it until `mark_sent` commits; unit tests (locked search skipped, state under the lock wins) and an integration test with a second transaction holding the lock. No `expires` on the beat entries: under a backlog longer than an hour it would discard every sender run.
  - `[medium]` `[defer]` Blind: SMTP login without STARTTLS / SSL — real; the same code is in `send_batch` and `send_digest`, which predate the story; the fix needs a config key. Deferred with evidence; the operator step for the mail settings now says so.
  - `[medium]` `[patch]` Blind: matches past `max_items_per_email` are marked sent although the email never showed them, and the digest then leaves them out — the sender marks only the rows the email carries (oldest first); the rest stay pending and leave in the next day's email; the `+N` line says so. Unit and integration tests rewritten for it.
  - `[low]` `[reject]` Blind: the held line in the email is corpus-wide and promises delivery — carried for "not per search" (membership is unknown before a Property is decidable); the promise is now true, since a hold no longer expires. The size of the number is the honest state of the pipeline.
  - `[low]` `[reject]` Blind: the hold report counts Properties that can never become decidable (photo gate), so the warning never stops — real; excluding them needs the photo-gate rule inside this query (a second copy of enrichment's rule). Documented under Notes.
  - `[low]` `[reject]` Blind: a search that fails every run still yields `status: ok` — the result carries `errors` and each failure is logged with the search id; the one known always-failing case (`accepts_pets`) is fixed in this pass.
  - `[low]` `[reject]` Blind: unmatchable searches leave no per-search trace in the task — the API reports it per search (`new_match_alerts_supported`, now also for a blob that is not an object); a log line per unsupported search every 15 minutes adds noise, not information. The "sender does not re-check" half is carried (send-time re-check, pass 1).
  - `[low]` `[reject]` Blind: `notify_enabled_at` is serialised without a UTC offset — documented as naive UTC in `docs/api.md`; nothing reads it yet; Story 1.10 owns the first consumer.
  - `[low]` `[defer]` Blind: the Total Monthly Cost cap cannot be part of an alerting search — the saved-search wire never stored it (SPA and API, since Story 1.2), so the reopened search has no cap either; alert and reopened search agree. Deferred with evidence; documented in the feature doc.
  - `[low]` `[reject]` Blind: by default the email carries no link — `app_base_url` is a host setting with no safe default (the SPA's address is not known to the worker); the operator step names it.
  - `[low]` `[reject]` Blind: the spec still states superseded rules — its fix is an edit of this spec; the change log records what is superseded. The `docs/api.md` omission of `min_price` / `max_bedrooms` is part of the existing deferred entry.
  - `[false]` `[reject]` Blind: integration assertions depend on a corpus-wide count and can flake — the gate runs the integration suite serially (`scripts/agent/validate.py`), and every other test of the module cleans its platform up.
  - `[low]` `[patch]` Blind: `min_price_drop` accepts non-finite values — `allow_inf_nan=False` on both request models; a stored infinity would have made every later `GET /saved-searches` fail to serialise. Unit test added.
  - `[low]` `[reject]` Blind: leftovers without a caller (`LogNotifier.send_new_matches`, two `_utcnow_naive`, private aliases in `api/properties.py`) — no named harm; the aliases keep the pre-existing unit tests unedited, which is what the lock discipline asked for.
  - `[low]` `[reject]` Blind: the email locale lookup is exact-match — `ui.locale` is validated to the two supported values by `AppConfig`.
  - `[medium]` `[patch]` Edge: overlapping sender runs — same root as the first row; fixed there.
  - `[low]` `[reject]` Edge: a rent search prints a sale price with `/mês` when the rent Listing vanished before the window — real, needs a Property to lose its rent Listing and keep a sale one within a day; the fix adds a branch to the renderer. Same family as the send-time re-check.
  - `[low]` `[reject]` Edge: a pending row is not withdrawn when the Property loses its Listing of the searched type — carried (pending rows are not re-checked against the filters at send time, pass 1).
  - `[low]` `[patch]` Edge: a stored blob that is not an object is reported as supported while the matcher never fires for it — `_item_from_row` now tests the stored value, not the `{}` stand-in; unit tests for non-object and legacy camelCase blobs.
  - `[low]` `[reject]` Edge: the email locale ignores the Redis `ui:locale` override — the worker has no request context; the YAML locale is the documented source for the email.
  - `[low]` `[patch]` Edge (claim): for a blob with `max_price` and no `price_type` the matcher follows the endpoint default while the SPA would reopen it with rent — behaviour kept (ruling: the alert equals `GET /properties` for the stored parameters; the SPA cannot write such a blob, it always stores `price_type`); the feature doc's "Matches" definition and the `price_type` row now state the difference.
  - `[medium]` `[patch]` Edge (claim): "exactly one email" does not hold under overlapping runs — same root as the first row; fixed there. An `email` channel listed twice in the config sends twice: a configuration error, not guarded.
  - `[low]` `[patch]` Verification gap: nothing observed the floor the sender passes to `hold_report` — the sender unit test now asserts it, with an enable moment older than `hold_warning_hours`.
  - `[low]` `[patch]` Verification gap (other): non-object blob reported as supported — same root as the edge row; fixed there.
  - `[low]` `[patch]` Verification gap (other): grid and alert disagree for a blob without `price_type` — same root as the edge claim row; documented there.
  - `[high]` `[patch]` Verification gap (other): `accepts_pets` never runs on Postgres — deferred in pass 1; fixed in this pass on the orchestrator's instruction: `(p.props_json->'amenities')::jsonb ? ...` wrapped in `COALESCE(..., false)`; regression test on Postgres for the list (true and false) and the matcher, a parity row, the lock line updated in the same commit; verified read-only on the primary (89,327 true + 110,867 false = 200,194 active).
  - `[high]` `[patch]` Intent: the story says "held ..., never dropped"; the code stopped looking after 168 hours — no planning text licenses an expiry (UX-DR11 only forbids alerting early). The floor is now the enable moment alone; `max_age_hours` became `hold_warning_hours` (reporting only, `held_overdue`). Integration test: a Property held for 900 hours is alerted once decidable. The contract sentences are recorded as superseded in the change log.
  - `[medium]` `[patch]` Intent: the cutoff was on Property age, so a decidable Property that no run saw in time (worker down, master switch off) was lost too — same root; integration test `test_decidable_property_no_run_saw_in_time_is_still_matched`.
  - `[low]` `[patch]` Intent: "reported" was an aggregate count before expiry, and the feature doc claimed an email line for expired matches — same root; nothing expires now and the doc is rewritten.
  - `[low]` `[reject]` Intent: membership is evaluated at decision time, not at creation — the contract's stated choice (filters such as `min_score` and the percentile cap do not exist at creation); the email then agrees with what the click-through shows.
  - `[low]` `[reject]` Intent: "new" is relative to the moment the search was switched on — the contract's reading of "only genuinely new Properties fire"; without it, switching a search on would email the existing corpus.
  - `[low]` `[reject]` Intent: the digest also excludes pending rows that were never emailed — carried (pass 1: held, not dropped; they are about to be emailed).
  - `[low]` `[reject]` Intent: searches with a NULL owner are ignored — the API always writes the principal; AD-11 names one principal as the owner of alerts.
  - `[false]` `[reject]` Intent: `mark_sent` writes `saved_searches.new_match_last_window_on` although "the only tables this story writes" names the API for that table — the same contract requires a stored window date; the table is in the sentence.
  - `[false]` `[reject]` Intent: rows are withdrawn on every hourly tick, earlier than "at the window" — carried (pass 1): the outcome the matrix states is what happens.
  - `[high]` `[patch]` Intent: an enabled `accepts_pets` search is reported as supported and never fires — same root as the verification-gap row; fixed there.
  - `[low]` `[reject]` Intent: the alert click — no link by default, and a degraded verdict counts as decidable with no panel test — the link is the `app_base_url` row above; the panel is frontend, which this story does not touch.
  - `[high]` `[defer]` Intent: the outcome "new deals reach me" is not produced on the primary, where no new Property is decidable — carried (deferred in the dev pass: enrichment on the primary); the entry's text is updated for the new hold rule.

### 2026-10-08 — Review pass 3 (follow-up, narrow)
- scope: commits `2ba24cd5`, `b4f9d6e9`, `b446d69c` only; one reviewer, five questions set by the orchestrator
- verdicts: 9 findings — high 0, medium 1, low 5, false 3, maybe-false 0
- findings:
  - `[medium]` `[patch]` Row lock held across the SMTP conversation: `PATCH` and `DELETE /saved-searches/<id>` waited for the mail server (both statements take a lock that conflicts with `FOR NO KEY UPDATE`) — confirmed on Postgres before the fix (`lock timeout` on an `UPDATE` of the search from a second connection during the send). The sender now claims the day in a short transaction, sends with nothing held and marks afterwards; a failed send gives the day back. Errs towards late: a worker killed between claim and send delays that day's email to the next day; an email delivered and not marked is sent again the next day, not every hour. Integration tests (edit during the send, delete during the send, second run during the send, claim given back) and five unit tests.
  - `[false]` `[reject]` The matcher's inserts block behind the sender's lock — they do not: the foreign-key check takes `FOR KEY SHARE`, which `FOR NO KEY UPDATE` does not conflict with. The pass 2 test asserted it without inserting anything; it now records a new Property while the lock is held.
  - `[low]` `[reject]` A search deleted while its email is being sent leaves its rows `pending` with no search, so the weekly digest may list such a home again — needs a delete inside the seconds of a send; same end state as the documented "pending row of a deleted search". Documented.
  - `[low]` `[patch]` `accepts_pets=false` semantics were stated nowhere — judgement call, kept: the complement of `true` ("not known to accept pets"). QuintoAndar and Zap store only "accepts" or nothing, so an explicit-no filter would list OLX homes only; nothing in the application sends `false`. Rule written into `docs/api.md` and the feature doc.
  - `[false]` `[reject]` The pets regression test might pass against the unfixed predicate — run against it: fails with `operator does not exist: json ? unknown` (and the parity test with it); with the cast but without `COALESCE` it fails on the `false` list (the Property without an `amenities` key is lost). Restored; passes.
  - `[false]` `[reject]` With no age limit a matcher run gets expensive as holds pile up — measured read-only on the primary with the whole table as candidates (200,195 active, 172,882 held): 134 to 1,330 ms per search, hold report about 220 ms. A held Property is one scanned row and is not stored. No bound added. The `INSERT` half (conflict probes for rows already recorded) is not measurable on the primary, which lacks the table.
  - `[low]` `[patch]` "Oldest first" was arbitrary inside a backlog: rows recorded by one matcher run share `matched_at` and the order fell back to the Property id — `collect_pending` now orders by `matched_at`, `first_seen`, id; integration test.
  - `[low]` `[patch]` The backlog release (20 per search per day, oldest first, `+N` line) was documented in two half-sentences — confirmed in code and test (`test_over_the_email_limit_the_rest_stays_pending_for_the_next_day`); the feature doc now states it under Notes with the key to change. Product behaviour unchanged.
  - `[low]` `[reject]` Watchlist task, beyond the removed `title=`: it reads the cheapest Listing whether active or not, and a Property whose Listings carry no price would fail the comparison — predates the story and is outside the reviewed line; the alert itself carries every field the three notifiers read. Noted in the feature doc.

## Design Notes

- **Pull, not push.** Newness is a stored fact (`properties.first_seen`, written only by `_create_property`), so the matcher reads it instead of receiving a message from the persist path. Nothing can be lost between persist and enrichment, a held match is simply a row not yet selectable, and stories 2.3 / 5.4 / 3.4 see no edit on the shared path.
- **Match at decision time.** Filters such as `min_score` and the percentile cap read enrichment output, so a match is evaluated when the Property is decidable, with the same SQL the click-through from the email would run.
- **Window as stored date.** The sender runs hourly; a search is due when the local hour has reached `window_hour` and `new_match_last_window_on` is before the local date. A worker that was down at the window hour sends at the next tick; a second run the same day does nothing.

### Working rules for the implementer (binding)

- Work only in the git worktree that contains this spec (`C:\Workfolder\imoveis\.run\wt\1-9`, branch `feat/v0.14-s1.9-saved-search-new-match-detection`). Every shell call starts elsewhere: `cd` there first. Never touch `C:\Workfolder\imoveis` itself (except using its interpreter `C:\Workfolder\imoveis\.venv\Scripts\python.exe`), `.bmad-loop/`, `sprint-status.yaml`, `.env.local`, the frontend, or the primary docker project `imoveis`.
- Read `AGENTS.md` first. Never f-string SQL (a unit lint enforces it: concatenate static fragments, bind values). `get_logger` kwargs must not be `name`, `msg`, `args`, `level`.
- Never open a connection to a mail server. Tests patch `smtplib.SMTP` or use a fake notifier.
- Single unit test files may be run with `C:\Workfolder\imoveis\.venv\Scripts\python.exe -m pytest <file> -p no:cacheprovider` from the worktree. Integration tests need Postgres and only run inside the gate: `C:\Workfolder\imoveis\.venv\Scripts\python.exe scripts/agent/validate.py` (auto tier; long timeout, 20+ min allowed; re-run once if an unrelated test fails under load). The gate must exit 0 at the end.
- Commits (conventional, on the branch, tree clean at the end, no merge / push / ship): 1) `test(v0.14-s1.9): lock the list WHERE before moving it` with only the lock test, passing against the unmoved code; 2) the refactor; 3+) the feature; docs. Do not edit the lock test after commit 1. Do not edit the `<intent-contract>` or the frontmatter of this spec; tick the task boxes when done. Commit this spec file with the work.
- A shell script or heredoc whose body contains a single quote fails to parse on this host: write such files with the file-writing tool.

### Shared WHERE (`core/property_list_filters.py`)

- `PropertyMatchFilters`: frozen dataclass with exactly the membership fields of `PropertyListFilters` (`platform, min_score, max_price, price_type, min_bedrooms, min_parking, neighborhood_name, city_name, listing_type, property_type, is_furnished, accepts_pets, max_total_monthly_cost, include_incomplete_totals, max_price_per_m2_percentile, bbox`), all optional / default as the API model.
- `build_property_where(filters, *, require_embedding=False) -> tuple[list[str], dict]` returns the predicate list starting with `p.active = true` (then `p.embedding IS NOT NULL` when asked) in the order used today, and the bound params without `limit` / `offset` / `q_vec`. It accepts any object with those attributes, so the API passes its pydantic model. `api.properties._build_list_filters` keeps signature and output (the lock test and the existing unit tests must pass unedited); order / sort stays in the API. Aliases under the old private names stay importable from `api.properties`.
- A unit test fails when `PropertyListFilters` gains a field that is neither pagination / sort / `q` nor a field of `PropertyMatchFilters`.

### Core (`core/saved_search_alerts.py`): no adapter imports, no lazy imports, SQLAlchemy `Session` allowed as in `core/top_deals_digest.py`

- `match_filters_from_saved_search(wire: Mapping) -> PropertyMatchFilters | None`. `None` = not matchable (non-blank `q`). Mirrors the SPA: `max_price` -> `max_price` with `price_type = wire price_type or "rent"` (only when `max_price` is set); `neighborhood` -> `neighborhood_name`; `city` -> `city_name`; `listing_type` passed through (`both` / missing mean no type); `is_furnished` / `accepts_pets` only when true; `max_price_per_m2_percentile` only when 0 < x <= 1; `min_bedrooms`, `min_parking`, `min_score`, `platform`, `property_type` as stored. `sort_*`, `min_price`, `max_bedrooms` are ignored because the list endpoint ignores them too.
- `DECIDABLE_SQL`: `ms.percentile_evaluated_at IS NOT NULL AND NULLIF(btrim(ms.meta->'deal_verdict'->>'verdict'), '') IS NOT NULL` (`meta` is `json`). A degraded template verdict counts: the panel shows it.
- `newness_floor(enabled_at, now, max_age_hours)` = the later of `enabled_at` and `now - max_age`. All timestamps naive UTC, like `first_seen`.
- `record_new_matches(session, *, search_id, owner, filters, enabled_at, now, max_age_hours) -> int`: one `INSERT ... SELECT p.id FROM properties p LEFT JOIN metrics_scoring ms ... LEFT JOIN neighborhoods n ... WHERE <shared where> AND p.first_seen >= :floor AND <decidable> ON CONFLICT (saved_search_id, property_id) DO NOTHING`, returning the inserted count. Same FROM / JOIN aliases as the list query.
- `hold_report(session, *, floor, now, max_age_hours) -> {held, oldest_held_hours, expiring_24h}` over active Properties with `first_seen >= floor` that are not decidable (`expiring_24h`: those within 24 h of aging out).
- `local_window_date(now_utc, tz_name)`, `window_is_due(now_utc, *, tz_name, window_hour, last_window_on) -> bool`.
- `collect_pending(session, search_id)` -> projected rows (AD-12 `map_property_list_item` over `LIST_SELECT_COLUMNS`) of pending rows whose Property is active; `withdraw_stale(session, ...)` sets `withdrawn` on pending rows whose Property is inactive, whose search is disabled, or that were matched before the current `notify_enabled_at`; `mark_sent(session, search_id, property_ids, now, window_date)` sets `sent` + `sent_at` and stamps `saved_searches.new_match_last_window_on`.
- `render_new_match_email(...) -> (subject, body)` pure text, `pt-BR` and `en` (locale argument, default `pt-BR`). Body: search name, one block per Property (title or type, neighbourhood, headline price with `/mês` for rent, area, bedrooms, verdict text, `entre os N% mais baratos do bairro` only when the percentile of the relevant type is not NULL, link `<app_base_url>/?property=<public_id>` only when `app_base_url` is set), a `+N` line when over `max_items_per_email` (every pending row is still marked sent), a held-count line when `held > 0`, and one line saying the email exists because new-match alerts are on for this search and are switched off in Buscas salvas. No threshold wording (that is the drop email of Story 1.10).

### Schema (`f7a8b9c0d1e2`, down_revision `e6f7a8b9c0d1`; models mirror it exactly so the alembic check is clean)

- `saved_searches`: `notify_new_matches BOOLEAN NOT NULL DEFAULT false`, `notify_enabled_at TIMESTAMP NULL`, `min_price_drop DOUBLE PRECISION NULL` + CHECK `ck_saved_searches_min_price_drop` (`IS NULL OR >= 0`), `new_match_last_window_on DATE NULL`.
- `saved_search_new_matches`: `id UUID PK default gen_random_uuid()`, `saved_search_id UUID NULL FK saved_searches ON DELETE SET NULL`, `property_id UUID NOT NULL FK properties ON DELETE CASCADE` (indexed), `owner VARCHAR NULL`, `status VARCHAR NOT NULL DEFAULT 'pending'` + CHECK in (`pending`, `sent`, `withdrawn`), `matched_at TIMESTAMP NOT NULL DEFAULT now()`, `sent_at TIMESTAMP NULL`, UNIQUE (`saved_search_id`, `property_id`) named `uq_saved_search_new_match`. `SET NULL` keeps "already alerted" for the digest after a search is deleted.

### Config (`alerts.new_match`, class `NewMatchAlertsConfig`)

`enabled: true` (master switch of both beat tasks; no email leaves while every search flag is off), `match_interval_minutes: 15` (> 0), `window_hour: 7` (0-23), `window_timezone: America/Sao_Paulo` (validated with `zoneinfo`), `max_age_hours: 168` (>= 1), `max_items_per_email: 20` (>= 1), `app_base_url: ""`. Recipient and SMTP stay the existing `alerts.digest_email` / `alerts.smtp_*`.

### Notifier registry

- `base.py`: `SavedSearchNewMatches(principal_id, search_id, search_name, subject, body, property_ids, generated_at)`; `Notifier.send_new_matches(batch)` non-abstract, raises `NotImplementedError` (existing fake notifiers in tests keep working).
- `__init__.py`: the registry remembers the channel type of each notifier; `get_notifiers_for_channel("email")` returns the email notifiers of the same cached registry (empty when alerts are disabled or the channel is not configured). No second registry, no direct `EmailNotifier()` in the tasks.
- `EmailNotifier.send_new_matches`: builds the message (From / To as `send_digest`), sends through `smtplib.SMTP`, and **re-raises** on failure (the caller keeps the rows pending). An empty recipient raises too. `LogNotifier.send_new_matches` logs ids (not used by the task; email channel only).

### Tasks (both `bind=True`, routed to `scrapers`, results are plain dicts)

- `tasks.match_saved_search_new_matches`: skip when `alerts.new_match.enabled` is not true; load searches with `owner = auth.principal_id`, `notify_new_matches`, `notify_enabled_at IS NOT NULL`; per search translate, skip unsupported, `record_new_matches`, commit per search; a failing search is rolled back, logged and counted without stopping the others; then one `hold_report` (only when at least one search is enabled) with a warning log when `expiring_24h > 0`. Result: `{status, searches, matched, unsupported, errors, held, oldest_held_hours, expiring_24h}`.
- `tasks.send_saved_search_new_match_alerts`: hourly. For each search of the principal: `withdraw_stale`; skip unless enabled and `window_is_due`; `collect_pending`; nothing pending -> leave the window unstamped; no email notifier -> `status no_email_channel`, rows stay pending; else render, `send_new_matches` on each email notifier, `mark_sent` + commit only when at least one notifier succeeded. Exceptions per search are logged and counted (`errors`), the task does not raise. Result: `{status, searches_due, emails_sent, properties_alerted, withdrawn, errors}`.
- Beat (`build_beat_schedule`, guarded with `is True` like the neighbouring entries): `match-saved-search-new-matches` every `match_interval_minutes * 60` s; `send-saved-search-new-match-alerts` at `crontab(minute=0)`.
- `send_top_deals_digest` passes `alerted_owner=cfg.auth.principal_id`; `select_top_deals(..., alerted_owner=None)` adds `NOT EXISTS (SELECT 1 FROM saved_search_new_matches a LEFT JOIN saved_searches s ON s.id = a.saved_search_id WHERE a.property_id = p.id AND a.owner = :alerted_owner AND (a.status = 'sent' OR (a.status = 'pending' AND s.notify_new_matches)))` only when an owner is given.

### API (`/saved-searches`)

- `SavedSearchItem` adds `notify_new_matches: bool`, `min_price_drop: float | None`, `notify_enabled_at: str | None`, `new_match_alerts_supported: bool` (false when the stored filters carry a non-blank `q`), `last_new_match_alert_on: str | None`.
- `POST` accepts `notify_new_matches` (default false) and `min_price_drop` (>= 0). `PATCH` accepts both; `min_price_drop: null` sent explicitly clears it (`model_fields_set`). Turning the flag on (false -> true, or creating with true) stamps `notify_enabled_at = now`; turning it off leaves the stamp; turning it on again stamps a new one. Enabling a search whose filters carry `q` is accepted and reported unsupported (never fires).

### Tests that must exist

- Unit (TDD, `test_saved_search_alerts.py`): every translation rule above, `q` -> None, floor, window due at / before / after the hour and across the date line, same-day second run not due, email text (pt-BR and en, percentile line present / absent, `+N`, held line, no link without base URL), `record_new_matches` SQL contains the exact predicates of `build_property_where` for the same filters and `ON CONFLICT`.
- Unit (`test_saved_search_alert_tasks.py`): matcher happy path and a failing search; sender happy path (fake email notifier called once, log / redis notifiers never called, rows marked) and error path (notifier raises -> not marked, `errors == 1`, no raise); disabled master switch.
- Unit: `EmailNotifier.send_new_matches` with `smtplib.SMTP` patched (sends once; failure re-raises); registry channel lookup; both tasks present in `task_routes` and in the beat schedule; config defaults and validation.
- Integration (`test_saved_search_new_matches.py`, Postgres through the gate, seeded like `test_price_percentile_filter.py`): every I/O-matrix row except the SMTP-level ones; parity (for several saved filter blobs the set recorded by the matcher equals the ids `GET /properties` returns for hand-written SPA-equivalent query parameters, restricted to new decidable Properties); release path (a Property made decidable through `_persist_ai_scores` plus a stored verdict, with no bulk recalculation, is matched on the next run); API round trip of the flag and threshold including the enable stamp; digest exclusion; unique constraint and CHECKs; fake email notifier injected through the registry.

## Verification

**Commands:**
- `C:\Workfolder\imoveis\.venv\Scripts\python.exe scripts/agent/validate.py` -- expected: exit 0 (backend tier: unit + integration + contract + alembic check).

## Auto Run Result

Status: awaiting-operator (code complete and validated; the primary needs the migration and a rebuild before anything runs there).

**Summary.** Two beat tasks on `scrapers`: a matcher (every 15 minutes) records each new, decidable Property that matches a notifying saved search, using the list endpoint's own `WHERE`; a sender (hourly) emails each search's recorded matches once per local day through the notifier registry's email channel. The saved-search API exposes the flag, the stored threshold and the alert state. No hook in the persist path.

**Files changed.**
- `src/core/property_list_filters.py` (new) — the list `WHERE` builder, shared by `GET /properties` and the matcher.
- `src/api/properties.py` — delegates to it; private names kept.
- `src/core/saved_search_alerts.py` (new) — translation, decidable rule, floor, window, record / collect / withdraw / mark, hold report, email text.
- `alembic/versions/f7a8b9c0d1e2_saved_search_new_match_alerts.py`, `src/adapters/db/models.py` — four columns on `saved_searches`, table `saved_search_new_matches`.
- `src/infra/config.py`, `configs/app_config.yaml` — `alerts.new_match`.
- `src/adapters/notify/*` — channel lookup on the one registry, `send_new_matches`.
- `src/adapters/queue/tasks.py`, `celery_app.py` — the two tasks, routes, beat; the digest passes the owner.
- `src/core/top_deals_digest.py` — already-alerted exclusion.
- `src/api/saved_searches.py` — flag / threshold round trip, enable stamp.
- Tests: lock, match-filter coverage, pure rules, tasks, notifier, celery app, config, contract, integration on Postgres.
- `docs/features/v0.14-s1.9-saved-search-new-match-detection.md`, `docs/api.md`, `docs/data-models-api.md`.

**Review.** 41 findings from four layers. Patched 14 entries (medium 5, low 9, high 0): endpoint default for a missing `price_type`, unknown-key and non-object blobs never fire, SPA deep link, SMTP timeout, one-line subject, docstring, docs, and six test additions (real dedupe path, real verdict writer, failing statement on Postgres, sender arguments, untitled Property, SPA key pin). Deferred 1 entry from the review (the pre-existing `accepts_pets` predicate bug, four rows) plus three findings of the dev session (no verdict on the primary since 2026-08-13; `evaluate_watchlist_alerts` constructor bug; unused saved-search keys). Rejected: 16 low rows and 6 false rows, each with its reason in the triage log above.

**Follow-up review: recommended (true).** Five medium entries were patched. The patches were applied after the review layers ran and no reviewer has read them: the unknown-key rule (a search now silently stops firing when its blob has an unexpected key), the changed `price_type` default, and four integration tests that only run inside the gate.

**Verification.** `C:\Workfolder\imoveis\.venv\Scripts\python.exe scripts/agent/validate.py` (auto tier resolved to backend) exited 0 on the final code: lint passed, 2548 unit tests passed (1 skipped), 281 integration, 78 contract. The gate's alembic check step is informational and lists only drift that predates this story (PostGIS tables, hand-made indexes, `saved_searches.filters` JSONB vs JSON); the in-repo test compares this story's tables and columns with the models. Read-only measurements on the primary are in the feature doc.

**Residual risks.**
- On the primary no new match can be released until enrichment produces verdicts again (deferred, with evidence).
- Mail settings on the primary are placeholders; nothing was sent and no mail server was contacted in this run.
- A notifying search with `accepts_pets` fails on every matcher run until the deferred bug is fixed.
- The email text was reviewed as text only; no mail client rendered it.

### Follow-up review (pass 2), 2026-10-08

Status: awaiting-operator (unchanged; the operator steps are in the frontmatter).

**What changed in this pass.** `main` was merged into the branch first (two frontend fixes, ledger lines; no conflict). Then:
- `fix(v0.14-s1.9): accepts_pets filter runs on Postgres` — the pets predicate casts to `jsonb` and coalesces; regression test on Postgres; the lock line follows.
- `fix: watchlist drop alert no longer raises on its first match` — `evaluate_watchlist_alerts` no longer passes `title=`; confirmed by running the task path (TypeError without the fix).
- `fix(v0.14-s1.9): a held match is never dropped; one sender per search` — no age limit on a hold (`max_age_hours` -> `hold_warning_hours`, `expiring_24h` -> `held_overdue`); an email marks only the rows it shows and the rest stay pending; the sender locks the search row and re-reads its state; `new_match_alerts_supported` is computed from the stored value; `min_price_drop` rejects non-finite values.

**Files changed in this pass.**
- `src/core/property_list_filters.py` — pets predicate.
- `src/core/saved_search_alerts.py` — floor, hold report (`held_overdue`), email `remaining` line.
- `src/adapters/queue/tasks.py` — both tasks (no age limit, row lock, overflow), watchlist constructor.
- `src/infra/config.py`, `configs/app_config.yaml` — `hold_warning_hours`.
- `src/api/saved_searches.py` — supported flag from the stored value, finite threshold.
- Tests: lock (pets line), `test_watchlist_alert_task.py` (new), task / core / config / filter unit tests, integration (pets on Postgres, hold without limit, overflow carried to the next day, concurrent sender).
- `docs/features/v0.14-s1.9-saved-search-new-match-detection.md`, `docs/api.md`.

**Review.** 38 findings from four layers. Patched 8 entries (high 2, medium 2, low 4): the hold without a time limit (3 rows), the pets predicate (2 rows), one sender per search (3 rows), overflow stays pending, supported flag for a non-object blob (2 rows), finite `min_price_drop`, the sender's hold floor test, the `price_type` wording (2 rows). Deferred 3 entries: SMTP without TLS (medium, new), the cost cap missing from the saved-search wire (low, new), enrichment on the primary (high, carried). Removed from `deferred` because fixed: the pets predicate and the watchlist constructor. Rejected: 17 low rows and 3 false rows, each with its reason in the triage log.

**Ruling on the 168-hour expiry.** Not licensed. The acceptance criterion names one end of a hold (verdict stored and percentile evaluated) and says "never dropped"; UX-DR11 only forbids alerting early; no planning document mentions a maximum age. The code now delivers late: a held Property is alerted when it becomes decidable, whenever that is, and a hold longer than 168 hours is visible as `held_overdue` in the matcher result and a warning log.

**Follow-up review: recommended (true).** This pass patched two high entries (patched counts: high 2, medium 2, low 4), and no reviewer has read those patches. The specific unverified risks: (1) the sender's row lock is held across the SMTP conversation, and its interplay with a `PATCH` of the same search was reasoned about, not tested; (2) with no age limit, the first release after a long enrichment gap is a backlog delivered 20 per search per day, a product behaviour nobody has confirmed; (3) the pets predicate's negated form now keeps Properties without an `amenities` key, which changes what `accepts_pets=false` returns compared with the text that was locked (that text never ran).

**Verification.** `C:\Workfolder\imoveis\.venv\Scripts\python.exe scripts/agent/validate.py` (auto tier resolved to backend) exited 0: lint, unit, 283 integration, 78 contract; the alembic check step is informational and lists only drift that predates the story. Read-only on the primary: the fixed pets predicate runs (89,327 true, 110,867 false, 200,194 active), the matcher's SELECT with the floor at the year 2000 takes 738 ms, and `saved_searches` is empty. No email was sent and no mail server was contacted.

**Residual risks.**
- On the primary nothing is decidable, so nothing is alerted until enrichment runs again (deferred); the matcher then releases a backlog.
- The mail path was never exercised against a server; TLS is missing (deferred).
- The beat tasks share the `scrapers` queue with a scrape backlog of about 10,400 on the primary; how late they run there is not measured.

### Follow-up review (pass 3, narrow), 2026-10-08

Status: awaiting-operator (unchanged; no operator step changed).

**Scope.** The three commits of pass 2 only (`2ba24cd5`, `b4f9d6e9`, `b446d69c`), against five questions set by the orchestrator. One reviewer, no review layers.

**What changed in this pass.**
- `fix(v0.14-s1.9): the sender sends with no lock held; oldest Property first` — the sender claims the day under the row lock and commits, sends with nothing held, then marks; a failed send gives the day back. `collect_pending` breaks a `matched_at` tie by `first_seen`.
- `docs(v0.14-s1.9): review pass 3` — the `accepts_pets` rule in `docs/api.md`, the backlog behaviour, the failure table and the measurements in the feature doc, this log.

**Files changed in this pass.**
- `src/adapters/queue/tasks.py` — sender: claim, send, mark / release.
- `src/core/saved_search_alerts.py` — `claim_window`, `release_window`, order of `collect_pending`.
- Tests: `test_saved_search_alert_tasks.py`, `test_saved_search_alerts.py`, integration `test_saved_search_new_matches.py` (four new tests, one strengthened).
- `docs/features/v0.14-s1.9-saved-search-new-match-detection.md`, `docs/api.md`.

**Review.** 9 findings. Patched 4 (medium 1, low 3): the lock across the send, the `accepts_pets=false` rule in the docs, the order inside a backlog, the backlog note. Rejected 2 low rows and 3 false rows, each with its reason in the triage log. Nothing deferred; the `deferred:` list is unchanged.

**Answers to the five questions.**
1. The lock did block `PATCH` and `DELETE` for the length of the send (confirmed on Postgres); fixed. The matcher was never blocked.
2. `accepts_pets=false` is the complement of `true`; kept and documented. The regression test fails against the old predicate.
3. A matcher run is one statement per search, linear and cheap: at most 1.3 s per search with the whole table as candidates.
4. Cap 20, oldest first, `+N` line: as documented; the tie inside one matcher run is now decided by `first_seen`.
5. The watchlist alert carries every field the notifiers read.

**Follow-up review: not recommended (false).** No high finding; the one medium patch is covered by tests that fail without it and were run both ways.

**Verification.** See the final report of this pass for the gate result on the last commit. Before the fixes, on this worktree's test stack: the three new mid-send tests failed (`lock timeout`), the pets test failed against the old predicate, the order test failed without the tie-break. No email was sent and no mail server was contacted. Reads on the primary were read-only.

**Residual risks.**
- Unchanged from pass 2: nothing is decidable on the primary; the mail path was never run against a server and has no TLS; the beat tasks share the `scrapers` queue.
- The `INSERT` half of the matcher was not measured on the primary (the table is not there yet).
