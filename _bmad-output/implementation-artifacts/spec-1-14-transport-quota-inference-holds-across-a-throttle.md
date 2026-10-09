---
title: 'Story 1.14 — Transport-quota inference holds across a throttle'
type: 'feature'
created: '2026-10-09'
status: awaiting-operator
baseline_revision: 'd49eb4a2086c902ef51af6aef9ffabf80e3d39de'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/docs/features/v0.13-fu8-gemini-transport-quota-classification.md'
  - '{project-root}/docs/features/v0.14-s1.13-runner-lifecycle-ends-honestly.md'
  - '{project-root}/docs/features/_template.md'
warnings: ['oversized']
deferred:
  - summary: >-
      The A/B harness passes the transport-quota window and hold to its client with no test, so a
      dropped keyword would give that client the default hold whatever the config says.
    evidence: |-
      scripts/dev/ab_gemini_vs_ollama.py builds the gemini arm's client with
      transport_quota_window_seconds and, since Story 1.14, transport_quota_hold_seconds. No test
      imports that script (a search of the tree for ab_gemini_vs_ollama finds the script and one
      docstring). The other two construction sites are pinned (test_ai_client.py,
      test_backfill_gemma_cli.py). Pre-existing: the window keyword on the line above has been
      unpinned since v0.13-fu8, and the script is a manual tool that needs a live key. A fix is a
      unit test that loads the script and asserts the keywords of the client it builds.
    location: >-
      scripts/dev/ab_gemini_vs_ollama.py (_amain, the gemini arm's client)
    severity: low
  - summary: >-
      The number of rows whose quota refusal was inferred is not on the last_run record, the
      status endpoint or the Operações card, so an operator of a --serve run sees it only in the
      host log.
    evidence: |-
      Found by the follow-up review of Story 1.14 (2026-10-09). The banner line of DW-16 is
      print() output. Under the host supervisor (scripts/windows/backfill_host.py, pythonw with
      stdout redirected) it lands in .run\backfill-host\host.log. _run_supervised
      (scripts/dev/backfill_gemma.py) gets only the exit code back from main(), and the last_run
      record is written from that code and _exit_reason(code, cfg); neither is handed a
      BackfillResult. Story 1.13 put every ending on the card, and since Story 1.14 a cycle
      refused by inference counts towards exit 10 and towards the daily-window wait, so the card
      can show "provider_refused" or a long "backing-off" that rests partly or wholly on
      transport failures with no number beside it. The follow-up review changed the exit-10
      sentence to say that a refused cycle may have been inferred and to name the network route;
      it carries no count. Outside the story's contract ("No wire change"), and outside the
      original text of DW-16 (which names the banner, the backfill_terminal event and the
      quarantine report, all done). A fix returns the count out of _run_continuous and main,
      adds a field to the last_run record, src/api/schemas.py, the contract test and the card,
      and shows it on the backing-off state too. No existing ledger entry covers this (DW-86 is
      about the Painel health strip and notifications).
    location: >-
      scripts/dev/backfill_gemma.py (_run_supervised, _exit_reason, _record_last_run),
      src/core/backfill_runner.py (last_run record), src/api/schemas.py,
      frontend/src/components/operations/BackfillCard.tsx
    severity: low
operator_actions:
  - >-
    AGENT-RUNNABLE. Once Ollama answers on localhost:11434 (starting it is the human's decision; do
    not start it), run from the PRIMARY checkout (C:\Workfolder\imoveis), after the branch is
    merged: .venv\Scripts\python.exe scripts/agent/validate.py --only ai . Verify: the output has
    a PASS line for "ai: golden tests" and no "AI golden tests SKIPPED" warning, and the exit code
    is 0. Record the result under "## Auto Run Result" of this spec and move the story on. On
    2026-10-09 Ollama did not answer (a GET of http://localhost:11434/api/tags timed out), so the
    gate skipped that suite; the story's AC "the AI golden tests pass" is not met until this runs.
    What the run proves (follow-up review): --only ai runs one file,
    src/tests/unit/test_ai_quality.py, against the local model through OllamaClient. A pass
    shows that adapters/ai/client.py still imports and the local scoring path is within
    tolerance. It exercises nothing Story 1.14 changed (GeminiClient, the licence, the
    classifier); those are covered by the unit tests with a fake provider only.
---

<intent-contract>

## Intent

**Problem:** The v0.13-fu8 inference reads a storm of identical transport failures as a provider throttle only when a stated refusal (429) is at most `ai.gemini_transport_quota_window_seconds` (300 s) old, lives on a client that `--continuous` rebuilds every cycle, and declines any call that saw an HTTP response. So a throttle that turns silent mid-call (DW-12), stays silent past the window (DW-13) or crosses a cycle boundary (DW-14) charges good rows an attempt each; a 429 seen long after a storm began licenses it (DW-15); and the end-of-run banner says nothing about inferences (DW-16).

**Approach:** Keep "what the provider last told this process" in one small process-local object that outlives the per-cycle client and is shared by every client of a `--continuous` run. A stated refusal licenses a storm for the short window on both sides, and for a bounded, config-owned hold after it while the provider has answered nothing at all since; a stated refusal inside the call licenses that call's storm directly. Rows classified by inference are counted by the runner and stated in every end-of-run banner.

## Boundaries & Constraints

**Always:**
- `AIQuotaExhaustedError.is_quota_exhausted` stays the only signal that makes `run_backfill` roll an attempt back; an inferred refusal additionally carries `is_quota_inferred = True` (duck-typed, AD-1: `src/core` imports no adapter).
- A licence is anchored on a refusal the provider stated. An inference never stamps, moves or extends it (no self-reinforcement). A 200 clears it.
- Every bound is an `AIConfig` field with a `Field(...)` range, threaded to the client at all three construction sites; a hand-built client clamps and logs like the existing window does.
- Clocks are monotonic and read through the client module's `time` name.
- Each inference is audible: its own counter, a distinguishable `last_error`, a WARNING naming signature, attempts and the basis it was licensed on (`in-call`, `window`, `hold`).
- An inferred refusal is a quota refusal for Story 1.13's no-progress rule (`BackfillResult.quota_exhausted`); a storm that is not read as quota stays a hard row error and does not feed that count.
- Every provider response in tests is a fake. No network call to a provider.

**Block If:** closing an entry would need a second consumer of the `backfill:gemma` pacer, a new exit code, or a change to what `AttemptLedger.record_attempt` counts.

**Never:**
- No Redis key for inference state (see Design Notes). No change to `LivenessTicker`, the main-thread watchdog, the exit-code table, `_is_quota_response`, `_QUOTA_BODY_MARKERS`, the retry ladder's statuses, retry decisions or back-off.
- `rate_limit_hits` never counts an inference.
- No wire change: `src/api/schemas.py` and the `last_run` record are not touched (Design Notes).
- Do not edit `sprint-status.yaml`. Do not edit the Story 1.13 regression tests.

## I/O & Edge-Case Matrix

"Storm" = every attempt of one call was either a stated 429 or a transport failure, all transport failures share one full signature, the call has at least two such attempts in total and ends in transport. `W` = window (300 s), `H` = hold (7200 s), `d` = first transport failure of the call minus the last stated refusal.

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Throttle turns silent mid-call (DW-12) | attempt 0 answers 429, the remaining attempts are identical resets | `AIQuotaExhaustedError`, `is_quota_inferred`, basis `in-call`; `rate_limit_hits` +1 for the 429 only | Runner rolls the attempt back |
| Non-quota answer in the call | attempt 0 answers 503 (or a body read fails), the rest are resets, recent 429 | raw transport error | Hard row error, attempt stands |
| Silent past the window (DW-13) | 429 stated 1 800 s ago, nothing answered since, identical storm | inferred, basis `hold` | Rolled back |
| Silent past the hold | 429 stated more than `H` ago, identical storm | raw transport error | Hard row error |
| Answered since the refusal | 429 stated 1 800 s ago, then a 500 was answered, then a storm | raw transport error (the hold needs silence; the window is over) | Hard row error |
| Answered, but inside the window | 429 stated 10 s ago, then a 500, then a storm on a later call | inferred, basis `window` (fu8 behaviour kept) | Rolled back |
| Cycle boundary (DW-14) | cycle 1 ends on a stated 429; 900 s back-off; cycle 2 builds a new client and meets a storm from its first call | inferred through the shared licence; the row's ledger attempt count is 0 | Rolled back, cycle counts as a provider refusal |
| Separate runs | a client built without a shared licence | starts with no evidence, as before | n/a |
| 429 long after the storm began (DW-15) | storm's first failure at `t`, another row's 429 stamped at `t + 10 000 s` before the storm's last attempt | raw transport error (`d < -W`) | Hard row error |
| 429 shortly after the storm began | same, stamped at `t + 10 s` | inferred, basis `window` | Rolled back |
| Success in between | 429, then a 200, then a storm | raw transport error (licence cleared) | Hard row error |
| Hold disabled | `H = 0` | only `in-call` and `window` license | n/a |
| Window disabled | `W = 0` | no inference at all, whatever `H` is | Hard row error |
| Banner (DW-16) | a `--continuous` run in which rows were classified by inference in two different cycles | every terminal banner and the `backfill_terminal` event state the run-wide number of rows; nothing is printed when it is 0 | n/a |

</intent-contract>

## Code Map

Adapter, `src/adapters/ai/client.py`:
- `AIQuotaExhaustedError` (:229) -- add subclass `AITransportQuotaInferredError` with `is_quota_inferred = True`.
- `GeminiClient` (:926): constants (:951-961), ctor (:963, window clamp :1004-1026), `last_rate_limit_at` (:1029), `_note_rate_limit_hit` (:1032), `_clear_rate_limit_recency` (:1043), `_is_transport_throttle` (:1055), `_raise_inferred_transport_quota` (:1092), `chat_completions` (:1128; `saw_http_response` set at :1176, 429 retry :1184, terminal quota :1201, transport arm :1214-1235).
- `create_ai_client` (:1536-1541) -- third construction site.
- NEW `TransportQuotaLicence` (module level, above `GeminiClient`): `refused_at`, `answered_since_refusal`, `note_refusal()`, `note_success()`, `note_other_answer()`. No counter, no Redis, no knobs.
- `GeminiClient.session_context` (:541) opens one aiohttp session per pass; client lifetime stays per pass.

Core, `src/core/backfill_runner.py`:
- `is_quota_exhausted` (:2067) -- add `is_quota_inferred(exc)` beside it (attribute only, no text net).
- `BackfillResult` (:2322, `to_dict` :2377) -- add `quota_inferred_rows: int = 0`.
- `_worker` quota branch (:3040-3050) -- count the row when the exception is inferred.
- `to_dict` feeds only the `backfill_done` log line (`scripts/dev/backfill_gemma.py:2828`); `src/api/admin.py:415` is a different result type.

CLI, `scripts/dev/backfill_gemma.py`:
- `_build_client` (:521) -- gains keyword `quota_licence=None`; threads the hold.
- `_run` (:1040; client built :1104) -- gains keyword `quota_licence=None`.
- `_on_progress` (:1174) -- already logs the per-client counter; unchanged.
- `_terminal_summary` (:1345), `_finish` (:1360) -- gain `inferred`.
- `_run_continuous` (:1624): accumulators (:1659-1661), `backfill_cycle_done` (:1716), `_end` (:1792), lease-lost banners (:1808-1836), stopped (:1856), breaker (:1879), provider refused (:1951-1973). `quota_zero_cycles` (:1927) reads `result.quota_exhausted` and is not changed.
- `main` single pass: the "Backfill pass done" line (:2843).
- `scripts/dev/ab_gemini_vs_ollama.py:496` -- construction site.

Config: `src/infra/config.py` `AIConfig` (:317-330), `configs/app_config.yaml` (:300-306), `backfill.quota_backoff_seconds: 900` (:396).

Tests:
- `src/tests/unit/test_ai_quota_propagation.py` -- helpers `_transport_client` (:293, `throttled_ago` stamps `client.last_rate_limit_at`), `_reset`, `_http_response`, `_ctx`, the `_FakeClock` pattern (:588). `test_storm_after_a_stale_throttle_stays_a_hard_error` (:394) uses a 3 600 s old stamp, which the hold now licenses: it is restated (hold disabled, plus a beyond-the-hold case). No other existing test changes meaning.
- `src/tests/unit/test_config.py` (:525-585) -- default and bounds tests for the window; the pattern to copy.
- `src/tests/unit/test_ai_client.py` (:346, :369), `src/tests/unit/test_backfill_gemma_cli.py` `_wire` (:119), `src/tests/unit/test_backfill_gemma_completion_cli.py` `_cfg` (:80) -- `MagicMock` configs: the new float MUST be set as a real number (`float(MagicMock())` is 1.0).
- `test_backfill_gemma_cli.py:324, :395` stub `_build_client` with `lambda cfg, scope=None`; they need `**_kw`. `_run` fakes all take `**kwargs` or are `MagicMock`.
- Runner tests with a real `run_backfill`: `src/tests/unit/test_backfill_circuit_breaker.py` (`_run` :153) is the model for a ledger-observing test.
- Story 1.13 tests that must stay green unedited: `test_backfill_gemma_cli.py` `_refusing_provider` (:3395) and its users, including `test_the_fifth_and_sixth_refusal_are_a_daily_window_apart`.

Ledger: `_bmad-output/implementation-artifacts/deferred-work.md` DW-12 (:100), DW-13 (:107), DW-14 (:114), DW-15 (:121), DW-16 (:128).

## Tasks & Acceptance

**Execution:**
- `src/tests/unit/test_ai_quota_propagation.py` -- first, failing: one test per matrix row above the banner row (in-call 429 then silence; non-quota answer in the call; silent past the window; past the hold; answered since the refusal; answered inside the window; two clients sharing a licence across a 900 s gap; unshared clients; the two-sided pair; hold disabled; window disabled with a hold; an inference does not move the anchor; the WARNING names the basis; the inferred error is `is_quota_inferred` and still `is_quota_exhausted`). Restate the stale-throttle test -- TDD on classifier branches.
- `src/infra/config.py`, `configs/app_config.yaml`, `src/tests/unit/test_config.py` -- `ai.gemini_transport_quota_hold_seconds: float = Field(default=7200.0, ge=0.0, le=21600.0, allow_inf_nan=False)` with a comment stating what it bounds and why 6 h is the ceiling; default, bounds and client-mirror tests; a test that the shipped hold is longer than the shipped `backfill.quota_backoff_seconds` -- config-owned bound, and DW-14's "the two knobs are ordered so a licence can never cross" pinned the other way.
- `src/adapters/ai/client.py` -- `TransportQuotaLicence`; `AITransportQuotaInferredError`; `GeminiClient(..., transport_quota_hold_seconds=, quota_licence=None)` (own licence when none is given; hold clamped to `[0, 21600]` with the same logged correction); `last_rate_limit_at` becomes a read/write property over the licence; `chat_completions` records stated refusals inside the call and treats only *other* answers as the disqualifier; the basis function replaces `_is_transport_throttle`; docstrings say what is and is not read as quota; `create_ai_client` threads the hold -- DW-12, DW-13, DW-14, DW-15.
- `src/core/backfill_runner.py`, new `src/tests/unit/test_backfill_quota_inferred_rows.py` -- test first: with a real `run_backfill` and ledger, an inferred refusal rolls the attempt back, sets `quota_exhausted` and counts one `quota_inferred_rows`; a stated refusal counts none; a raw transport error charges the row, sets no `quota_exhausted` and counts none -- the row count for the banner and the truth of the 1.13 signal.
- `scripts/dev/backfill_gemma.py`, `scripts/dev/ab_gemini_vs_ollama.py`, `src/tests/unit/test_backfill_gemma_cli.py`, `src/tests/unit/test_backfill_gemma_completion_cli.py`, `src/tests/unit/test_ai_client.py` -- test first. `_run_continuous` creates one licence per run (a WARNING when the hold is positive and not longer than `quota_backoff_seconds`), passes it to every `_run`, which passes it to `_build_client`; it accumulates `quota_inferred_rows` across cycles and hands the total to every banner path, to `backfill_cycle_done` (per cycle) and to `backfill_terminal`. `main`'s single pass prints the count on its own line when positive. Tests: the same licence object reaches every cycle's client; an end-to-end `--continuous` run with real `_run`, `run_backfill`, ledger and `GeminiClient` over a scripted fake session (cycle 1 stated 429, 900 s later cycle 2 storm on a new client, cycle 3 answers) leaves the row with no attempt charged and prints the banner line; a hard storm in cycle 2 with no licence charges the row and is not counted as a refusal cycle; banner line absent at 0 -- DW-14, DW-16.
- `docs/features/v0.14-s1.14-transport-quota-inference-holds.md` -- from the template, all sections; a note in the fu8 feature doc pointing to it -- feature doc.
- `_bmad-output/implementation-artifacts/deferred-work.md` -- DW-12..DW-16: `status: resolved` plus `resolution:` only for what the code resolves; narrowed scope stated where something stays open -- ledger.

**Acceptance Criteria:**
- Given a provider that stated a refusal and then answers nothing, when rows are attempted in the same call, later in the pass, or in the next `--continuous` cycle after the back-off, then each such row ends as a quota refusal with no ledger attempt charged, for at most the hold after the last stated refusal.
- Given a storm with no stated refusal in reach (none ever, older than the hold, cleared by a success, or stamped more than the window after the storm began), when it is classified, then the raw transport error propagates and the row is charged as before.
- Given a `--continuous` run in which N rows were classified by inference, when it ends on any terminal banner, then the banner states N.
- Given Story 1.13's no-progress rule, when a cycle ends on an inferred refusal with nothing enriched, then it counts towards `backfill.max_no_progress_cycles`; a cycle that ended on a storm not read as quota does not.
- Given the diff, when inspected, then `backfill_runner.py` has no adapter import, no Redis key was added, and `LivenessTicker`, the watchdog and the exit codes are untouched.

## Spec Change Log

## Review Triage Log

### 2026-10-09 — Review pass
- verdicts: 35 findings — high 0, medium 8, low 23, false 4, maybe-false 0
- findings:
  - `[medium]` `[patch]` Blind: the lease-lost banner after `_sleep_for_reset` omits the inferred count — true at the last return of `_run_continuous`; the line is added and `test_a_lease_lost_in_the_quota_backoff_states_the_inferred_rows` covers it.
  - `[medium]` `[patch]` Blind: the banner says rows but sums row refusals over cycles — true, a rolled-back row is a candidate again; `BackfillResult.quota_inferred_ids` replaces the counter (`quota_inferred_rows` is its length) and `_run_continuous` keeps a set; `test_a_row_inferred_in_two_cycles_is_one_row_on_the_banner`.
  - `[low]` `[patch]` Blind: the hold/back-off check accepts 901 s — true; the warning now fires up to `quota_backoff_seconds + ai.timeout`, and `test_config.py` computes the four-pass figure (5100 s) from the knobs and requires the shipped hold to reach it.
  - `[low]` `[patch]` Blind: the ordering warning fires with the window at 0 — true; gated on a positive window (`test_the_hold_warning_is_silent_when_the_inference_is_off`). A dry run or an all-local map still warns: harmless, left.
  - `[low]` `[patch]` Blind: an inferred refusal is narrated as a stated one on the wait line — true; `_inferred_clause` adds "(inferred from transport failures on N row(s), no 429 on them)" to the three quota wait reasons. The exit-10 banner already carries the inferred line.
  - `[low]` `[reject]` Blind: stopped, lease-lost and migration endings have no `backfill_terminal` event — true and pre-existing: those endings never emitted the event. Adding five log events is more than a correction, and `backfill_cycle_done` carries each cycle's count; the feature doc now says "where that event exists".
  - `[low]` `[patch]` Blind: a retried 5xx with a quota body is "another answer" before the last attempt and a stated refusal on it — true; the retry branch now uses `_is_quota_response`, as the terminal branch does (`test_a_retried_answer_with_a_quota_body_is_a_stated_refusal_too`).
  - `[low]` `[patch]` Blind: the floor constant, its comment and the message "ended in 1 identical transport failures" are stale — comment and message corrected; the constant keeps its fu8 name (the fu8 feature doc cites it). `[429 x4, reset]` being quota is the design (Design Notes).
  - `[low]` `[patch]` Blind: the "every attempt accounted for" guard is unpinned — pinned by `test_every_attempt_of_the_call_has_to_be_accounted_for`, which calls the basis function directly.
  - `[low]` `[reject]` Blind: inferred rows of a pass that dies on Redis after a lease loss are dropped — true and the same for every counter of that pass (`_lease_lost_pass` returns an empty result, pre-existing). Needs a Redis outage as long as the lease TTL in the same pass as an inference; a fix means carrying a partial result out of an exception. Noted in the feature doc.
  - `[low]` `[patch]` Blind: the feature doc's concurrency note is partly wrong — rewritten after the in-call change below; it now also names the hold ending for every row.
  - `[low]` `[patch]` Blind: spec says both "close the ledger" and "do not edit it"; the fu8 pointer omits DW-16 — the part that asks for a spec edit is rejected (the Working Rules were for the implementer, the ledger was closed by this session in the same commit); the fu8 pointer now names DW-16.
  - `[low]` `[patch]` Blind: derived numbers in comments — "(900)" removed from the YAML comment; the 5100 s in `config.py` now points at the test that computes it.
  - `[medium]` `[patch]` Edge: lease lost during the quota back-off sleep prints no inferred line — same defect as the first row.
  - `[low]` `[patch]` Edge: retried 5xx with a quota marker — same defect as the Blind row above.
  - `[low]` `[patch]` Edge: with concurrency above 1, a 200 on another row after this call's 429 does not revoke the in-call basis — true; the basis function now returns nothing when the licence is cleared, before looking at in-call refusals (`test_a_success_on_another_row_revokes_an_in_call_refusal`).
  - `[low]` `[reject]` Edge: with concurrency above 1, another row's 429 more than the window after a hold-licensed storm began moves the anchor ahead of the storm and the row is charged — true. Needs two rows in flight (shipped concurrency is 1), a storm longer than the window and a 429 inside it; costs one attempt, the fu8 status quo. The fix keeps a second copy of the licence per call and three more branches. Written up in the feature doc as a known gap.
  - `[low]` `[patch]` Edge: hold marginally above the back-off gets no warning — same defect as the Blind row above.
  - `[low]` `[patch]` Edge: warning with a zero window — same defect as the Blind row above.
  - `[medium]` `[patch]` Edge (claim): "hands the total to every banner path" is untrue for the sleep ending — same defect as the first row.
  - `[low]` `[patch]` Edge (claim): "a 200 clears it" does not hold for the in-call basis — same defect as the in-call row above.
  - `[medium]` `[patch]` Verification gap: no test for the lease-lost-in-sleep ending with inferred rows — test added with the fix.
  - `[low]` `[patch]` Verification gap: the no-census lease-lost banner line is untested — `test_a_lease_lost_ending_without_a_census_states_the_inferred_rows`.
  - `[low]` `[patch]` Verification gap: an unreadable-body answer ending the hold for later calls is not asserted — `test_an_unreadable_answer_ends_the_hold_for_later_calls`.
  - `[low]` `[defer]` Verification gap: the A/B harness construction site is untested — true and pre-existing for the whole script (frontmatter `deferred`).
  - `[medium]` `[patch]` Verification gap (other): the sleep ending is a behaviour defect against the AC — same defect as the first row.
  - `[medium]` `[patch]` Verification gap (other): the feature doc's list of endings is inaccurate — true until the fix; the list is now accurate.
  - `[false]` `[reject]` Intent (a): the throttle is not held "for as long as it lasts", the hold is bounded — the entries this story closes select the bounded reading: DW-13 asks for "a decaying or bounded self-licence" and names an unbounded one as the way an outage is masked for a whole run. Past the hold a storm is a row error by decision (Design Notes, ledger DW-13).
  - `[false]` `[reject]` Intent (b): silence before any 429 was ever seen has no licence — by design: with no stated refusal a storm cannot be told from an outage, and the fu8 contract this story extends forbids reading every connection failure as quota. Stated in the DW-14 resolution.
  - `[medium]` `[patch]` Intent (c): the banner number is not distinct rows — same defect as the second row.
  - `[low]` `[patch]` Intent (d): mid-call is asserted at the client and "no attempt charged" with hand-made exceptions — `test_a_throttle_that_turns_silent_mid_call_charges_no_attempt` runs the adapter's own error through the real runner and ledger; the silent-past-the-window case already ran end to end (the cycle test's storm is 900 s after the refusal).
  - `[low]` `[patch]` Intent (e): the end-to-end tests bypass the enrichment stages — `test_the_enrichment_stages_let_an_inferred_refusal_through_intact` drives a real storm through `analyze_visuals`, `analyze_text` and `summarize_deal`. `run_enrichment` itself needs a database and stays outside these tests.
  - `[low]` `[patch]` Intent (f): no test drives a real inferred refusal to exit 10 — `test_cycles_refused_by_inference_count_towards_the_no_progress_exit`.
  - `[false]` `[reject]` Intent (g): unknown whether a supervised run's banner reaches the operator — `_run_supervised` calls `main(argv)` in the supervisor's own process, so the banner goes where every other banner of the run goes. The status endpoint was left out by the intent's own option (Design Notes).
  - `[false]` `[reject]` Intent (h): behaviour widened beyond the five entries, all documented — a description, no bad outcome named; each item is a decision recorded in Design Notes.

### 2026-10-09 — Review pass (follow-up)
- verdicts: 29 findings — high 0, medium 1, low 25, false 3, maybe-false 0
- findings:
  - `[low]` `[patch]` Blind: the wait-line clause "no 429 on them" is false for a row licensed `in-call` (it was answered 429 in that call) — true; the clause now says "no 429 on their last attempt", as the banner line does.
  - `[low]` `[reject]` Blind: the distinct-row count hides for how many cycles the run rested on inference — true at concurrency 1 (a pass stops on its first refusal, and the same row tends to come back). Each cycle's wait line and `backfill_cycle_done` carry the per-cycle figure; a second number on every banner and event is new surface, not a correction.
  - `[low]` `[reject]` Blind: the inference WARNING does not log the age of the anchor — true; not a defect. It needs the basis function to return more than a name; the hold's bound and the basis are on the line.
  - `[low]` `[reject]` Blind: a declined inference has no line of its own — true; the hard error is logged with its traceback as before, and a reason code per declined branch is new surface.
  - `[low]` `[patch]` Blind: the exit-10 reason on the Operações card reads as a stated refusal although inferred cycles feed the count — true; `_exit_reason` now says a cycle counts when the refusal was stated or inferred from transport failures and names the network route beside the quota (`test_the_exit_ten_reason_on_the_card_names_the_inferred_reading`, which also holds it under the record's 500 characters). The missing count on the card is the Intent (f) row.
  - `[low]` `[patch]` Blind: the stated reason for keeping the count off `last_run` ("a child-to-supervisor channel") is wrong, `main` runs in the supervisor's process — true; the feature doc now says what the change would really take. The part that asks for an edit of this spec's Design Notes is rejected.
  - `[low]` `[reject]` Blind: `test_config.py` writes the pass count as literals instead of `_MAX_QUOTA_BACKOFF_CYCLES`, and this spec's "4 x about 630 s" does not add up to 5100 — true. The constant lives in a script that `test_config.py` would have to load by path, and Story 1.13's tests pin the four-pass ladder itself; the spec figure is a spec edit.
  - `[low]` `[reject]` Blind: the spec's Code Map, Tasks and matrix no longer describe what shipped — the fix is to edit this build's spec.
  - `[false]` `[reject]` Blind: `epics.md` still says "for as long as it lasts" and the golden-test criterion is not among the spec's ACs — carried: the bounded reading was settled in the first pass (Intent (a), (b)); the golden-test criterion is carried as the operator action, and moving it is a spec edit.
  - `[low]` `[reject]` Blind: residual gaps are in prose, not in the ledger — the ledger is minted from this spec's `deferred:` list, which holds the two items that deserve tracking (A/B harness, the count on the status record). The others were rejected as low in the first pass and are in the feature doc.
  - `[low]` `[patch]` Blind: classifier branches with no test — `test_a_refusal_stated_in_the_middle_of_the_storm_is_in_call_evidence` and `test_an_in_call_refusal_does_not_excuse_mixed_failure_shapes` added; the asymmetry (another row's 500 ends the hold but does not veto an in-call basis) is now stated in the feature doc. A hold storm that outlives the hold is judged at its first failure by the same subtraction the window test pins; not added.
  - `[low]` `[reject]` Blind: the retry branch counts a quota-bodied 5xx in `rate_limit_hits`, and some wording still says "429" — carried from the first pass (that change was its patch). `_is_quota_response` matches five specific phrases, not the words "quota" or "rate"; the terminal branch has counted such answers since before this story; `_note_rate_limit_hit` says "429 / quota body". The daily budget counts `request_count` and the breaker counts refused results: neither reads this counter.
  - `[low]` `[reject]` Blind: the hold warning's name and its firing on dry runs and local routing — carried from the first pass (rejected there as harmless).
  - `[low]` `[patch]` Edge: wait-line clause — same defect as the first Blind row.
  - `[low]` `[reject]` Edge: with concurrency above 1, an in-call 429, another row's 200 and a third row's 429 leave the in-call basis licensed — true. Needs three rows in flight inside one retry ladder (shipped concurrency is 1), and the licence is live on a refusal stated after the success; closing it is a per-call copy of the licence.
  - `[low]` `[reject]` Edge: the hold warning has no allowance for the next pass's start-up time — true; the warning is advice about an operator's own values and the shipped hold is eight times the back-off.
  - `[false]` `[reject]` Edge (claim): a storm with mixed signatures under a live hold is still charged — the contract's definition of a storm requires one signature; open since fu8 and listed in the feature doc.
  - `[low]` `[patch]` Verification gap: the clause is asserted on one of the three wait lines — `test_the_long_wait_line_says_when_the_refusal_was_inferred` and `test_the_budget_spent_wait_line_says_when_the_refusal_was_inferred`; both fail with the clause removed from their arm.
  - `[low]` `[patch]` Verification gap: the 200-with-unreadable-body test passes with `unclassified_answer` moved below the 200 branch — `test_an_unreadable_200_vetoes_the_call_even_when_the_licence_is_live_again` re-stamps the licence before the body read fails; it fails under that mutation, the older test does not.
  - `[low]` `[reject]` Intent (a): most matrix rows are asserted at the call and reach the row by composition — carried (first pass, Intent (d)): three cases join client, runner and ledger.
  - `[low]` `[reject]` Intent (b): the end-to-end runs make one row one call — carried (first pass, Intent (e)). A row is up to three sequential calls on one licence; a 200 on an earlier call clears it by the contract's own rule.
  - `[low]` `[reject]` Intent (c): "another row" is simulated on the licence object — true; two calls in flight need a harness this suite does not have, and shipped concurrency is 1.
  - `[low]` `[reject]` Intent (d): time is a stepped clock, no attempt consumes `ai.timeout` — true; the judgement uses the first failure's stamp only, and the figures that depend on durations are arithmetic pinned in `test_config.py`.
  - `[low]` `[reject]` Intent (e): banner tests feed hand-built results — true; three end-to-end runs produce the count from the real classifier.
  - `[low]` `[defer]` Intent (f): under `--serve` the banner goes to the host log and the status record has no count — true and outside the contract ("No wire change"); frontmatter `deferred`.
  - `[false]` `[reject]` Intent (g): behaviour beyond the matrix — carried (first pass, Intent (h)): a description, each item a recorded decision.
  - `[low]` `[patch]` Intent (h): the new bases are never run on `GemmaClient`, the class the backfill builds — `test_the_backfill_client_classes_both_carry_the_licence_across_a_cycle` runs in-call and hold through both classes on a shared licence.
  - `[medium]` `[patch]` Orchestrator: the documents said an outage after a stated refusal is masked "for up to the hold (7200 s)". The fourth refused pass makes the runner wait for the rest of the daily window, so a run is parked for up to 24 h and a permanent egress failure reaches exit 9 up to about a day late — the feature doc ("Accepted cost of the hold"), the DW-13 resolution and the YAML comment now say so, with the reason the default stays 7200 s. No code change: the contract makes an inferred refusal a quota refusal for Story 1.13's rule.
  - `[low]` `[patch]` Orchestrator: "after four refused passes ... the next pass is past the hold" is not always true (a fifth can be inside it when little of the daily window is left); what holds is that the sixth cannot be — corrected in the feature doc and pinned by `test_no_allowed_hold_reaches_across_a_daily_budget_window` (hold ceiling below the 24 h budget window).

## Design Notes

**Sequencing note checked.** Stories 3.1 and 3.2 are not started and no SPIKE-1 verdict exists under `planning-artifacts/research/` or in the ledger, so the advisory re-scope did not apply. Full scope.

**Where the state lives: a process-local object, not the client, not Redis (DW-14).** Hoisting the client above the cycle loop changes session and pool lifetime for every run and still loses the count per cycle unless the counter moves too. Redis would need a wall clock (fu8 rejected one: a clock step must not license or revoke), would be a second quota key beside the pacer, and would let a licence survive an operator restart, which is the one moment a fresh look is cheap. `TransportQuotaLicence` holds two fields, is created once per `--continuous` run, and each cycle's client is built around it. A single pass, the A/B harness and `create_ai_client` get a private one, as today.

**The hold is the bounded self-licence DW-13 asked for.** Anchored on the last *stated* refusal and never moved by an inference, so one inference cannot license the next for ever. It needs total silence since that refusal: any answered status other than a 429 ends it (a 200 ends the whole licence). 7 200 s covers the four refused passes that are `quota_backoff_seconds` apart, timeouts included (4 x about 630 s of storm + 3 x 900 s + start-up, about 5 100 s), after which the runner waits for the daily window anyway. A provider still silent after that wait is past the hold: its storms are hard errors, the circuit breaker (3 consecutive rows) or the stall exit ends the run by name, and the no-progress count is not fed by a guess. Cost accepted: a real outage that begins right after a stated refusal is read as a throttle for up to the hold instead of 300 s; it shows as `basis=hold` warnings, the banner count and a `backing-off` state.

**An in-call refusal is evidence, not a veto (DW-12).** Only an answer that is *not* a stated refusal disqualifies the call. The two-failure floor counts stated refusals and transport failures together, so `[429, reset]` on a two-attempt client is quota: the call was refused and then cut off. The in-call basis has no window test: the refusal is part of the call it licenses.

**Two-sided means symmetric on the short window (DW-15).** `-W <= d <= W`. A refusal stamped by another row within `W` after this storm began still licenses it (live evidence), later than that it does not.

**Rows are counted in core, not read off a client counter (DW-16).** The banner sentence is about rows, the client counter is about calls and dies with each cycle's client. `run_backfill` already holds the exception in the quota branch; a duck-typed attribute costs one line and gives a number that sums across cycles like `enriched_this_run`.

**No wire change.** `last_run` is written by the `--serve` supervisor from the child's exit code; it never sees a `BackfillResult`. Putting the count there means a new child-to-supervisor channel plus schema, contract and card work. The AC asks for the banner; the count is also on `backfill_cycle_done`, `backfill_terminal` and `backfill_done`.

## Working Rules (implementer)

- Work only in the git worktree `C:\Workfolder\imoveis\.run\wt\1-14` (branch `feat/v0.14-s1.14-transport-quota-inference`). Every read, edit and git command happens there; a shell may start in the primary checkout `C:\Workfolder\imoveis`, so `cd` to the worktree or pass absolute paths. Never touch the primary checkout (its `.venv` interpreter is the only thing used from it) and nothing under `.bmad-loop/`. The worktree has no `.venv`: the interpreter is `C:\Workfolder\imoveis\.venv\Scripts\python.exe`. Git Bash is `'C:/Program Files/Git/bin/bash.exe'` (bare `bash` may be WSL).
- On this host `localhost:6379`, `:5433`, `:8000` and `:5173` are the LIVE primary stack. Never run raw `pytest` outside the isolated environment: use the gate, or for a single unit file the first command under Verification (with `REDIS_URL` unset the guard in `src/tests/redis_isolation.py` refuses every Redis connection; `DATABASE_URL` points at a closed port). Never work around that guard.
- Never call the Gemini/Gemma API or any cloud AI endpoint; every provider response in a test is a fake. Never start a real backfill run and never run `scripts/dev/backfill_gemma.py` against real services (`--status` is read-only and allowed). Never write or delete `backfill:gemma:*` keys on the primary. Never read or edit `.env.local`. Never run docker compose lifecycle commands against project `imoveis`, never run `migrate-primary.sh`, never run `scripts/install-backfill-runner.ps1` in any mode other than `-Mode Status`. Do not start Ollama.
- Do not write `sprint-status.yaml`. Do not edit `deferred-work.md` (the orchestrating session closes the ledger entries after review). Do not commit, merge, push or run `ship.py`: leave the changes in the working tree.
- TDD: each test is written and seen failing before the code that makes it pass. Do not edit an existing test to make it pass unless the Code Map names it; if another existing test fails, report it instead.
- More than 3 files outside the Code Map and the Tasks list means stop and report.

## Verification

**Commands:**
- `env -u REDIS_URL DATABASE_URL=postgresql://x:x@127.0.0.1:1/x PYTHONPATH=src C:/Workfolder/imoveis/.venv/Scripts/python.exe -m pytest src/tests/unit/<file>.py -q -p no:cacheprovider` (Git Bash at `'C:/Program Files/Git/bin/bash.exe'`, from the worktree) -- expected: the edited unit files pass; the only allowed way to run a single file while developing.
- `C:\Workfolder\imoveis\.venv\Scripts\python.exe scripts/agent/validate.py --tier fast --no-extras` (from the worktree; lint + unit, about 2 minutes) -- expected: exit 0. Run by the implementer.
- `C:\Workfolder\imoveis\.venv\Scripts\python.exe scripts/agent/validate.py` (from the worktree, auto tier, 25 to 30 minutes; run by the orchestrating session on the final commit, not by the implementer) -- expected: exit 0. The AI golden suite is reported as skipped when Ollama is down; that is not a pass.
- `C:\Workfolder\imoveis\.venv\Scripts\python.exe scripts/agent/validate.py --only ai` (from the primary checkout once Ollama answers on localhost:11434) -- expected: exit 0 with the golden tests run, not skipped.

## Auto Run Result

Status: awaiting-operator

### Summary

A provider throttle that arrives as resets or timeouts is now recognised in the four situations the ledger named, and the end of a run says how many rows that covered.

- **Turns silent mid-call (DW-12).** A refusal stated inside the call is evidence. `[429, reset, reset, ...]` is an inferred quota refusal (basis `in-call`); the row's attempt is rolled back. Any other answer in the call still makes it a row error.
- **Silent past the window (DW-13).** New knob `ai.gemini_transport_quota_hold_seconds` (7200, ceiling 21600, 0 off). After the 300 s window a storm is still quota (basis `hold`) while the last stated refusal is at most that old and the provider has answered nothing since. An inference never moves the anchor.
- **Cycle boundary (DW-14).** The evidence lives in a process-local `TransportQuotaLicence` that `_run_continuous` creates once and gives to every cycle's client. No Redis key, client lifetime unchanged.
- **Two-sided recency (DW-15).** `-window <= first failure - last stated refusal <= window`.
- **Banner (DW-16).** `run_backfill` records the ids of rows whose refusal was inferred; `--continuous` keeps the set over the run and every terminal banner states its size (also after a single pass, on the wait line and on the log events). Nothing at 0.
- **Story 1.13's count.** Unchanged code: an inferred refusal sets `BackfillResult.quota_exhausted`, a storm not read as quota does not. Both directions now run end to end. The 1.13 regression tests were not edited.
- **Sequencing note.** Stories 3.1 and 3.2 are not started and no SPIKE-1 verdict exists; the advisory re-scope was checked and did not apply.
- **Not on the wire.** `src/api/schemas.py` and `last_run` are untouched (Design Notes).

### Files changed

- `src/adapters/ai/client.py` — `TransportQuotaLicence`, `AITransportQuotaInferredError`, the hold and licence parameters of `GeminiClient`, `_transport_quota_basis`, bookkeeping in `chat_completions`, `create_ai_client`.
- `src/core/backfill_runner.py` — `is_quota_inferred`, `BackfillResult.quota_inferred_ids` / `quota_inferred_rows`, one line in the quota branch.
- `src/infra/config.py`, `configs/app_config.yaml` — `ai.gemini_transport_quota_hold_seconds`; the window comment says "before or after".
- `scripts/dev/backfill_gemma.py` — the run's licence, the hold warning, the inferred line on every ending, the wait-line clause.
- `scripts/dev/ab_gemini_vs_ollama.py` — passes the hold.
- `src/tests/unit/test_ai_quota_propagation.py`, `test_backfill_quota_inferred_rows.py` (new), `test_backfill_gemma_cli.py`, `test_backfill_gemma_completion_cli.py`, `test_ai_client.py`, `test_config.py` — the cases of the matrix, the review cases, config doubles.
- `docs/features/v0.14-s1.14-transport-quota-inference-holds.md` (new), a pointer in the fu8 feature doc.
- `_bmad-output/implementation-artifacts/deferred-work.md` — DW-12 to DW-16 resolved.

Existing tests edited: `test_storm_after_a_stale_throttle_stays_a_hard_error` (a 3600 s old refusal is now inside the hold; restated as hold off, and hold on at 7300 s); two `_build_client` stubs accept keywords; three `MagicMock` configs carry the new float (and `ai.timeout`) as real numbers.

### Review findings

One review pass, four layers, 35 findings (triage log above).

- Patched: 17 entries after grouping, medium 2 (a terminal banner without the count; the count summing one row once per cycle), low 15.
- Deferred: 1 (the A/B harness has no test; frontmatter).
- Rejected: 7. Three low: no `backfill_terminal` event on endings that never had one; counters of a pass that dies on Redis after a lease loss; a hold-licensed storm charged when another row's 429 moves the anchor (concurrency above 1 only, in the feature doc). Four false: the bounded hold against "for as long as it lasts" (DW-13 selects bounded); no licence before any stated refusal (by design); whether a supervised banner reaches the operator (same process, same output); "behaviour widened" (a description).
- Found by the orchestrating session before the review and fixed test-first: a 200 whose body could not be read, after a 429 in the same call, completed an `in-call` storm.

`followup_review_recommended: true`. Two medium entries were patched on a first pass. The risk nobody reviewed independently: the patch round changed runtime behaviour after the reviewers had read the diff, namely (1) the `in-call` basis now needs a live licence, (2) a retried 5xx with a quota body now counts as a stated refusal and bumps `rate_limit_hits`, (3) the row count moved from an integer to a list of ids on `BackfillResult` and a set in `_run_continuous`, (4) the hold warning's threshold.

### Verification

- `validate.py --tier fast --no-extras` on the reviewed tree: exit 0 (lint; unit 3145 passed, 1 skipped).
- The full gate (`validate.py`, auto tier) runs on the commit that contains this text. A commit cannot carry its own gate result: the exit code and the skipped suites are in the session's final report and in the stamp `.run/validated/<tree-sha>.<tier>`.
- AI golden tests: not run. Ollama did not answer on localhost:11434 on 2026-10-09, so the gate skips that suite, and a skip is not a pass (operator action in the frontmatter).
- Fail-without-fix: every test added in the review round that pins a behaviour change was seen failing before the change (the 200-body case, the quota-bodied retry, the revoked in-call basis, the distinct-row count, the three banner endings, the warning thresholds, the wait line). The implementation session reported 39 of 40 mutations of its own branches killed; the survivor is now pinned.
- Read-only check on the primary, 2026-10-09: `install-backfill-runner.ps1 -Mode Status` prints the task as Disabled with `running: false`. No host supervisor runs old code; the next start picks the merged code up.

### Residual risks

- Not observed on a real run. Every provider answer is a fake; a cloud run spends the operator's quota and was not started.
- A real outage that begins right after a stated refusal is read as a throttle for up to the hold (7200 s) instead of 300 s: rows wait instead of failing. Visible as `basis=hold` warnings, on the wait line, in the banner count and as `backing-off`.
- The licence is process-local: a restart during a silent throttle charges rows until the provider states a refusal again.
- With `--concurrency` above 1, a hold-licensed storm can be charged when another row is answered 429 late in that storm (rejected finding, feature doc).
- No migration, no wire change, no API image rebuild needed for behaviour.

### Follow-up review pass (2026-10-09)

A second, independent review of the whole diff (four layers plus the orchestrating session), aimed at what the first pass's patch round changed. 29 findings (triage log). No runtime behaviour of the classifier, the runner or the licence changed in this pass; two operator-facing sentences did.

**Patched: 9 entries, medium 1, low 8.**
- Medium: the documents understated how long the hold can hide a dead route (see "Rulings").
- Low: the wait-line clause ("no 429 on their last attempt"); the exit-10 sentence on the card names the inferred reading and the route; the `last_run` rationale in the feature doc; the fifth-pass arithmetic; five test additions (three wait-line arms, the 200-body veto with a live licence, a refusal in the middle of a storm, mixed shapes after an in-call refusal, both client classes across a cycle) and one config pin (hold ceiling below the daily window).

**Deferred: 1** (the inferred count on the status record and card). **Rejected: 19**, each with its reason in the triage log: 16 low (new surface, concurrency above 1 only, spec edits, or carried from the first pass) and 3 false.

**Rulings.**
- *In-call basis and "a process never told a refusal has no licence".* Both hold. The 429 inside the call is itself the stated refusal: it stamps the licence before the storm is judged, so the first call of a process is covered. "No licence" is a process in which no 429 was ever stated, in or before the call. The licence is "live" when `refused_at` is set, that is, no 200 since the last stated refusal.
- *What ends the hold.* A 200 (clears the licence), a retried or terminal answer that is not a quota refusal (5xx, 4xx), and any answer whose body cannot be read. A new stated refusal starts a new hold.
- *The concurrency gap (hold-licensed storm charged after another row's late 429).* The safe direction: one attempt charged, nothing hidden. Not closed: it needs the licence as it stood at the storm's first failure, and that copy would have to track answers too. Shipped concurrency is 1 and a row's calls are sequential.
- *(a) The hold masks a real egress failure, and for longer than the hold.* A route that dies after a stated refusal and before any other answer is read as that throttle. Four refused passes (45 to 90 minutes) park the run for the rest of the daily window, so exit 9 for a permanent failure comes up to about a day late. Exit 9 stays reachable: with no stated refusal in reach, or past the hold, a storm is a refused result on three rows in a row. The default stays 7200 s (feature doc, "Why the default stays 7200 s"); `0` turns the hold off.
- *(b) Exit 10.* An outage read as quota cannot complete the count of 6 by itself: the sixth cycle is a 24 h window after the fifth and no allowed hold reaches that far. It can supply up to five of the six.
- *(c) `--serve`.* Each run creates its own licence; nothing is carried from one run to the next. Already pinned.
- *Core boundary.* `is_quota_inferred` reads an attribute with `getattr`; no import, no class name, no text match.
- *Restated stale-throttle test.* Still pins the protection, at both new boundaries (hold off at 3600 s; hold on at 7300 s), with `test_the_hold_reaches_exactly_its_bound` on the inclusive edge.
- *Ledger.* DW-12 to DW-16 stay `resolved`. DW-13's remainder is the stated cost of the decision the entry asked for; DW-14's (no licence before any stated refusal) is outside an entry about the cycle boundary; DW-16's (status record) is outside its original text and is in `deferred:`.

`followup_review_recommended: false`. This was a follow-up pass and it patched no high entry.

**Verification.** The edited unit files pass in isolation (87 + the CLI and config files). The new tests that pin code were checked against a mutation of that code (the 200 veto, the two wait-line arms). The full gate runs on the commit that contains this text; its exit code and skipped suites are in the session's final report and the stamp under `.run/validated/`. AI golden tests: still not run (Ollama down); the operator action stays.

**Residual risks added by this pass:** none in code. The masking described under (a) is now documented, not removed.
