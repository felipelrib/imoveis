---
title: 'Story 1.13 — Runner lifecycle ends honestly'
type: 'feature'
created: '2026-10-08'
status: 'done'
baseline_revision: 'be3f616484727c22c37eb80c28a9691a88b902b5'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/docs/features/v0.14-s1.12-backfill-liveness-visible.md'
  - '{project-root}/docs/features/_template.md'
warnings: ['oversized']
deferred:
  - summary: >-
      A stop signal delivered to a runner that has already lost its lease can still write the
      shared stop key, which then stops the run of the successor that holds the lease.
    evidence: |-
      BackfillControl.should_stop (src/core/backfill_runner.py) mirrors a local stop to
      <prefix>:control:stop on its first observation. run_backfill's _may_launch calls
      control.should_stop() at its head and inside the paused loop before _lease_held(), so a
      signal that arrives while this runner is paused and after another runner took the lease
      publishes the key into keys the successor reads. Pre-existing and narrower than before
      Story 1.13: the old signal handler wrote the key at signal time with no lease check at
      all. The launch-loop head and both sync wait loops read lease_lost first and are not
      affected. A fix lets the control skip the mirror write when the caller knows the lease is
      lost, or drops the mirror write and serves the local stop on the status surface another
      way.
    location: >-
      src/core/backfill_runner.py (BackfillControl.should_stop, run_backfill._may_launch)
    severity: low
  - summary: >-
      The main-thread watchdog does not see a run whose event loop still turns while every
      in-flight row waits on a call that never returns.
    evidence: |-
      run_backfill's _pulse_progress task (src/core/backfill_runner.py) stamps progress whenever
      the event loop schedules it, so "progress" means "the main thread ran". A row that awaits
      for ever keeps the loop alive, the launch loop parked on sem.acquire(), and the watchdog
      quiet. Not established that such an await exists: the AI client has a 120 s timeout
      (ai.timeout); reading every await under adapters.queue.tasks.run_enrichment would settle
      it. Counting launch-loop steps instead would end healthy runs, because one slow row
      (three stages, JSON retries, HTTP retries) can honestly take longer than the limit.
    location: >-
      src/core/backfill_runner.py (run_backfill._pulse_progress)
    severity: low (unverified)
  - summary: >-
      The watchdog stops vouching for a hung run but cannot end its process, so a hung
      supervisor stays up with its start button dead until someone restarts the host runner.
    evidence: |-
      After backfill.main_thread_stall_seconds without a stamp, LivenessTicker stops renewing
      the lease and the stall callback stops the supervisor keepalive and records `hung`
      (scripts/dev/backfill_gemma.py, _stall_callback). The process itself is still there: under
      --serve it is the supervisor, so runner_present turns false and start requests are not
      served, and <prefix>:active keeps being beaten if a pass was writing, so
      migrate-primary.sh refuses. The systemd unit (Restart=always) and the Windows host loop
      restart a process that exits, not one that hangs. A hard exit from the watchdog thread
      (os._exit with a code of its own) would let the host restart the supervisor; it was left
      out because it kills a process that may be mid-write on a false positive, which is a
      decision about the runner's contract.
    location: >-
      src/core/backfill_runner.py (LivenessTicker._tick_watchdog), scripts/dev/backfill_gemma.py
      (_stall_callback)
    severity: low
  - summary: >-
      A backfill run that ended in a failure is said only on the Operações card: the Painel
      health strip shows nothing for it and no notification is sent.
    evidence: |-
      HealthStrip (frontend/src/pages/Dashboard.tsx) renders its backfill chip from the
      published state alone, and the state of a run that ended provider_refused, hung, crashed
      or interrupted is idle, the same as a run that never started. Nothing in the runner or
      the supervisor goes through src/adapters/notify. An unattended multi-day run that gave
      up is therefore found only by opening /scraper. Pre-existing: the strip never showed an
      ending, and the intent of Story 1.13 names the status endpoint and the Operações card as
      its surfaces. last_run is on the status payload the strip already reads, so a chip for a
      failed last_run is a small change; whether a failed ending deserves an email is a
      product decision.
    location: >-
      frontend/src/pages/Dashboard.tsx (HealthStrip), scripts/dev/backfill_gemma.py (_serve)
    severity: low
---

<intent-contract>

## Intent

**Problem:** A cloud backfill that cannot proceed does not say so. `--continuous` sleeps forever against a provider that refuses permanently (DW-19); a run requested through the admin API that is refused or dies leaves no trace the API can read (DW-28); a pause expires after 7 days and the run silently spends cloud quota again (DW-23); the SIGINT/SIGTERM handler does blocking Redis I/O and can deadlock the process (DW-22); and since Story 1.12 a run whose main thread hangs reads as alive until it is killed (DW-81).

**Approach:** Give each of these an explicit end or an explicit standing state, and publish it on the surface the operator started the run from: two new exit codes, a `last_run` outcome record written by the `--serve` supervisor and served by `GET /admin/backfill/status` and the Operações card, a pause that stays a pause until an operator resumes it (and says since when), a signal handler that only sets a flag, and a main-thread watchdog in the liveness ticker.

## Boundaries & Constraints

**Always:**
- Work only in the git worktree `C:\Workfolder\imoveis\.run\wt\1-13` (branch `feat/v0.14-s1.13-runner-lifecycle-ends-honestly`). Every read, edit, test and git command happens there; a shell may start elsewhere, so `cd` there first.
- TDD for `src/core/`: the failing test first. Each of the four cases below (and the watchdog) has a regression test that fails without the fix.
- `src/core/backfill_runner.py` imports no adapter (AD-1). One pacer, one lease.
- Wire values are canonical English; pt-BR exists only as a rendered label. New UI strings land in both `en.json` and `pt-BR.json`.
- Tunables live in `configs/app_config.yaml` through `AppConfig` (`BackfillConfig`).
- Exit codes already in use keep their number and meaning: 0, 1, 2, 3, 4, 5, 6, 7 (lease lost), 8, 9.
- Conventional commits; commit everything on the branch; leave the tree clean.

**Never:**
- Never run raw `pytest` or `npx playwright test` against the host's services. `localhost:6379`, `:5433`, `:8000` and `:5173` are the LIVE primary stack. A single unit file is run only with `REDIS_URL` unset and `DATABASE_URL` pointed at a closed port (command under Verification); a single Playwright spec only with `PLAYWRIGHT_PORT` set to a free port in 5200-5299 and EVERY `/api` call mocked. Never work around the Redis guard in `src/tests/redis_isolation.py`.
- Never start a real backfill run, never call the Gemini/Gemma API, never run `scripts/dev/backfill_gemma.py` against real services (`--status` is read-only and allowed), never write or delete `backfill:gemma:*` keys on the primary Redis, never call the primary's `/admin/backfill/*` endpoints with a write method.
- Never run docker compose lifecycle commands against project `imoveis`, never run `migrate-primary.sh`, never run `scripts/install-backfill-runner.ps1` in any mode other than `-Mode Status`, never read or edit `.env.local`.
- Never touch the primary checkout `C:\Workfolder\imoveis` (its `.venv` interpreter is used, nothing else), anything under `.bmad-loop/`, or `_bmad-output/implementation-artifacts/sprint-status.yaml`.
- Never merge, push or run `scripts/agent/ship.py`.
- Do not touch `src/adapters/ai/` (Story 1.14 owns the Gemini client and the transport-quota inference); "the provider refuses" is read from the existing `BackfillResult.quota_exhausted`.
- Do not add a socket timeout to the shared Redis client (DW-10 stays open).
- A signal handler never touches Redis, the liveness ticker or a lock, and does not print.
- The runner never creates an operator request: it may extend the TTL of a pause that exists, never set one.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Provider refuses permanently | `--continuous`; `backfill.max_no_progress_cycles` consecutive cycles end in a provider quota refusal with nothing enriched | Exits 10 before the next sleep with a banner naming the count; final published state `idle`, not `backing-off` | A cycle that enriches a row resets the count; `0` disables the limit (old behaviour) |
| API-requested run ends | `--serve` consumed a start request; the run returns any exit code, raises `SystemExit` (refusal) or raises an exception | `<prefix>:last_run` holds outcome, exit code, reason, `started_at`, `finished_at`; `GET /admin/backfill/status` serves it as `last_run`; the card shows a line for it | Recording is guarded: a Redis error is logged and the supervisor keeps serving. A crash publishes the exception type only, never its text |
| API-requested run killed outright | Record says `started`, the lease is free, and the supervisor key is absent or held by another process id | Status serves `last_run.outcome = "interrupted"` | Derived at read time; nothing is written |
| Pause held past its TTL | Pause requested; a run observes it for longer than the request TTL | The run stays paused and launches nothing until `resume`; status serves `paused_since` and `pause_stale: true`; the card says so | A failed TTL refresh is logged, never fatal |
| Operator resumes | `resume` deletes the pause key while the run refreshes it | The run resumes; the refresh never re-creates the key | — |
| SIGINT / SIGTERM during a run | Signal arrives at any bytecode, including inside a Redis call | Handler sets a flag and restores the default disposition, nothing else; the run observes the flag at its next stop check, drains and exits 6 | Second signal aborts hard (default disposition) |
| Main thread hangs | No progress stamp for `backfill.main_thread_stall_seconds` while a run holds the lease | The ticker stops renewing the lease and publishing state, the supervisor key stops being beaten, `last_run` reads `hung`; if the thread comes back the run launches nothing more and exits 11 | `0` disables the watchdog; a failing stall callback is logged, never raised |

</intent-contract>

## Code Map

Core, `src/core/backfill_runner.py`:
- `_CONTROL_REQUEST_TTL_SECONDS` (:46), `BackfillControl` (:813): `request_pause` (:860) writes `"1"` with `ex=`; `should_stop` (:999) reads Redis; `is_paused` (:996) is `bool(get)`, so any non-empty value works. No outcome record exists.
- `LivenessTicker` (:1040): `tick` (:1345) runs lease, state, heartbeat, keepalives; `_latch` (:1195) makes `lease_lost` true and thereby stops renew and state publish; `stop` (:1446) joins the thread. Its `_latch_lock` and `_io_lock` are not re-entrant.
- `build_status_snapshot` (:1495): the one place Redis state becomes the wire dict. Test doubles for `control` are duck-typed, so new reads use `getattr`.
- `run_backfill` (:2122): `_may_launch` (:2752) is the paused loop (`while control.is_paused()`); the stop decision everywhere is `control.should_stop()`. The renewer task pattern (:2812, cancel + `asyncio.wait` at :2954) is the model for any new background task.

CLI, `scripts/dev/backfill_gemma.py`:
- Exit codes (:178-185) and the docstring table (:71-88). 10 and 11 are free; `scripts/windows/backfill_host.py` (:313) only tests `result == 0` of `--serve`, the systemd unit runs `--serve` with `Restart=always`, the installers use 0/1.
- `_run_continuous` (:1351): `quota_zero_cycles` (:1388, updated :1646-1649) already counts consecutive provider-refused cycles with nothing enriched; `_MAX_QUOTA_BACKOFF_CYCLES = 4` (:198) only lengthens the wait.
- `_sleep_for_reset` (:1153), `_wait_out_migration` (:1238), `_publish_wait_state` (:1127): the sync wait loops; both read `control.should_stop()` every `control_poll_seconds`.
- `_run_supervised` (:1846) returns only an int; `_serve` (:1875) consumes the request (:1952), wraps the run in a keepalive-only `LivenessTicker` (:1988) and prints the exit code.
- `main` (:2028): builds the ticker at :2292, installs signals at :2299; the continuous branch computes `quota_backoff` at :2326; the exit `finally` at :2368.
- `_install_stop_signals` (:2528): the handler calls `control.request_stop()` and `print` (DW-22). `_STOP_SIGNAL_RECEIVED` (:192) is read by `_serve` (:1998).
- `_print_status` (:565): the `--status` print-out.

Config: `src/infra/config.py` `BackfillConfig` (:126), `configs/app_config.yaml` `backfill:` (:342).

API: `src/api/schemas.py` `BackfillStatusResponse` (:360); `src/api/admin.py` `_backfill_snapshot` (:712) validates the core dict; `docs/api.md` (:323).

Frontend: `frontend/src/api.ts` `BackfillStatus` (:351); `frontend/src/components/operations/BackfillCard.tsx` and `lines.ts`; `frontend/src/i18n/locales/{en,pt-BR}.json` `operations.*`; `frontend/src/i18n/format.ts` `formatDateTime`; CSS classes `.ops-line`, `.ops-fail`, `.ops-pending` in `frontend/src/index.css` (:1384-1425) already use Meia-noite tokens, no new CSS is needed.

Tests to extend: `src/tests/unit/test_backfill_control.py` (`FakeRedis` :49, real control runs :871), `test_backfill_liveness_ticker.py` (`_Clock`, `_kit`, `_backfill`), `test_backfill_start_request.py` (`_snapshot` :367), `test_backfill_gemma_cli.py` (`_wire` :89 builds a `MagicMock` config: every new numeric config field MUST be set there as a real number, `int(MagicMock())` is 1; `_serve_args` :1842; signal test :2190), `test_backfill_gemma_completion_cli.py` (its own config wiring), `test_windows_backfill_host.py` (:185 calls `_install_stop_signals(control)` and then polls the same plain `control.should_stop()`: it must keep working), `test_admin_backfill_api.py`, `src/tests/contract/test_api_contract.py` (:956), `src/tests/unit/test_i18n_catalog_parity.py` (parity and One/Many pairing run on the catalogs), `frontend/tests/e2e/backfill-card.spec.js` with `helpers/apiMocks.js` (`BACKFILL_STATUS_IDLE` :242, `mockAdminBackfill` :338).

Ledger: `_bmad-output/implementation-artifacts/deferred-work.md` DW-19 (:151), DW-22 (:174), DW-23 (:181), DW-28 (:218), DW-81 (:789).

## Tasks & Acceptance

**Execution:**
- `src/infra/config.py`, `configs/app_config.yaml` -- add `backfill.max_no_progress_cycles` (int, default 6, `ge=0`, 0 disables) and `backfill.main_thread_stall_seconds` (int, default 3600, 0 disables, otherwise at least 900 enforced by a validator), each with a comment that states what it bounds -- config-owned limits.
- `src/core/backfill_runner.py` (`BackfillControl`) -- test first. Pause: `request_pause` stores the request time (ISO, `now_fn`) with `SET NX EX`; when a pause already exists it only re-arms the TTL, keeping the first stamp. Add `hold_pause()` (EXPIRE on the existing key, returns whether it exists, never creates), `paused_since()` (datetime or None for absent / legacy `"1"`), `request_ttl_seconds`. Local stop: `watch_local_stop(flag)`; `should_stop()` returns True without a Redis read when the flag is true, and on the first such observation makes one guarded `request_stop()` so the API still shows a pending stop. Outcome: `record_run_start(source, owner)`, `record_run_end(outcome, *, exit_code, reason, source, owner)`, `last_run()` on `<prefix>:last_run` (JSON, TTL 30 days, reason cut to 500 chars, tolerant decode); an end keeps the `started_at` of the start it closes -- DW-23, DW-22, DW-28.
- `src/core/backfill_runner.py` (`LivenessTicker`) -- test first. `stall_limit_seconds`, `on_stall`, `note_progress()` (one assignment, no lock, no I/O), `stalled`, `progress_interval`, `silence()` (set the stop flag without joining). The watchdog check runs first in `tick()`; a stall latches the lease as lost with its own reason, stops keepalives of that ticker, logs once, and calls `on_stall(seconds_silent)` guarded. `:active` keeps the lease-loss rule (still beaten while a pass is writing) -- DW-81.
- `src/core/backfill_runner.py` (`run_backfill`, `build_status_snapshot`) -- test first. In the paused loop call `hold_pause` each poll when the control has it (guarded, logged). When the ticker has a positive `progress_interval`, run a pulse task that calls `note_progress()` on that interval with real `asyncio.sleep`, cancelled like the renewer. The snapshot gains `last_run` (no `owner` on the wire; `interrupted` derived as in the matrix), `paused_since`, `pause_stale` (age at or past the request TTL) -- status surface.
- `scripts/dev/backfill_gemma.py` -- `EXIT_PROVIDER_REFUSED = 10`, `EXIT_MAIN_THREAD_STALLED = 11`, docstring table, one exit-code to outcome-word map covering every `EXIT_*`. `_run_continuous` exits 10 when `quota_zero_cycles` reaches the limit (before sleeping). Signal handler sets only `_STOP_SIGNAL_RECEIVED` and restores `SIG_DFL`; `_install_stop_signals` registers the flag with `control.watch_local_stop`, and the drain message is printed once from the main thread when the flag is first observed. `main` builds the ticker with the stall limit and a callback that silences the supervisor keepalive and records `hung`; stamps progress in `_run` (start, after the candidate fetch, after partition), `_run_continuous` (cycle start, around the census) and each wait-loop step; maps a stalled run to exit 11 with a banner; publishes `idle`, not `backing-off`, after exit 10. `_serve` records the start after consuming, runs through a helper that returns exit code, outcome and reason, records the end (guarded), and says it will not relaunch on its own after exit 10. `_publish_wait_state` holds the pause. `--status` prints `last run` and `paused since` lines -- the four cases.
- `src/api/schemas.py`, `src/api/admin.py`, `docs/api.md` -- `BackfillLastRunModel` (`outcome`, `exit_code`, `reason`, `started_at`, `finished_at`, `source`) and `last_run`, `paused_since`, `pause_stale` on `BackfillStatusResponse`, all optional or defaulted; document the outcome vocabulary -- wire change.
- `src/tests/unit/`, `src/tests/contract/test_api_contract.py` -- regression tests named for each matrix row; fixtures updated for the new config fields; contract test that a recorded outcome and a stale pause come back on `/admin/backfill/status` matching the model -- AC "each case has a regression test".
- `frontend/src/api.ts`, `frontend/src/components/operations/{BackfillCard.tsx,lines.ts}`, `frontend/src/i18n/locales/{en,pt-BR}.json` -- types; a last-run line (hidden while a run is active or the outcome is `started`; `.ops-fail` for outcomes that need the operator, `.ops-line` otherwise; date and time through `formatDateTime`; the runner's `reason` on its own line when present; an unknown outcome word is shown verbatim); a "paused since" line and a stale-pause line while a run is paused. No count is interpolated into a noun -- Operações card.
- `frontend/tests/e2e/backfill-card.spec.js`, `frontend/tests/e2e/helpers/apiMocks.js` -- cases: a provider-refused last run with its reason; no last-run line while a run is active; a stale pause. Every `/api` call mocked -- e2e.
- `docs/features/v0.14-s1.13-runner-lifecycle-ends-honestly.md` -- from the template, all sections, with the full exit-code table (code, meaning, what a supervisor should do) and the outcome vocabulary -- feature doc.
- `_bmad-output/implementation-artifacts/deferred-work.md` -- DW-19, DW-22, DW-23, DW-28 and DW-81 get `status: resolved` plus a `resolution:` line only for what the code resolves; done by the orchestrating session after review, not by the implementer -- ledger.

**Acceptance Criteria:**
- Given a provider that refuses every pass, when `--continuous` has run `max_no_progress_cycles` such cycles, then the process exits 10 and `_serve` records `provider_refused` and waits for the next operator request.
- Given a start request consumed by `--serve`, when the run is refused, crashes or ends with any code, then `GET /admin/backfill/status` returns `last_run` with the outcome and reason, and the Operações card shows it in pt-BR and en.
- Given a pause observed by a run, when more than the request TTL passes without a resume, then no row is launched, and the status endpoint and the card say the pause is stale and still in force.
- Given the stop handler installed, when it is invoked, then no Redis call is made and nothing is printed from the handler, and the run still stops and exits 6.
- Given a run holding the lease, when no progress stamp arrives for `main_thread_stall_seconds`, then the lease is no longer renewed, the supervisor key is no longer beaten and `last_run` reads `hung`.
- Given the feature doc, when read, then it lists every exit code with its meaning.

## Spec Change Log

## Review Triage Log

### 2026-10-08 — Review pass
- verdicts: 41 findings — high 0, medium 8, low 25, false 7, maybe-false 1
- findings:
  - `[low]` `[patch]` blind-hunter: a run hung inside a pass keeps `:active` beaten, so `migrate-primary.sh` stays blocked, and the docs say the run "reads as gone" — true and deliberate (rows in flight may still write when the thread wakes; the exclusion is never traded away). Patched: stated in the feature doc Notes and in the recorded `hung` reason.
  - `[medium]` `[patch]` blind-hunter: a `hung` record never resolves when the process is killed or the run was started by hand — real: only `_serve` wrote an end. Patched: the reason is worded so it stays true afterwards, and `main` closes the record of a hand-started run that comes back (exit 11).
  - `[low]` `[patch]` blind-hunter: `hung` carries `finished_at` while the run is open — real, harmless. Patched: schema docstring and docs/api.md say `finished_at` is when the watchdog gave the run up.
  - `[low]` `[reject]` blind-hunter: a stall callback blocked in Redis for longer than the 5 s join can overwrite the real ending — real but needs a Redis stall inside that window at the moment a hung thread returns; the fix is a conditional write (new parameter). Not worth the surface.
  - `[low]` `[patch]` blind-hunter: `max_no_progress_cycles` of 1 to 4 ends a run during the 15-minute back-offs — true by arithmetic, the operator's choice. Patched: the config comments say so. The key name stays (the AC's words).
  - `[low]` `[patch]` blind-hunter: exit 10 says "check the provider quota" on a classification that includes string markers — true; the classification is the existing one and Story 1.14 owns it. Patched: feature doc Notes.
  - `[low]` `[patch]` blind-hunter: the 900 s floor contradicts the "1800 s honest gap" rationale, and the stated bound omits the cadence and the lease TTL — the comments were wrong, the floor is a choice. Patched: comments state the risk under 1800 and the real bound.
  - `[medium]` `[patch]` blind-hunter: `_run_supervised` labels every `SystemExit` `refused` — real: an int code was mislabelled and the generic reason claimed "before it started". Patched: int/None codes map through the exit table; a crash reason names the log.
  - `[low]` `[patch]` blind-hunter: the outcome vocabulary is hand-kept in six places with one pin — real. Patched: a unit test ties every outcome word to both catalogs.
  - `[medium]` `[patch]` blind-hunter: the acceptance says pt-BR and en, the e2e renders pt-BR only and four outcomes are never rendered — real gap. Patched: an `en` case with `refused` and `interrupted`; a `hung` case.
  - `[low]` `[patch]` blind-hunter: the stale-pause text asserts a holder nobody checked — real for a re-armed pause or one a dead run held. Patched: CLI line, schema comment and docs say only "older than the request TTL and still set".
  - `[low]` `[patch]` blind-hunter: `_install_stop_signals` silently disarms the stop for a control without `watch_local_stop` — real for doubles only, but the guard hides a wiring error. Patched: called unconditionally.
  - `[low]` `[patch]` blind-hunter: the only real-signal test of the changed path is skipped in a linked worktree — true (DW-42). Action: run from a standalone clone by the orchestrating session; result under Auto Run Result.
  - `[low]` `[patch]` blind-hunter: older docs left stale; the spec lists `src/api/admin.py`, absent from the diff — the two doc lines are patched (1.12 note, the s1.3 BUG line gets a pointer). The spec part is rejected (a finding whose fix is to edit this spec; `admin.py` needed no change because it validates the core dict through the model). The systemd advice stays in the feature doc: the shipped unit runs `--serve`.
  - `[low]` `[reject]` edge-case: a hung supervisor returning after a second supervisor wrote `started` overwrites that record — needs two supervisors on one prefix (unsupported, the installer says so) plus a hang; the fix adds a branch.
  - `[low]` `[reject]` edge-case: late stall callback overwrites the ending — same as the blind-hunter row above; same reason.
  - `[low]` `[reject]` edge-case: a failed `record_run_start` lets the end borrow an older open record's `started_at` — needs a Redis blip at launch and a stale open record of the same pid; the fix adds a parameter.
  - `[low]` `[defer]` edge-case: a signal while paused, after the lease was lost, publishes the stop key into the successor's keys — pre-existing and narrower now: the old handler wrote the key at signal time without any lease check. Deferred.
  - `[low]` `[patch]` edge-case: `print` in `_local_stop_requested` can raise out of `should_stop()` — real on a closed stream. Patched: guarded.
  - `[medium]` `[patch]` edge-case: a zero-progress cycle that ends on the local budget resets the refusal count, so exit 10 may never be reached — real, and against the matrix row ("a cycle that enriches a row resets the count"). Patched: only `processed > 0` resets; test added.
  - `[maybe-false]` `[defer]` edge-case: the pulse keeps stamping while every in-flight row awaits a call that never returns — the event loop is then alive, which is not the defect DW-81 names (a main thread that hangs). Whether any await in a row is unbounded is not established (the AI client has a 120 s timeout); reading every await under `run_enrichment` would settle it. Deferred as low (unverified).
  - `[low]` `[patch]` edge-case: a migration holding its lock longer than the stall limit reads as a hang — true for limits under the migration's duration; grouped with the floor comment above. No lock timeout added (not this story).
  - `[low]` `[reject]` edge-case: a pause written as `1` by the old code never gets a time when requested again — transitional only; `backfill:gemma:control:pause` does not exist on the primary (read 2026-10-08), so no such pause is in flight.
  - `[low]` `[patch]` edge-case: `--status` and the API report a run holding a pause nobody holds — same as the stale-pause row above; patched there.
  - `[low]` `[reject]` edge-case: the supervisor key is read twice in one snapshot, so one poll can say `runner_present` and `interrupted` together — a window of milliseconds around the key's expiry, corrected on the next poll.
  - `[false]` `[reject]` edge-case: `supervisor_heartbeat=None` with a `started` record reads `interrupted` — the parameter is required and both callers (admin API, `--status`) pass a heartbeat.
  - `[low]` `[patch]` edge-case: a `SystemExit` raised after the lease was taken is recorded as refused "before it started" — grouped with the `_run_supervised` row; the label now reads "refused by the runner".
  - `[medium]` `[patch]` edge-case: a hand-started run that stalls and exits 11 leaves `hung` with a null exit code — grouped with the `hung` row above; patched there.
  - `[low]` `[reject]` edge-case (claim): a pause written as `1` and held for weeks is never reported stale — true for a legacy value only; none exists on the primary (same read as above), and the runner must not rewrite an operator request.
  - `[medium]` `[patch]` verification-gap: no test asserts the stamp in `_wait_out_migration` — filed gap. Patched: test added.
  - `[low]` `[patch]` verification-gap: the failure styling is pinned for two outcome words — filed gap. Patched: class assertions for the unknown word and `stopped`.
  - `[low]` `[patch]` verification-gap: the "no pause line for a dead runner" guard is unobservable — filed gap. Patched: e2e case with `active: false`.
  - `[medium]` `[patch]` verification-gap (other): hand-started stalled run leaves a stale `hung` record — grouped with the `hung` rows; patched there.
  - `[low]` `[patch]` verification-gap (other): `test_the_budget_sleep_holds_a_pause_it_can_see` returns before the hold — true. Patched: the test drives the loop.
  - `[false]` `[reject]` intent-alignment (a): exit 10 is absorbed by `--serve`, so no shipped supervisor sees the process code — the shipped supervisor is `--serve`, which starts a run only on an operator's start request and so cannot restart one blindly; it records `provider_refused` and says so. A hand-run `--continuous` exits 10 as a process.
  - `[false]` `[reject]` intent-alignment (b): "no progress" counts quota-classified refusals only — the AC's precondition is "the provider refuses permanently"; other zero-progress cycles already end as exit 3. The seam for Story 1.14 is `BackfillResult.quota_exhausted`.
  - `[medium]` `[patch]` intent-alignment (c): the last-run line is hidden while the lease is held, so `hung` does not show for up to 900 s; no `en` rendering — patched (shown for `hung` while active; `en` e2e case). The English `reason` on the pt-BR card is deliberate, as the 409 detail is.
  - `[false]` `[reject]` intent-alignment (d): the pause hold exists only while a run observes it; ADR 0006 is not cited — an unobserved pause cannot turn into spend (the next start discards it and says so). ADR 0006 was read: it does not mention pauses; its rule that recovery is unattended is why a pause does not end the run. Now in the feature doc.
  - `[false]` `[reject]` intent-alignment (e): the handler test calls the handler directly — that is the surface DW-22 names (what the handler does); real delivery is the harness test, see the blind-hunter row.
  - `[false]` `[reject]` intent-alignment (f): the watchdog reads "the main thread ran", not "the launch loop made a call" — the defect is "a run whose main thread hangs for good"; a launch loop waiting on a slow row is not a hang, and counting it would end healthy runs. The lockout bound is now stated in the config comments.
  - `[false]` `[reject]` intent-alignment (g): the tree was uncommitted and five ledger entries are planned — the review runs before the commit; DW-81 is the watchdog the intent put in scope.

### 2026-10-09 — Review pass (follow-up)
- verdicts: 41 findings — high 0, medium 2, low 32, false 7, maybe-false 0
- findings:
  - `[low]` `[patch]` blind-hunter: a `hung` record is shown over whatever run is active next — real: the record lives 30 days, a run started by hand writes none, and the card showed `hung` whenever a run was active. Patched: `hungRunHoldsTheLease` (lines.ts) shows it during an active run only when `finished_at` is not before the lease's `acquired_at`; e2e case "an old hung record is not painted over a later run".
  - `[low]` `[reject]` blind-hunter: `record_run_end` overwrites another process's open record, and the watchdog can still fire after a takeover latched the loss — carried: same claim as the first pass's "a hung supervisor returning after a second supervisor wrote `started`" row, code unchanged; it needs a hung process that wakes after a successor started. The watchdog half is true and harmless: that process is hung, and `hung` is what its record should say.
  - `[low]` `[reject]` blind-hunter: an end record whose single write fails leaves `started` for as long as the supervisor lives — real, needs a Redis error on exactly that write while the run itself just used Redis; the fix is retry state in the poll loop. The card hides `started`, so the visible result is "no line", and the next run overwrites it.
  - `[false]` `[reject]` blind-hunter: cycles 5 and 6 can be 15 minutes apart when no local window is open, so a healthy provider gets exit 10 in 75 to 90 minutes — a refused pass reserves budget before the provider call (`try_consume` in the launch loop, ahead of `_worker`), which opens a window, and `settle` never deletes one, so after the fourth refusal every wait is the rest of a window and then a whole one. Walked with the real `DailyBudget` and locked by `test_the_fifth_and_sixth_refusal_are_a_daily_window_apart`; the reasoning is now in the code comment, the feature doc and the DW-19 resolution.
  - `[low]` `[patch]` blind-hunter: "consecutive" / "in a row" is not exactly what the counter means, and the back-off ladder (`throttle_ruled_out`) changed with it — true since the first pass's reset rule. Patched: the feature doc and docs/api.md say "with no row enriched in between" and name the ladder; the banner keeps its wording, explained there.
  - `[low]` `[reject]` blind-hunter: a signal during a blocking stretch is not acknowledged until the next stop check — true and chosen: the intent forbids a handler that prints, and an acknowledgement from another thread is new surface. The wait is at most `control_poll_seconds` in a wait loop. The feature doc now says when the message appears and what a second signal leaves behind.
  - `[low]` `[patch]` blind-hunter: `test_native_process_stop_drains_and_clears_real_heartbeat` was not run — the test does run in a linked worktree (it builds its own checkout; only three other test functions carry the skip) and passed here, 3 modes; what was wrong is the feature doc saying it is skipped. Patched: the note.
  - `[low]` `[defer]` blind-hunter: a failed ending is visible only on the Operações card (the Painel strip shows nothing, no notification) — true and pre-existing; the intent names the status endpoint and that card. Deferred.
  - `[low]` `[patch]` blind-hunter: docs/api.md gives `refused` an exit code of "1 or 2" and does not document `source` or the hand-started `hung` — real. Patched.
  - `[low]` `[patch]` blind-hunter: two docstrings say a stale pause means a run is holding it — real (`request_ttl_seconds`, `build_status_snapshot`). Patched.
  - `[low]` `[patch]` blind-hunter: the edited note in the s1.12 feature doc contradicts itself — real. Patched.
  - `[low]` `[patch]` blind-hunter: the feature doc is stale against its own diff (ledger sentence, files table, the s1.3 note marks only DW-23) — real. Patched.
  - `[low]` `[patch]` blind-hunter: the pt-BR `lease_lost` label asserts a takeover the English one does not; no unit tests for the `lines.ts` helpers or the last `SET` of `request_pause` — the label is patched ("perdeu a vez de execução"). The helpers are asserted through the e2e cases (label, class, verbatim word), which is how this repo tests the card; the final `SET` needs a key that expires twice between three commands.
  - `[medium]` `[patch]` edge-case: a cycle that enriched rows and ended with budget to spare skips the reset (`continue` before it), so refusals on either side add up — real, and against the matrix row "a cycle that enriches a row resets the count"; the costly direction (a false exit 10). Patched: the reset runs for every cycle with `processed > 0`, ahead of the branches; `test_a_cycle_that_enriches_rows_with_budget_to_spare_resets_the_refusal_count` fails without it.
  - `[low]` `[reject]` edge-case: `record_run_end` from a stalled or displaced process replaces another owner's `started` — carried: same claim and code as the first pass's row; needs two supervisors on one prefix or a hang that ends after a successor started.
  - `[low]` `[reject]` edge-case: the stall callback's write lands after the main thread's end record — carried: the first pass's "late stall callback overwrites the ending" row, code unchanged.
  - `[low]` `[reject]` edge-case: a hand-started run that stalls and then raises leaves `hung` with a null exit code — true; the reason says "if the process still exists it has to be ended by hand", which stays correct, and closing it needs a write in `main`'s `finally` for a state reached by a hang followed by a non-Redis exception.
  - `[low]` `[reject]` edge-case: the one `record_run_end("hung")` of the callback is not retried — true. When Redis is why the thread hangs, the ticker thread blocks in the same Redis (no socket timeout, DW-10) and a retry changes nothing; the record then reads `interrupted` once the lease lapses, which still says the run is not going.
  - `[low]` `[reject]` edge-case: the supervisor's end-record write is tried once — same as the blind-hunter row above; same reason.
  - `[low]` `[reject]` edge-case: a `started` record stays `started` while a different owner holds the lease — true for at most one lease TTL after a kill, or for as long as a hand-started successor runs; the card hides `started` and shows the active run, so nothing false is displayed.
  - `[low]` `[patch]` edge-case: an old `hung` record while a later hand-started run is active — same root cause as the first blind-hunter row; patched there.
  - `[low]` `[patch]` edge-case: a host suspended for longer than the stall limit is recorded as `hung` when the ticker ticks before the main thread stamps — real on Windows, where the monotonic clock counts through a suspend. Patched: the ticker loop takes a wait that returned 60 s or more late off the silence (`_discount_frozen_wait`); silence from before the freeze still counts. Two tests, one of them failing without the fix. The run still ends (exit 7): the lease TTL passed.
  - `[low]` `[reject]` edge-case: the watchdog fires after a takeover already latched the loss — true; the process is hung either way and silencing the supervisor key is right for it. Same group as the second blind-hunter row.
  - `[false]` `[reject]` edge-case (claim): the spec says the last-run line is hidden while a run is active, and `hung` is rendered then — the first pass changed that on purpose (triage row "intent-alignment (c)"); a finding whose fix is to edit this spec.
  - `[low]` `[reject]` edge-case (claim): "last_run reads hung" does not hold when the write fails — same as the retry row above; same reason.
  - `[medium]` `[patch]` verification-gap: a stall that surfaces in a `--continuous` wait loop could go back to exit 7 unnoticed (four `_lease_lost_exit` call sites untested) — filed gap. Patched: `test_a_stall_found_in_a_continuous_wait_exits_eleven_not_seven`, for the budget sleep and the migration wait.
  - `[low]` `[patch]` verification-gap: a hand-started `--continuous` run that stalls is not verified to close its record — filed gap. Patched: `test_a_hand_started_continuous_run_that_stalls_closes_its_own_record`.
  - `[low]` `[patch]` verification-gap (other): a stale `hung` record over a healthy hand-started run — same root cause as the first blind-hunter row; patched there.
  - `[low]` `[patch]` verification-gap (other): the feature doc's claim that the native stop test is skipped does not match the test file — confirmed by running the file (9 passed, 8 skipped, none of the 8 that test). Patched: the note.
  - `[false]` `[reject]` intent-alignment: every row is exercised per component with fakes, never as a real process, signal or seven-day pause — the intent's own Never list forbids a real run, a real provider call and signals to processes this session did not start; the wire is covered by the contract test and the card by the e2e, and the one real-signal path (the host stop) ran.
  - `[false]` `[reject]` intent-alignment: the runner now writes the stop key, against "never creates an operator request" — the sentence continues "it may extend the TTL of a pause that exists, never set one"; the stop is the operator's own signal, the handler wrote the same key before, and the write is now on the main thread, guarded.
  - `[low]` `[patch]` intent-alignment: "consecutive" is loosened — same as the blind-hunter wording row; patched there.
  - `[low]` `[reject]` intent-alignment: `pause_stale` is age-based, not held-based — carried: the first pass's stale-pause rows; the wire docs say exactly that, and this pass corrected the two docstrings that still said otherwise.
  - `[false]` `[reject]` intent-alignment: `last_run` has a second writer (the stall callback, also for a run started by hand) — the matrix row "Main thread hangs" asks for `last_run` to read `hung`, and only the run's own watchdog can know.
  - `[low]` `[reject]` intent-alignment: `hung` carries `finished_at` while the process may still exist — carried: first pass, documented in the schema and docs/api.md.
  - `[low]` `[reject]` intent-alignment: the last-run line is conditional (nothing is shown for a `lease_held` ending while the other run is active) — by design: the card is then about the run that holds the lease, and the line appears when that run ends.
  - `[low]` `[reject]` intent-alignment: "stops reading as alive" is partial (`:active` for a run hung inside a pass, about 90 minutes to detect) — carried: first pass; said in the `hung` reason and the config comments, and the unbounded part is deferred item 3.
  - `[low]` `[reject]` intent-alignment: a refusal's text goes on the wire and `reason` is English on the pt-BR card — carried: first pass. Checked again: every `SystemExit` message in the runner names flags and config keys, none carries a value from the environment. The outcome word is the localized message; the reason is diagnostic detail, as a 409 detail is.
  - `[false]` `[reject]` intent-alignment: `max_no_progress_cycles` counts only quota-refused cycles — carried: first pass, intent-alignment (b).
  - `[low]` `[patch]` intent-alignment: docs/api.md says "1 or 2" for `refused`, and the feature doc says the ledger is updated later — same as the blind-hunter doc rows; patched there.
  - `[false]` `[reject]` intent-alignment: the diff adds things the intent does not ask for (`--status` lines, names for exit 1 and 2, the 900 s floor, reason truncation, the 30-day TTL) — each is in the spec's task list or bounds a record the intent asks for; none changes a code already in use.

## Design Notes

**Sequencing note checked.** Stories 3.1 (SPIKE-1) and 3.2 are not started and no Strata verdict exists, so the advisory re-scope did not apply: the full scope is done.

**Why the pause stays (DW-23).** The ledger named two options: the paused loop refreshes the key, or expiry ends the run. Ending a multi-day run because nobody resumed it costs a restart and loses nothing a pause does not also hold. The refresh is an `EXPIRE` on a key that exists, so the runner extends an operator request and never creates one; a resume deletes the key and the refresh is then a no-op. `pause_stale` is the same 7-day figure, used as "this pause is older than a request normally lives". A pause with no run observing it still expires, which costs nothing: the next start discards stale requests and says so.

**Why cycles, and why 6.** `quota_zero_cycles` already counts the condition DW-19 describes and resets on any enriched row. With the shipped values: four refused passes 15 minutes apart, then a wait for the daily window, a fifth refused pass, a second window, a sixth refused pass, exit 10. Two daily windows refused is not a throttle. The `--serve` supervisor never relaunches on its own (a run needs a new start request), so "act on it" there is recording the outcome and saying so; an operator who runs `--continuous` under their own supervisor uses the code (for systemd: `RestartPreventExitStatus=9 10 11`).

**Watchdog meaning.** "Progress" is "the main thread ran": a pulse on the event loop inside a pass, explicit stamps around the blocking stretches outside it. The longest honest gap is one database statement blocked by a migration (`migration_wait_seconds` and the migration lock are both 1800 s), hence the 3600 s default and the 900 s floor. The ticker cannot end a hung process; it stops vouching for it. A stall is treated as a lease loss for every key (not renewed, state not published), so a main thread that wakes up launches nothing and exits 11.

**`interrupted` is derived, not written.** The supervisor and the run it drives are one process, and the supervisor beats its key with its `host:pid`. A `started` record whose owner is not the current supervisor id, with the lease free, is a run whose process is gone. While the same supervisor is alive the record stays `started` for the milliseconds between the lease release and the end record, so the card never flickers.

## Verification

**Commands:**
- `env -u REDIS_URL DATABASE_URL=postgresql://x:x@127.0.0.1:1/x PYTHONPATH=src C:/Workfolder/imoveis/.venv/Scripts/python.exe -m pytest src/tests/unit/<file>.py -q -p no:cacheprovider` (Git Bash at `'C:/Program Files/Git/bin/bash.exe'`, from the worktree) -- expected: the edited unit files pass; this is the only allowed way to run a single file while developing.
- `C:\Workfolder\imoveis\.venv\Scripts\python.exe scripts/agent/validate.py --tier fast` (from the worktree) -- expected: exit 0 (lint + unit).
- `C:\Workfolder\imoveis\.venv\Scripts\python.exe scripts/agent/validate.py` (from the worktree, auto tier: full + harness, 35 to 45 minutes; run by the orchestrating session on the final commit) -- expected: exit 0.

## Auto Run Result

Status: done

### Summary

A cloud backfill that cannot proceed now ends, or stands still, in a named way, and the name is on the status endpoint and the Operações card.

- **Provider refuses permanently (DW-19).** `--continuous` exits 10 after `backfill.max_no_progress_cycles` (default 6) consecutive cycles that end in a provider quota refusal with nothing enriched, before the next sleep. Only a cycle that enriches a row resets the count.
- **Outcome of an API-requested run (DW-28).** The `--serve` supervisor writes `<prefix>:last_run` at launch and at the end. `GET /admin/backfill/status` serves it as `last_run`; the card shows the outcome and the runner's reason. `interrupted` is derived at read time.
- **Pause past its TTL (DW-23).** Decision: the pause stays in force. A run that observes a pause extends its TTL (an `EXPIRE`, never a `SET`); status serves `paused_since` and `pause_stale`.
- **Signal handler (DW-22).** The handler sets one flag and restores the default disposition. The run reads the flag at its stop checks.
- **Main-thread watchdog (DW-81).** After `backfill.main_thread_stall_seconds` (default 3600) without a progress stamp the ticker stops renewing and publishing, the supervisor key stops being beaten and `last_run` reads `hung`. A thread that comes back exits 11.
- **Sequencing note.** Stories 3.1 and 3.2 are not started and no SPIKE-1 verdict exists; the advisory re-scope was checked and did not apply.

### Files changed

- `src/core/backfill_runner.py` — pause stamp and `hold_pause`, local stop flag, `last_run` record, watchdog in `LivenessTicker`, pulse task and pause hold in `run_backfill`, three new snapshot fields.
- `scripts/dev/backfill_gemma.py` — exit codes 10 and 11, the exit-code to outcome map, the refusal limit, flag-only signal handler, watchdog wiring, outcome recording in `_serve`, `--status` lines.
- `src/infra/config.py`, `configs/app_config.yaml` — `max_no_progress_cycles`, `main_thread_stall_seconds`.
- `src/api/schemas.py`, `docs/api.md` — `BackfillLastRunModel`, `last_run`, `paused_since`, `pause_stale`.
- `frontend/src/api.ts`, `frontend/src/components/operations/BackfillCard.tsx`, `lines.ts`, `frontend/src/i18n/locales/en.json`, `pt-BR.json` — last-run line, paused-since and stale-pause lines.
- `frontend/tests/e2e/backfill-card.spec.js`, `helpers/apiMocks.js` — nine new cases, every call mocked.
- `src/tests/unit/test_backfill_control.py`, `test_backfill_liveness_ticker.py`, `test_backfill_start_request.py`, `test_backfill_gemma_cli.py`, `test_backfill_gemma_completion_cli.py`, `test_admin_backfill_api.py`, `test_config.py`, `src/tests/contract/test_api_contract.py` — regression tests for the four cases and the watchdog.
- `docs/features/v0.14-s1.13-runner-lifecycle-ends-honestly.md` — feature doc with the full exit-code table; pointers added in the s1.12 and s1.3 feature docs.
- `_bmad-output/implementation-artifacts/deferred-work.md` — DW-19, DW-22, DW-23, DW-28, DW-81 resolved.

### Review findings

One review pass, four layers, 41 findings (see the triage log): 25 rows patched (15 changes sent to the implementation session), 2 deferred (in frontmatter, plus one residual risk of the design recorded there by this session), 14 rejected with their reasons in the log. No intent gap and no spec loopback.

Patched entries by verdict, after grouping: medium 6 (the `hung` record that never closed, `SystemExit` mislabelled as `refused`, the refusal count reset by a non-refused zero-progress cycle, `hung` hidden while the dead lease was held, the missing `en` rendering in the e2e, the missing `_wait_out_migration` stamp test), low 9.

`followup_review_recommended: true`. Two or more medium entries were patched on a first pass. The risk that was not reviewed independently: the patch round changed runtime behaviour after the review layers had read the diff, namely the reset rule of `quota_zero_cycles` (it also feeds the existing back-off escalation, `throttle_ruled_out`), the end record `main` now writes for a hand-started stalled run, and the outcome mapping of an int `SystemExit` in `_run_supervised`.

### Verification

- `validate.py --tier fast` on the pre-review tree: exit 0 (lint, unit).
- The full gate (`validate.py`, auto tier) is run on the commit that contains this text. A commit cannot carry its own gate result: the exit code and the e2e count are in the session's final report and in the validation stamp `.run/validated/<tree-sha>.<tier>`.
- `test_windows_backfill_host.py -k "native_process_stop or active"` (the real-signal host stop, skipped in a linked worktree, DW-42): run from a standalone clone of commit 6dcd191f with `REDIS_URL` unset, 3 passed. It drives the Windows host stop through the flag-only handler with fakes only.
- Fail-without-fix: with the baseline `backfill_runner.py` and `backfill_gemma.py` restored, the new core, snapshot and CLI tests fail (reported by the implementation session).
- Read-only checks on the primary, 2026-10-08: `backfill:gemma:control:pause`, `backfill:gemma:lease` and `backfill:gemma:supervisor:active` do not exist; `install-backfill-runner.ps1 -Mode Status` prints the task as Disabled with `running: false`. No host supervisor runs old code, so there is no operator action: the next supervisor start picks the merged code up by itself.

### Residual risks

- Not observed on a real run: exit 10 against a real refusing provider, a real `hung` record, a real pause held for more than 7 days. All three are covered by tests with fakes and injected clocks only; a real cloud run spends the operator's quota and was not started.
- A host suspended for longer than the stall limit can end a run with exit 11 (`hung`) where it used to end with exit 7; the lease was lost either way.
- The watchdog cannot end a hung process, and a run hung inside a pass keeps `<prefix>:active` beaten, so `migrate-primary.sh` refuses until that process is ended (deferred item 3).
- `last_run.reason` is the runner's English sentence and is shown as written on the pt-BR card.
- The API image has to be rebuilt after the merge for the new status fields to be served (the orchestrator's usual rebuild). No migration.

### Follow-up review pass (2026-10-09)

Status: done

A fresh review of the whole diff by a session that did not write it: four layers, 41 findings (triage log above), plus a walk through the runtime changes of the first pass's patch round, which no reviewer had read.

**Patched (11 entries after grouping: medium 2, low 9).**

- medium — a cycle that enriched rows and ended with budget to spare did not reset the refusal count, so refusals on either side of it added up towards exit 10 (`scripts/dev/backfill_gemma.py`, `_run_continuous`). The reset now runs for every cycle with `processed > 0`.
- medium — no test reached exit 11 from the `--continuous` wait loops; added for the budget sleep and the migration wait.
- low — an old `hung` record was shown over any later active run (`frontend/src/components/operations/lines.ts`, `BackfillCard.tsx`).
- low — a host suspended for longer than the stall limit could be recorded as `hung` (`src/core/backfill_runner.py`, `LivenessTicker._loop`).
- low — a hand-started `--continuous` stall closing its record had no test; added.
- low, documentation — docs/api.md (`refused` exit code, `source`, the wording of `provider_refused`); two docstrings about `pause_stale`; the s1.12 and s1.3 feature-doc notes; the feature doc (the arithmetic of exit 10, the suspend note, the native stop test, the ledger sentence, the files table, three BUG lines); the pt-BR `lease_lost` label.

**Deferred (1).** A failed ending is said only on the Operações card (frontmatter, low). The three items of the first pass stay as they were.

**Rejected (23 rows, reasons in the log).** The groups: writes of `last_run` racing a second process or failing once (needs two supervisors on one prefix, or a Redis error on exactly one write); the acknowledgement of a signal arriving only at the next stop check (the intent forbids a handler that prints); descriptive intent-alignment rows that the intent contract or the first pass already settles.

**Rulings asked of this pass.**

- *Can exit 10 fire on a healthy provider?* Not at the shipped limit of 6, for a provider whose quota resets daily and a key nobody else spends. Refusals 1 to 4 are 15 minutes apart. From the fourth on the wait is the rest of the local 24-hour window; the pass after it reserves budget before it is refused, which opens a window of its own, so the wait after the fifth refusal is a whole day. A daily quota has reset between the fifth and the sixth pass, the pass enriches a row, and the count is cleared. Locked by `test_the_fifth_and_sixth_refusal_are_a_daily_window_apart` with the real `DailyBudget`. It can still fire when someone else spends the same key's quota for two days running, which is a provider that does not serve this run. A limit of 4 or less ends a run inside the 15-minute back-offs (said in the config comments). The one path that could add refusals up across productive cycles is the bug patched above.
- *A pause requested while no run is alive.* It expires after 7 days and nothing holds it. That is not the case DW-23 forbids: expiry starts nothing. With no run alive, spend needs a start, and a start has always discarded leftover requests and printed which ones (`_report_discarded_requests`, Story 1.3), whether the pause is one minute or six days old. `--serve` never starts a run without a new start request. An operator who runs `--continuous` under a supervisor that restarts it does get an unpaused run after a crash while paused; that is the start rule of Story 1.3, not the TTL, and changing it (a start that honours a pending pause) is a control-semantics decision outside this story. `EXPIRE` on a missing key is a no-op and the runner has no `SET` path for the pause key, so a resume is never undone.
- *The watchdog under a host suspend.* Fixed here (see above). The run does not resume after a suspend longer than the lease TTL: it ends 7, as before this story.

**The five ledger entries.** DW-19, DW-22, DW-23 and DW-28: resolved, nothing of the original text is left open. DW-81: resolved for what the entry describes (a hung run reading as alive on the lease, the state and the supervisor key, so that no successor could start). Two things it never covered stay true and are carried by deferred item 3 of this spec, not by the entry: the watchdog cannot end the process, so a hung `--serve` supervisor serves no start request until the host runner is restarted, and `:active` stays beaten for a run hung inside a pass.

`followup_review_recommended: false`. This was the follow-up pass and it patched no `high` entry. Patched by verdict: high 0, medium 2, low 9.

**Verification of this pass.**

- `test_backfill_gemma_cli.py` and `test_backfill_liveness_ticker.py` with `REDIS_URL` unset: 259 passed. With the baseline `backfill_runner.py` and `backfill_gemma.py` of commit 751eee4c restored, the three tests of the two fixes fail.
- `test_windows_backfill_host.py` with `REDIS_URL` unset, in this linked worktree: 9 passed, 8 skipped (DW-42); the three modes of `test_native_process_stop_drains_and_clears_real_heartbeat` are among the 9.
- `backfill-card.spec.js` on `PLAYWRIGHT_PORT=5263` with `API_PORT=1`: 34 passed.
- The full gate (`validate.py`, auto tier) runs on the commit that contains this text; its exit code and e2e count are in the session's final report and in the validation stamp.

**Residual risks added by this pass.** The suspend discount relies on the ticker thread's own wait overrunning; a freeze shorter than 60 s is not discounted, and a host that suspends repeatedly while the main thread really is hung delays the watchdog by the time asleep. The card's `hung` rule compares two timestamps written by runner hosts; with one of them missing the line is shown.
