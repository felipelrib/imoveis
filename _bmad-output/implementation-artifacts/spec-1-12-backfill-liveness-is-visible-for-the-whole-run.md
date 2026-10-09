---
title: 'Story 1.12 — Backfill liveness is visible for the whole run'
type: 'bugfix'
created: '2026-10-08'
status: awaiting-operator
baseline_revision: '038c0667db1c248f2e08738488556bdd923e41f2'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/AGENTS.md'
  - '{project-root}/docs/features/_template.md'
warnings: ['oversized']
operator_actions:
  - >-
    AGENT-RUNNABLE. After the branch is merged, find out whether a host supervisor is running the
    old code, and restart it only if one is. Work from the PRIMARY checkout (C:\Workfolder\imoveis),
    never from a worktree: the installer registers the task against the checkout its script lives
    in. Step 1, read-only: powershell.exe -NoProfile -ExecutionPolicy Bypass -File
    scripts/install-backfill-runner.ps1 -Mode Status . On 2026-10-08 (follow-up review) it printed
    "Task: Imoveis-Backfill-Supervisor; state: Disabled" with host phase "stopped" and running
    false, and backfill:gemma:lease, backfill:gemma:supervisor:active and
    backfill:gemma:control:start were all absent on the primary Redis. If it still reads Disabled
    with running false: no supervisor is running, there is no old code to restart, and the next
    start picks up the merged code by itself. Record that and stop here. Do NOT run -Mode Install
    to "restart" a Disabled task: Install runs the host preflight (which reads .env.local), drains
    any running host, registers the scheduled task again ENABLED (per-user, at sign-in plus a
    one-minute recovery trigger, no elevation requested) and starts the --serve supervisor at
    once. It issues no start request itself, but it turns back on a supervisor someone stopped on
    purpose, and a running supervisor serves the next start request with a real cloud run;
    re-enabling it is the human's decision. Step 2, only when Status shows the task enabled
    (Ready or Running) and the host running true: confirm, read-only, that docker exec
    imoveis-redis-1 redis-cli exists backfill:gemma:lease returns 0 (if 1, wait for that run to
    end; do not stop it for this) and that docker exec imoveis-redis-1 redis-cli exists
    backfill:gemma:control:start returns 0 (if 1, leave the restart to the human: the new
    supervisor would consume that request and start a cloud run). Then run -Mode Stop followed by
    -Mode Install. Verify: -Mode Status shows the task running, docker exec imoveis-redis-1
    redis-cli exists backfill:gemma:supervisor:active returns 1 within a few seconds, and docker
    exec imoveis-redis-1 redis-cli get backfill:gemma:supervisor:active returns a host:pid value
    (not 1), which is how the new code identifies itself. Record under "Operator results" in
    docs/features/v0.14-s1.12-backfill-liveness-visible.md.
  - >-
    HUMAN-ONLY. Observe the next real cloud backfill run (starting one spends the Gemini/Gemma
    quota, so do not start one only for this). While it runs, from another shell: (1) python
    scripts/dev/backfill_gemma.py --status during a pass, during the census between passes
    and during the budget sleep: "control state" is never idle and the "lease" line says held,
    last seen about 5 minutes ago or less; (2) docker exec imoveis-redis-1 redis-cli exists
    backfill:gemma:active returns 1 during a pass (also while one row takes longer than 5
    minutes) and 0 during the budget sleep; during a pause it may stay 1 for up to 5 minutes
    after the last row finished, then 0; (3) when the run was started through the supervisor,
    the "supervisor" line reads "running — busy, a run holds the lease"; when it was started by
    hand beside a running supervisor it reads "running — idle; a run in another process
    (host:pid) holds the lease, so a start request waits"; (4) GET /admin/backfill/status shows
    state running, active true and heartbeat_active true during a pass. If any of these reads
    idle for a live run, reopen DW-9 / DW-20 / DW-34 with the observation. Record under
    "Operator results" in the same feature doc.
deferred:
  - summary: >-
      Already tracked as DW-10, which the follow-up review left open with its scope narrowed to
      this (do not mint a second ledger entry): the shared Redis client has no socket timeout,
      so a Redis that accepts the connection and never answers blocks whichever thread calls
      it; a backfill launch loop blocked that way does not reach its next lease check, and the
      process hangs instead of exiting 7.
    evidence: |-
      src/infra/redis_client.py builds the client with redis.Redis.from_url(cfg.redis.url,
      decode_responses=False) and no socket_timeout / socket_connect_timeout. Story 1.12 made
      lease loss independent of the ticker thread (LivenessTicker.lease_lost is computed by the
      reader, and callers wait at most 2 s for the ticker's lock), but the loop's own calls
      (control.should_stop, the budget reservation, the ledger writes) still block without a
      bound. This is the second half of DW-10, left out because the client is shared by the
      API, the Celery workers and the scripts, so a timeout changes every one of them.
    location: >-
      src/infra/redis_client.py:26
    severity: medium
  - summary: >-
      A run whose main thread hangs for good now reads as alive until someone kills the process:
      the liveness thread keeps renewing the lease, re-publishing the state and, under --serve,
      beating the supervisor key, so no successor can start and every start request waits.
    evidence: |-
      LivenessTicker._loop (src/core/backfill_runner.py) runs on a daemon thread and has no
      notion of progress; main (scripts/dev/backfill_gemma.py) starts it after lease.acquire()
      and _serve wraps the supervised run in a keepalive ticker. Before Story 1.12 a hung
      process stopped renewing and the lease lapsed after lease_ttl_seconds (900 s), the
      supervisor key after 30 s. Ways the main thread can hang: a call with no timeout (the
      Redis client has none, DW-10), the signal-handler deadlock of DW-22. A fix is a progress
      watchdog (the loop stamps a counter the ticker requires to move within a bound, then the
      ticker stops renewing), which is a new end state of the runner: Story 1.13 territory,
      excluded by this story's intent contract ("no new exit codes or end states"). Found by
      the blind-hunter layer of the follow-up review, 2026-10-08.
    location: >-
      src/core/backfill_runner.py (LivenessTicker._loop), scripts/dev/backfill_gemma.py (main,
      _serve)
    severity: medium
---

<intent-contract>

## Intent

**Problem:** The cloud backfill runner keeps three Redis keys alive, each from a different, event-driven place: the `<prefix>:active` heartbeat only when a row finishes (DW-9), the published state only from the launch loop and a finished row (DW-20), and the lease only inside `run_backfill` and the two sync wait loops (DW-21). A single slow row, the candidate fetch or the census therefore makes a live, lease-holding writer read as idle to `migrate-primary.sh`, `--status` and the admin status endpoint, and can let the lease lapse. A Redis outage longer than the lease TTL is swallowed, so the run keeps launching on a lease that has expired (DW-10). `--status` reports the supervisor as not running for the whole run it is driving (DW-34).

**Approach:** One `LivenessTicker` in `src/core/backfill_runner.py`, running on a daemon thread for the whole lifetime of a run (from the lease acquire to the release in `main`), owns the refresh of all three keys; the run only tells it what is true (`set_state`, `set_writing`, pause hold). The ticker also decides lease loss: a refused renew, or no successful renew for a whole lease TTL. The supervisor keeps its own heartbeat alive with a second instance of the same class while it drives a run, and `--status` says "running".

## Boundaries & Constraints

**Always:**
- `src/core/backfill_runner.py` imports no `adapters` / `api` module; the ticker uses only the standard library (`threading`, `time`) and the injected primitives (`BackfillLease`, `BackfillControl`, `Heartbeat`), with the clock injectable so the state machine is unit-tested without a thread.
- Each key keeps its meaning. Lease: renewed for the whole run. Published state: whatever the run last set, re-published while the lease is held. `<prefix>:active`: beaten only while rows may be written (inside a pass, from the beat in `_go` to its clear), never during the budget sleep, the migration wait, or a pause with nothing in flight. A paused or sleeping runner must still read as idle to `migrate-primary.sh`.
- The set-then-check order with `migrate-primary.sh` stays: the pass beats `:active` synchronously, on the calling thread, before it reads `<prefix>:migrating`. A pause that ends beats synchronously before the next launch.
- Lease loss is terminal and latched once; after it the ticker publishes no state (the key describes the successor) and the run launches nothing more. In-flight rows still drain. Renewal stays owner-token CAS.
- A Redis failure inside a tick is logged and never propagates into the run; a failure shorter than the lease TTL changes nothing.
- `run_backfill` called without a ticker behaves exactly as before (existing tests are the lock). `BackfillLease` and `Heartbeat` keep their behaviour for `scrape_single_flight.py` and the admin API (additive changes only).
- The existing synchronous renew sites (launch-loop head, pause poll, finished row, the two wait loops) stay as the loop's stop decision; they go through the ticker so there is one bookkeeping.

**Block If:** closing the entries would need a change to the lease key layout, the CAS contract, `src/api/schemas.py`, or `scripts/agent/migrate-primary.sh`.

**Never:**
- No Story 1.13 work: no new exit codes or end states, no change to the signal handlers, no pause TTL change. No Story 1.14 work: nothing in `src/adapters/ai/client.py`.
- No socket timeout on the shared `get_redis()` client (multi-surface; recorded as deferred).
- No real backfill run, no cloud call, no write to the primary Redis.
- No edit to `sprint-status.yaml`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Slow row | one row in flight longer than the heartbeat, state and lease TTLs; ticker ticking | `:active`, `state=running` and the lease are each refreshed on their own cadence; `lease_lost` stays false | none |
| Candidate fetch / census | ticker running, no pass in flight | lease renewed, state re-published; `:active` not beaten | none |
| Paused, nothing in flight | pause poll with zero in-flight rows | ticker stops beating `:active` (key lapses on its TTL), keeps lease and `state=paused`; on resume `:active` is beaten before the next launch | none |
| Paused, rows in flight | pause requested while rows drain | `:active` keeps being beaten until they finish | none |
| Redis blip < lease TTL | renew raises for some ticks, then succeeds | logged; retried on every tick; `lease_lost` false; run unaffected | swallowed |
| Redis outage >= lease TTL | no successful renew for `ttl_seconds` | `lease_lost` latches; loop launches nothing further; `BackfillResult.lease_lost`; CLI exit 7 | logged once |
| Ticker thread hung | thread blocked in a Redis call, no tick completes | a reader of `lease_lost` still gets true once a TTL has passed since the last successful renew | none |
| Renew refused | another token in the lease key | `lease_lost` latches at once; no state publish afterwards; successor's keys untouched | none |
| Supervisor mid-run | `--serve` drove a run; `--status` from another shell | line reads `supervisor : running — busy, a run holds the lease` | none |
| Supervisor idle | `--serve` polling | `supervisor : running — waiting for start requests` | none |
| No supervisor | key absent | `supervisor : not running (--serve)` | none |

</intent-contract>

## Code Map

- `src/core/backfill_runner.py:556` (`Heartbeat`) -- ADD read-only `ttl_seconds` property (the ticker derives its cadence from it). Nothing else changes; `src/api/admin.py:699` and `scrape_single_flight.py` construct these primitives.
- `src/core/backfill_runner.py:664` (`BackfillLease`) -- READ-ONLY. `renew()` is the CAS; `ttl_seconds` is the outage bound. Second user: `src/adapters/queue/scrape_single_flight.py:90,97,256`.
- `src/core/backfill_runner.py:792` (`BackfillControl`) -- READ-ONLY. `publish_state`, `refresh_interval_seconds` (state TTL / 4).
- `src/core/backfill_runner.py` (after `BackfillControl`) -- NEW `LivenessTicker`.
- `src/core/backfill_runner.py:1635` (`run_backfill`) -- NEW param `liveness`. With it: `_lease_held` → `liveness.renew_now()`; `_publish` → `liveness.set_state`; `_refresh_state` is a no-op; the asyncio `_renew_lease_periodically` task is not created; `result.lease_lost` is synced from `liveness.lease_lost` at the loop head, after `sem.acquire()` and in `_owns_shared_state`; the pause loop holds the heartbeat when `inflight == 0` and releases it on resume; the closing `idle` publish is skipped (the ticker's owner ends the run), `backing-off` is still published.
- `src/core/backfill_runner.py:1951` (`_renew_lease_periodically`) -- READ-ONLY reference: "never calls `clock()` or `_refresh_state()`" because the injected `clock` of the unit tests is a finite sequence. The ticker has its own clock, so it never touches the loop's.
- `scripts/dev/backfill_gemma.py:714` (`_run`) -- `liveness` kwarg; `_go` calls `set_writing(True)` before the gate read and `set_writing(False)` in `finally`; `_on_progress` no longer beats; a pass called without a ticker builds an unstarted one so the synchronous transitions are identical. Sets `running` before the candidate fetch.
- `scripts/dev/backfill_gemma.py:1016-1186` (`_publish_wait_state`, `_sleep_for_reset`, `_wait_out_migration`) -- `lease=` becomes `liveness=`; `lease.renew()` → `liveness.renew_now()`; state through `liveness.set_state`.
- `scripts/dev/backfill_gemma.py:1189` (`_run_continuous`) -- threads `liveness` to `_run` and both waits.
- `scripts/dev/backfill_gemma.py:2049-2160` (`main`) -- builds and starts the ticker after `lease.acquire()`, stops it first in the exit `finally`, and treats `liveness.lease_lost` as lease lost there.
- `scripts/dev/backfill_gemma.py:1662` (`_serve`) -- wraps `_run_supervised` in a keepalive-only ticker for the supervisor heartbeat. The idle poll-loop beat stays.
- `scripts/dev/backfill_gemma.py:632` (`_print_status`) -- the three supervisor wordings.
- `src/tests/unit/test_backfill_control.py:49` (`FakeRedis`), `:211` (`_rows`) -- test conventions to follow. `src/tests/unit/test_backfill_gemma_cli.py:23,89` (`_FakeRedis`, `_wire`) -- CLI test wiring.
- `scripts/agent/migrate-primary.sh:161,362` -- READ-ONLY: probes `<prefix>:active` with `EXISTS`.
- `_bmad-output/implementation-artifacts/deferred-work.md:76,83,156,163,307` -- DW-9, DW-10, DW-20, DW-21, DW-34.

## Tasks & Acceptance

**Execution:**
- [x] `src/tests/unit/test_backfill_liveness_ticker.py` -- NEW, written first: ticker state machine with a dict-backed Redis that can be told to raise and a settable clock (every matrix row above the supervisor rows), a real-thread start/stop test, `run_backfill(liveness=...)` integration (slow row, outage past the TTL stops launching, pause hold and resume beat, no asyncio renewer task, no `idle` at exit), and an import check that `core/backfill_runner.py` names no `adapters` / `api` module -- TDD for `src/core/`.
- [x] `src/core/backfill_runner.py` -- add `Heartbeat.ttl_seconds`, `LivenessTicker`, the `liveness` parameter of `run_backfill` and its log helpers -- DW-9, DW-10, DW-20.
- [x] `scripts/dev/backfill_gemma.py` -- wire the ticker through `main`, `_run`, `_run_continuous`, the two wait loops and `_serve`; reword the `--status` supervisor line -- DW-21, DW-34.
- [x] `src/tests/unit/test_backfill_gemma_cli.py`, `src/tests/unit/test_backfill_gemma_completion_cli.py` -- adapt the call sites that passed `lease=` to the wait loops; add CLI tests: the ticker is started after the acquire and stopped before the release, a pass turns writing on before the gate read and off after, the supervisor heartbeat is kept alive during a supervised run, the three `--status` wordings.
- [x] `docs/features/v0.14-s1.12-backfill-liveness-visible.md` -- NEW from the template, all sections; `docs/features/v0.13-s3.1-backfill-runner-hosting.md` or `docs/setup.md` only if they state the old `--status` wording.
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` -- close DW-9, DW-10, DW-20, DW-21, DW-34 with a `resolution:` line each, stating what the code resolves and what it does not.

**Acceptance Criteria:**
- Given a run holding the lease, when the candidate fetch, the census, an in-flight row or the gap between passes lasts longer than any of the three TTLs, then the lease is still held and the published state is still the run's, and during an in-flight row `<prefix>:active` still exists, so `migrate-primary.sh` and the status endpoint do not read the run as idle.
- Given Redis is unreachable for at least `lease_ttl_seconds`, when the launch loop reaches its next check, then no further row is launched, the result is `lease_lost`, and the CLI maps it to exit 7.
- Given a supervisor that is driving a run, when `--status` is run, then the supervisor line says it is running.
- Given `src/core/backfill_runner.py` after the change, when its imports are inspected, then no `adapters` or `api` module is imported.
- Given the full unit suite, when it runs, then `test_scrape_single_flight.py` and every existing backfill test pass unchanged except for the call sites named above.

## Spec Change Log

### 2026-10-08 — Follow-up review: ruling on `<prefix>:active` in the first acceptance criterion

The intent contract is unchanged. This entry records how one sentence of it is read, and two things the follow-up review changed outside it.

- **Trigger.** The first AC says one ticker "owns heartbeat, state and lease renewal across candidate fetch, census, in-flight rows and the inter-pass window". The dev pass does not beat `<prefix>:active` during the candidate fetch, the census, the gap between passes, the budget sleep, the migration wait or a pause with nothing in flight (the intent's own Always clause says the key is "beaten only while rows may be written"). The reviewer was asked to rule on each stretch.
- **Ruling: the dev pass's choice is confirmed for every stretch; no code change.** The ticker owns the key everywhere in the sense that it alone decides when it is beaten; outside a pass the decision is "not beaten".
- **Trace (both sides are set-then-check).** `migrate-primary.sh`: `SET <prefix>:migrating NX` (line 343), then `EXISTS <prefix>:active`, refuse if alive (line 381), then alembic. Runner: `liveness.set_writing(True)` beats `:active` on the pass's thread, then `migration_gate.is_migrating()` (`_go`, scripts/dev/backfill_gemma.py); inside the pass `_migration_holds()` is read again at the launch-loop head and after `sem.acquire()`, and on every pause poll.
  - Migration starts during the candidate fetch: it finds no `:active` and proceeds. The fetch is a read; either the `ALTER TABLE` waits for the fetch's session (which stays open until the pass returns) or the fetch waits for the `ALTER`, with the lease renewed by the ticker either way. Before any row is launched the pass reaches `_go`, beats, reads `:migrating`, finds it held, returns `migration_blocked`, the census is skipped, the session closes and `_wait_out_migration` takes over. No row is written on the way. If the migration has already finished by then, the key is gone and the pass runs on the new schema, exactly as a pass that started a second later would.
  - Migration starts during the census: `:active` was cleared when the pass ended, so it proceeds. The census is a read with the same lock behaviour. Nothing after it writes a row except the next pass, which goes through `_run`'s early gate and `_go` again. A run that ends after the census writes nothing more.
  - Migration starts in the gap between the census and the first row of the next pass: either its `SET` precedes the runner's read in `_go` (the runner is refused), or the runner's read came first, and then so did its beat, which the migration's `EXISTS` sees (the migration is refused). The two can never both proceed.
  - Budget sleep, migration wait: nothing is written; the wake-up is a new pass and goes through the same two checks. Beating `:active` here would refuse every migration for the length of a multi-day run.
  - Pause with nothing in flight: `hold_heartbeat()` stops the beating, the key lapses within 300 s, a migration is then allowed; the pause poll reads `:migrating` on every poll and ends the pass as blocked; a resume beats first (`release_heartbeat()`) and the loop reads `:migrating` after `sem.acquire()` before it launches.
- **What the readers see.** `migrate-primary.sh`: refused only from the beat in `_go` to the end of the pass (including a pause with rows in flight, and the drain after a lost lease). `--status` and the admin endpoint: the lease is held and the state is `running` / `paused` / `backing-off` / `blocked` in every stretch (never `idle`), with `heartbeat_active` true only inside a pass. No live writer reads as idle to either reader.
- **Where it is written down.** The per-stretch table in `docs/features/v0.14-s1.12-backfill-liveness-visible.md`; the DW-21 resolution in the ledger.
- **Changed by the follow-up review, outside the intent contract.**
  - `--status` has a fourth supervisor line, `running — idle; a run in another process (<owner>) holds the lease, so a start request waits`, for a lease held by a `host:pid` other than the supervisor's. The three matrix rows keep their wording. The supervisor key now holds the supervisor's `host:pid` (`Heartbeat(value=...)`, additive, default `1`).
  - DW-10 is not closed: the ledger entry is back to `status: open` with its scope narrowed to the socket timeout (the intent's Never clause keeps that out of this story). The Tasks line above that says "close DW-9, DW-10, DW-20, DW-21, DW-34" is read as: DW-9, DW-20, DW-21 and DW-34 closed, DW-10 half done.
- **KEEP.** Beat-then-read in `_go` on the pass's own thread; the clear in `_go`'s `finally`; `hold_heartbeat()` doing no Redis I/O; the re-read of `:migrating` after `sem.acquire()`.

## Review Triage Log

### 2026-10-08 — Review pass

- verdicts: 42 findings — high 0, medium 10, low 28, false 4, maybe-false 0
- findings:
  - `[medium]` `[patch]` (blind-hunter) `_io_lock` is held across the Redis write, so a ticker thread stuck in a socket blocks `set_state` / `set_writing` / `release_heartbeat` on the launch loop's thread and the loop never reads `lease_lost` — the callers now wait a bounded time for the lock and go on without it; the timer chores skip a tick when the lock is busy; test with the lock held by another thread.
  - `[low]` `[reject]` (blind-hunter) `_run` called without `liveness=` builds an unstarted ticker, so that path has no timer — only tests call `_run` that way (`main` always passes the started ticker when it holds a lease, and a dry run launches nothing); the behaviour is stated in `_liveness_for`'s docstring, and starting a thread per test-only pass is a branch with no production caller.
  - `[medium]` `[patch]` (blind-hunter) after a lost lease nothing beats `:active` while in-flight rows drain; before the change every finished row beat it — the timer keeps beating while writing is on, also after a loss; only the clear and a new synchronous beat are skipped after a loss; tests and ledger text updated.
  - `[low]` `[patch]` (blind-hunter) both wait loops read `control.should_stop()` before `liveness.lease_lost`, so a displaced runner can report (and in the migration wait, clear) a stop aimed at its successor — the free check moved first in both loops.
  - `[low]` `[patch]` (blind-hunter) no test makes the per-step `liveness.lease_lost` read end a wait — one test per loop added.
  - `[low]` `[patch]` (blind-hunter) `_run` publishes `running` before the candidate fetch even when a pause is pending, so an acknowledged `paused` flips to `running` for the fetch — the pass start publishes `paused` when a pause is pending.
  - `[low]` `[reject]` (blind-hunter) a refused renew at pass start does not end the pass before the candidate fetch — nothing is written (`run_backfill` returns `lease_lost` before any launch); the cost is one fetch by a displaced runner, and an early return is a new branch for a case an operator does not meet in normal use.
  - `[low]` `[patch]` (blind-hunter) the DW-21 resolution says the check in `main`'s `finally` "exits 7"; it only suppresses the final publish and `clear_stop` — ledger text corrected.
  - `[low]` `[patch]` (blind-hunter) `_tick_lease` and `_tick_keepalive` do not re-check the stop event, so a tick that outlives `stop()` can renew after the release or re-beat a cleared supervisor key — both re-check before the Redis call.
  - `[low]` `[patch]` (blind-hunter) `stop()` says nothing when the join timed out — it logs `backfill_liveness_tick_failed` with chore `stop` when the thread is still alive.
  - `[low]` `[patch]` (blind-hunter) the documented `:active` cadence (100 s) is not the real one: the thread wakes every 30 s, so the beat lands at the first wake-up at or after 100 s (120 s) — feature doc and DW-9 text corrected.
  - `[low]` `[patch]` (blind-hunter) no test proves the ticker reads a non-default lease or state TTL — cadence test extended with non-default values.
  - `[low]` `[reject]` (blind-hunter) only keepalive beats are checked on a live thread — the thread's whole job is to call `tick()` on `interval`, which `test_start_ticks_on_a_daemon_thread_and_stop_ends_it` proves; every chore is covered deterministically through `tick()`, and timing tests on a real thread are flaky under the host's load.
  - `[medium]` `[defer]` (blind-hunter) the residue of the closed ledger entries lives only in their prose — the one real residue (no socket timeout on the shared Redis client) is recorded in frontmatter `deferred`; the other "does not resolve" notes describe designed behaviour, not open defects.
  - `[false]` `[reject]` (blind-hunter) `sprint-status.yaml` is not in the diff — the orchestrator owns that file; a dev session never writes it.
  - `[low]` `[patch]` (blind-hunter) `lease_lost` is called "a plain attribute" in the class docstring and the feature doc; it is a property that reads the clock and can latch — wording corrected.
  - `[medium]` `[patch]` (blind-hunter) "a failure shorter than the TTL changes nothing" holds only while the loop is parked: the synchronous sites still raise on a Redis error — same root cause as the edge-case and intent-alignment rows on exit 7 below; boundary stated in the feature doc and DW-10, and the lease-lost exit no longer needs Redis.
  - `[low]` `[reject]` (blind-hunter) a pause with nothing in flight lets `:active` lapse (up to 300 s) instead of clearing it — behaviour kept from before the story on purpose (the key lapsed after the last finished row); `hold_heartbeat` runs on every pause poll and does no Redis I/O; clearing is a new write on the migration-exclusion boundary that the intent does not ask for. The docstring now says so.
  - `[low]` `[patch]` (blind-hunter) `test_run_backfill_leaves_the_state_running_at_exit_when_a_ticker_owns_it` ends with an assertion that repeats the previous line — replaced by a check that `idle` was never written.
  - `[medium]` `[patch]` (edge-case-hunter) `_io_lock` across the socket call — same root cause and fix as the first row.
  - `[low]` `[patch]` (edge-case-hunter) a renew that raises at pass start skips `set_state`, so the ticker has nothing to re-publish during the first candidate fetch — the pass start records the state whenever the lease is not known lost.
  - `[low]` `[reject]` (edge-case-hunter) `_run_continuous` called with `lease=` and no `liveness=` builds lease-less tickers in the wait loops — no such caller exists: `main` is the only caller that holds a lease and it always passes the ticker; the tests that omit both hold no lease.
  - `[low]` `[reject]` (edge-case-hunter) `run_backfill` given `lease=L` and a ticker whose `lease` is `None` never renews — no caller builds that pair (`_run` builds the ticker from the same lease); a `ValueError` would guard a state nothing produces.
  - `[low]` `[reject]` (edge-case-hunter) `LivenessTicker.start()` raising inside `_serve`'s `with` ends the supervisor — `Thread.start()` fails only when the process cannot create a thread at all; not a state this change can be shown to reach.
  - `[low]` `[patch]` (edge-case-hunter) a keepalive beat that outlives `stop()` re-sets the supervisor key after the clear — same fix as the stop re-check row above (the beat is skipped once stop is set; a call already inside the socket cannot be recalled and the key then expires on its 30 s TTL).
  - `[low]` `[reject]` (edge-case-hunter) removed per-row beat leaves `_run` without a started ticker with no beat — same test-only path as the second row.
  - `[low]` `[reject]` (edge-case-hunter) no asyncio renewer for `_run` without a started ticker — same test-only path as the second row.
  - `[low]` `[reject]` (edge-case-hunter) no closing `idle` for a pass whose ticker `_run` built itself — same test-only path; `main` publishes the final state on every production exit.
  - `[medium]` `[patch]` (edge-case-hunter) with Redis still down after the loss, the run ends in a `ConnectionError` (exit 1), not exit 7: the loop head read the migration key before the lease flag, `_run_continuous` ran the census (a ledger read), and the single pass read the stop key — the lease flag is read first at the loop head, a lease-lost pass tolerates a failing census, and a lease-lost single pass does not read the stop key; tests with a Redis that stays down.
  - `[low]` `[reject]` (edge-case-hunter) a loss latched after the post-census read (during `_finish`) does not change the exit code — a window of milliseconds; the final key writes are still suppressed in `main`'s `finally`.
  - `[medium]` `[patch]` (verification-gap) no test would notice the wait loops publishing past the ticker (the timer would then stamp `running` over `backing-off` / `blocked` every 30 s) — tests added: after each wait loop publishes, a tick of the same ticker re-publishes the wait state.
  - `[medium]` `[patch]` (verification-gap) `main`'s `finally` taking the ticker's verdict is not pinned where it is the only guard — test added: the pass raises while the ticker reports the lease lost; the successor's state and stop request stay untouched.
  - `[low]` `[patch]` (verification-gap) the per-step lease check in the wait loops never ends a wait in a test — same tests as the blind-hunter row.
  - `[low]` `[patch]` (verification-gap) the guard around the pass-start renew and publish has no error-path test — test added with a control whose first publish raises.
  - `[low]` `[patch]` (verification-gap) "stamped before the call" and "a renew that took a whole TTL proves nothing" are untested (filed as defer) — a test is cheap and the code is this story's, so it is added rather than deferred: a lease double whose `renew` advances the clock.
  - `[false]` `[reject]` (intent-alignment) `:active` is not beaten across candidate fetch, census and the inter-pass window although the AC lists the heartbeat among what the ticker owns there — the ledger entries the intent points to fix the reading: `:active` is the migration guard, a paused or sleeping runner must read as idle to it (fu7 contract, DW-4 wake-up gate, `_wait_out_migration`), and DW-21's defect for those stretches is the lease. Beating it through a 24 h budget sleep would block every migration for a multi-day run. The comment in `main` that said those stretches "all stay visible" is narrowed (patch, same pass).
  - `[low]` `[reject]` (intent-alignment) the expectation lives at `migrate-primary.sh` and the admin status endpoint; the tests assert on the keys they read — both surfaces are pinned to those keys by existing tests (`test_migrate_primary_guard.py` probes `<prefix>:active` written by the real `Heartbeat`; `test_admin_backfill_api.py` reads `BackfillControl.state()`); an observation on a real run is an operator action because a real run spends cloud quota.
  - `[medium]` `[patch]` (intent-alignment) exit 7 is not reached when Redis is still down — same root cause and fix as the edge-case row.
  - `[false]` `[reject]` (intent-alignment) two ticker instances exist during a supervised run and the synchronous sites remain — the three keys of the AC have one refresher and one bookkeeping (the run's ticker; the synchronous sites call into it); the supervisor's own key has a separate owner with a separate lifetime.
  - `[low]` `[reject]` (intent-alignment) `--status` mid-run is tested at function level, and `scripts/windows/backfill_host.py` is not exercised — the host wrapper calls the unchanged `main(["--serve"])`; restarting it and reading `--status` during a real run are operator actions.
  - `[medium]` `[defer]` (intent-alignment) ledger residue not tracked as open — same entry as the blind-hunter row (frontmatter `deferred`).
  - `[false]` `[reject]` (intent-alignment) the spec file and `sprint-status.yaml` are not in the reviewed patch — the spec is withheld from the blind layers by the workflow; the orchestrator owns `sprint-status.yaml`.

### 2026-10-08 — Review pass (follow-up)

- verdicts: 36 findings — high 0, medium 2, low 28, false 6, maybe-false 0
- findings:
  - `[medium]` `[defer]` (blind-hunter) a run whose main thread hangs for good now reads as alive forever: the daemon thread keeps the lease, the state and the supervisor key alive, where before the lease lapsed after 900 s — real, and a consequence of the intent's own design (a thread for the whole run); the fix is a progress watchdog, a new end state, which the intent excludes as Story 1.13 work. Recorded in frontmatter `deferred`; the feature doc states it, and `docs/features/v0.13-s3.1-backfill-runner-hosting.md` got a pointer where it said a wedged unit reads as absent. `scripts/install-backfill-runner.sh` says a wedged unit "can still report absent", which is still true, and is left alone.
  - `[low]` `[patch]` (blind-hunter) "the lease-lost exit needs no Redis" does not hold inside `_run`: a loss latched during the candidate fetch with Redis still down raises at the ledger read or the gate read and exits 1 — `_run_continuous` and the single pass in `main` hand a Redis error from `_run` to `_lease_lost_pass`, which returns `BackfillResult(lease_lost=True)` when the ticker reports the loss and re-raises otherwise; only Redis errors are taken over. Tests for both modes, and for a Redis error with the lease held.
  - `[medium]` `[patch]` (blind-hunter) `--dry-run` beats and then deletes `<prefix>:active`, also beside a live pass, so `migrate-primary.sh` reads an idle guard until the live run's next beat (up to 120 s) — behaviour older than this story, but the lines were rewritten here and it breaks the intent's "beaten only while rows may be written"; a dry run now builds its ticker without the heartbeat (`_liveness_for(writes_rows=False)`). Test added.
  - `[low]` `[patch]` (blind-hunter) the feature doc and the DW-34 resolution describe three `--status` lines and a supervisor key holding `1`; the code prints a fourth line and stores `host:pid` — doc table, Changes list, How to Test and DW-34 text updated.
  - `[low]` `[patch]` (blind-hunter) How to Test says `EXISTS <prefix>:active` returns 0 during a pause once the rows have finished; the key is left to lapse, so it reads 1 for up to 300 s — step and operator action 2 corrected.
  - `[low]` `[patch]` (blind-hunter) the lease-lost banner printed without a census drops the run's own totals — the cycles / elapsed / enriched / errors line is printed there too. Test added.
  - `[low]` `[patch]` (blind-hunter) no test ticks at the thread's real wake-up interval, so the 120 s `:active` cadence in the doc and DW-9 is unpinned — test added that steps by `ticker.interval` and pins 120 s / 30 s / 300 s.
  - `[low]` `[patch]` (blind-hunter) a renew stuck past `stop()` comes back refused after the owner released the lease and latches (and logs) a lost lease for a run that ended cleanly — `renew_now` returns without latching when the stop flag is set. Test added.
  - `[low]` `[patch]` (blind-hunter) a streak of failures is logged at its start and never at its end — `backfill_liveness_tick_recovered` is logged when a failing chore works again. Test added.
  - `[low]` `[patch]` (blind-hunter) `run_backfill` gates the finished-row renew on its `lease` argument while the rest goes through `liveness.lease`, so `run_backfill(liveness=ticker)` without `lease=` skips that renew — `lease` is taken from the ticker when none is passed. Test added. A `ValueError` on a mismatching pair stays rejected (carried, first pass: no caller builds it).
  - `[low]` `[patch]` (blind-hunter) `--status` reads the supervisor key twice (`is_active()`, then `value()`), so an expiry in between gives a serving supervisor with no identity; and a lease with owner `unknown` falls back to the busy line — one read now; the unknown-owner fallback is kept on purpose (nothing to compare) and pinned by a test.
  - `[low]` `[patch]` (blind-hunter) the fu7 feature doc states two rules this story reverses for CLI runs (no thread, a failing renew never sets `lease_lost`) with no pointer — a "superseded in part" line added to `docs/features/v0.13-fu7-backfill-lease-background-renewer.md`.
  - `[low]` `[patch]` (edge-case-hunter) loss latched during the fetch, then a Redis read in `_run` raises — same root cause and fix as the blind-hunter row on `_run`.
  - `[low]` `[patch]` (edge-case-hunter) `_run` raising after the ticker latched the loss replaces the lease-lost outcome — same fix (`_lease_lost_pass`).
  - `[low]` `[reject]` (edge-case-hunter) carried: `_run_continuous` or a wait loop called with `lease=` and no `liveness=` builds a lease-less ticker — no such caller, as logged in the first pass.
  - `[low]` `[patch]` (edge-case-hunter) `run_backfill` given `liveness` without `lease=`, or a mismatching pair — the first half is the blind-hunter row above (patched); the mismatch guard stays rejected as in the first pass.
  - `[low]` `[reject]` (edge-case-hunter) a tick stuck in `beat()` lands after `set_writing(False)` cleared the key, so `:active` exists for up to 300 s with no writer — needs a Redis call that stalls for more than 2 s; the effect is a migration refused for at most one TTL, the safe direction; a re-check and clear after every beat is a second Redis call on every tick for that case.
  - `[low]` `[reject]` (edge-case-hunter) a tick stuck in `publish_state(old)` lands after `set_state(new)` — same stalled-Redis precondition; the stale state is replaced at the next due publish, which is counted from the stuck tick's start, so in less than one 30 s period.
  - `[false]` `[reject]` (edge-case-hunter) a renew whose CAS succeeded but whose meta write raised is counted as failed — `BackfillLease._write_meta` catches every exception itself, so `renew()` returns the CAS result.
  - `[low]` `[patch]` (edge-case-hunter) with two supervisors on one prefix the idle one overwrites the key value, and a supervisor-driven run reads as "started elsewhere" — the fourth line now says "idle; a run in another process (<owner>) holds the lease", which is true of the supervisor that beat last and claims nothing about who started the run.
  - `[low]` `[patch]` (edge-case-hunter) supervisor key expiring between `is_active()` and `value()` — same fix as the blind-hunter row (one read).
  - `[low]` `[patch]` (edge-case-hunter) spurious lease-lost line when a renew outlives `stop()` — same fix as the blind-hunter row.
  - `[low]` `[reject]` (edge-case-hunter) carried: `_run(lease=...)` without a started ticker has no per-row beat and no asyncio renewer — test-only path, as logged in the first pass.
  - `[low]` `[patch]` (edge-case-hunter) claim "three `--status` wordings" no longer true — same fix as the blind-hunter doc row.
  - `[low]` `[patch]` (edge-case-hunter) claim "an outage of a whole TTL ends in exit 7" fails when it spans the candidate fetch — same fix as the `_run` row.
  - `[low]` `[patch]` (verification-gap) the guard around the pause read at pass start has no test — `test_a_pause_read_that_raises_at_pass_start_still_reaches_the_fetch` added.
  - `[low]` `[patch]` (verification-gap) the docs contradict the shipped `--status` behaviour — same fix as the blind-hunter doc row.
  - `[low]` `[reject]` (intent-alignment) carried: the matrix rows are verified through `tick()` on a fake clock and the outside readers (`migrate-primary.sh`, the admin endpoint) are not exercised — as logged in the first pass (both surfaces are pinned to the keys by existing tests; a real run is operator action 2).
  - `[false]` `[reject]` (intent-alignment) a fourth `--status` line and a supervisor key value go beyond the three matrix rows — the three rows still print their lines (their tests are unchanged); the fourth case was outside the matrix and is recorded in the Spec Change Log.
  - `[low]` `[patch]` (intent-alignment) the feature doc and DW-34 contradict the code and its test — same fix as the blind-hunter doc row.
  - `[false]` `[reject]` (intent-alignment) the ticker surface is wider than "set_state, set_writing, pause hold" — the extra members (`renew_now`, `release_heartbeat`, `lease`, `interval`, `keepalives`) are the Design Notes sketch; `note_lease_lost` is declared in the feature doc; no bad outcome is named.
  - `[false]` `[reject]` (intent-alignment) the state published before the fetch, the tolerated census failure, the skipped stop read and the lease check before the stop key are not named by the intent — each serves the second AC (exit 7) or "the successor's keys untouched"; no bad outcome is named.
  - `[false]` `[reject]` (intent-alignment) `release_heartbeat()` on resume is a new raising site where no Redis call existed — `control.is_paused()` and `_publish(RUNNING)` at that same point already raised on a Redis error, and the intent requires that beat to be synchronous (launching without it would break the exclusion with `migrate-primary.sh`).
  - `[low]` `[reject]` (intent-alignment) carried: `_run` without a ticker builds an unstarted one, which suppresses the asyncio renewer — test-only path, as logged in the first pass.
  - `[false]` `[reject]` (intent-alignment) `:active` is beaten after a lost lease by a process that no longer holds it — checked for the migration guard: the rows in flight still write, so the guard must stay up; the beating ends with the pass, the key then lapses within 300 s, and a hung row is bounded by the AI client's own timeouts. The safe direction.
  - `[low]` `[patch]` (intent-alignment) the unit test asserts a 105 s gap at 5 s steps, a cadence the thread never produces — same fix as the blind-hunter cadence row.

## Design Notes

**Why a thread.** `spec-dw-backfill-lease-background-renewer.md` (fu7) forbade renewing from a thread; that patch only had to cover awaits inside `run_backfill`. DW-21's stretches (`fetch_candidate_rows`, `_census`) are blocking DB calls outside any event loop, and a blocking section inside `enrich_fn` also starves a coroutine timer. Only a thread covers them. The thread touches no asyncio object: the loop reads `liveness.lease_lost`, a plain attribute.

**Why the renewer never refreshed the state (DW-20).** `run_backfill`'s `clock` is injected and the tests pass finite sequences; a timer calling it would exhaust them. The ticker takes its own `clock` (default `time.monotonic`) and never calls the loop's.

**Lease loss by elapsed time.** `lease_lost` is a property: latched flag, or `clock() - last_ok >= ttl`, where `last_ok` is stamped *before* the renew call that succeeded (so the bound errs early, never late). Computed by the reader, it holds even when the ticker thread is stuck in a socket call. After a failed renew the ticker retries on every tick, not every `ttl/3`.

**Ticker surface (sketch, names binding for the call sites in the Code Map).**

```python
LivenessTicker(*, lease=None, control=None, heartbeat=None, keepalives=(), clock=time.monotonic)
.lease                      # the BackfillLease it renews, or None
.interval                   # seconds between wake-ups: the smallest due period
.tick()                     # one pass of the due chores; never raises (what the thread calls, what tests call)
.start() / .stop(timeout=5.0)   # daemon thread; also a context manager; stop never raises
.lease_lost                 # property, no Redis I/O: latched, or a whole TTL since the last successful renew
.renew_now() -> bool        # synchronous CAS on the caller's thread, same bookkeeping; raises on a Redis error; False once lost
.set_state(state)           # remember, then publish now unless the lease is lost; raises on a Redis error (callers guard as before)
.set_writing(True)          # beat `:active` now on the caller's thread (raises), then on the timer
.set_writing(False)         # stop beating and clear the key; not cleared once the lease is lost (a successor may be beating it); never raises
.hold_heartbeat() / .release_heartbeat()   # pause with nothing in flight; release beats now when writing is on
```

`keepalives` are extra `Heartbeat`s beaten on every due tick regardless of lease or writing (the supervisor's key). A ticker with neither lease nor control nor heartbeat is valid.

**Cadences.** lease `ttl/3`; state `control.refresh_interval_seconds`; `:active` and each keepalive `ttl/3`. The thread wakes at the smallest of them and runs only the chores that are due.

**Seams.** 1.13: end states stay in `_run_continuous` / `main`; the ticker exposes nothing about exit codes, and its tick is the natural place for a stop flag a signal handler sets without Redis I/O. Pause TTL untouched. 1.14: no client change; `_on_progress` keeps the inference counters.

## Verification

**Commands:**
- `C:\Workfolder\imoveis\.venv\Scripts\python.exe scripts/agent/validate.py` -- expected: exit 0 (auto tier; the `scripts/` diff adds the harness-marked tests).

## Auto Run Result

Status: awaiting-operator (code complete and committed; two operator actions are listed in the frontmatter: restart the host supervisor so it runs the new code, and observe the next real run. No migration, no image rebuild.)

**Summary.** `LivenessTicker` (`src/core/backfill_runner.py`) runs on a daemon thread from the lease acquire to the release in `main` and refreshes the lease (every `ttl/3`), the published state (every 30 s) and, inside a pass, the `<prefix>:active` heartbeat (due every 100 s, beaten at the next 30 s wake-up). The run tells it what is true (`set_state`, `set_writing`, pause hold). It also decides lease loss: a refused renew, or no successful renew for a whole lease TTL, computed by the reader so a stuck thread cannot hide it. A lease-lost run launches nothing more and exits 7 without needing Redis. The supervisor keeps its own heartbeat alive while it drives a run, and `--status` prints "running — busy" / "running — waiting" / "not running".

**Files changed.**
- `src/core/backfill_runner.py` — `LivenessTicker`; `Heartbeat.ttl_seconds`; `run_backfill(liveness=...)`; log line `backfill_liveness_tick_failed`.
- `scripts/dev/backfill_gemma.py` — `main` starts and stops the ticker; `_run`, `_run_continuous`, `_sleep_for_reset`, `_wait_out_migration` take `liveness=`; `_serve` keepalive; `--status` supervisor line; lease-lost exit tolerates a Redis that is still down.
- `src/tests/unit/test_backfill_liveness_ticker.py` (new) — ticker state machine, thread start/stop, `run_backfill(liveness=...)`, import check.
- `src/tests/unit/test_backfill_gemma_cli.py`, `src/tests/unit/test_backfill_gemma_completion_cli.py` — wait-loop call sites (`lease=` → `liveness=`), wiring tests, `--status` tests.
- `docs/features/v0.14-s1.12-backfill-liveness-visible.md` (new) — feature doc.
- `_bmad-output/implementation-artifacts/deferred-work.md` — DW-9, DW-10, DW-20, DW-21, DW-34 closed, each with what it does not resolve.

**Decisions taken without a human.**
- `<prefix>:active` is beaten only inside a pass (and not during a pause with nothing in flight). The AC lists the heartbeat among what the ticker owns "across candidate fetch, census … and the inter-pass window"; the ticker owns it there in the sense that it alone decides when it is beaten, and it does not beat it, because that key is the migration guard and a sleeping or paused runner must read as idle to `migrate-primary.sh` (fu7 contract, DW-4). Lease and state are refreshed through all those stretches.
- A thread, against the fu7 spec's "do not renew the lease from a thread": the candidate fetch and the census are blocking calls outside any event loop.
- The DW-10 rule ("no successful renew for a whole TTL is a loss") replaces the fu7 rule ("a failing renew never sets `lease_lost`") for runs with a ticker. `run_backfill` without a ticker keeps the fu7 behaviour; only tests call it that way.
- With a ticker, `run_backfill` does not publish `idle` when a pass ends; `main` publishes the final state. Between passes the state stays `running` (or `backing-off`).
- After a lost lease the timer keeps beating `:active` until the pass has drained; it does not clear the key at the end (a successor may be beating it), so the key can outlive a displaced pass by up to 300 s.
- Two ticker instances exist during a supervised run: the run's (lease, state, `:active`) and the supervisor's (its own key).
- The `--status` "busy" wording is derived from the lease, so an idle supervisor beside a run started by hand also reads busy.
- No socket timeout was added to the shared Redis client (recorded in `deferred`).

**Review findings (one pass, four layers, 42 findings).**
- Patched: 23 rows in 13 root causes. By entry verdict: medium 5 (lock held across the Redis write; no `:active` beat while rows drain after a loss; exit 1 instead of 7 when Redis is still down, three rows; two missing tests: wait loops publishing through the ticker, the `finally` verdict), low 8 (lease check before the stop check in the wait loops; pass-start state with a pending pause and after a raising renew; stop re-checks and the stop log line; cadence wording; ledger and docstring wording; three test gaps).
- Deferred: 1 entry, 2 rows (socket timeout on the shared Redis client; see frontmatter).
- Rejected: 17 rows. `_run` / `_run_continuous` / `run_backfill` called with a lease and no started ticker (6 rows): no production caller, stated in `_liveness_for`'s docstring. Refused renew at pass start does not skip the fetch: nothing is written, one fetch by a displaced runner. Thread coverage: the thread only calls `tick()`, proved by one live test. `:active` lapses instead of being cleared on a pause: behaviour kept from before. `start()` raising in `_serve`: not a reachable state. Loss latched during `_finish`: milliseconds, final writes still withheld. Surfaces tested through their keys, `--status` at function level: observation of a real run is an operator action. False: `sprint-status.yaml` (orchestrator-owned, 2 rows), heartbeat scope outside a pass (settled by the ledger constraints), two instances (one bookkeeping for the three keys).

**Follow-up review: recommended (true).** Five medium entries were patched in this pass. The unverified risk is the patched code itself, which no review layer has read: the bounded lock wait (`_caller_lock`, and the timer chores that skip a tick when the lock is busy), the timer beating `:active` after a lost lease, and the lease-lost exit path that tolerates a failing census.

**Verification.**
- Unit files covering the change, run by the implementer with `REDIS_URL` unset and the database on a closed port: `test_backfill_liveness_ticker.py` 48 passed, `test_backfill_gemma_cli.py` 139 passed, `test_backfill_gemma_completion_cli.py` 28 passed, the six other `run_backfill` unit files passed; before the review patches the 14 listed files (including `test_scrape_single_flight.py`, `test_admin_backfill_api.py`, `test_core_api_layering.py`, `test_backfill_runner_hosting.py`) passed, 610 tests.
- A first gate run on the tree before the review patches: lint passed, unit 2926 passed and 1 skipped, contract 60 passed; its "test db: create + extensions" step failed once with "server closed the connection unexpectedly" (the known first-connection failure of the test Postgres under load); the run was stopped during the harness tests and superseded.
- The gate on the final commit (`scripts/agent/validate.py`, tier backend + harness) runs after this section is written; its exit code is in the session's final report, because writing it here would change the tree the stamp is for.
- Not verified here: any behaviour against a real Redis under a real run (operator action 2), and the installed Windows supervisor (operator action 1).

**Residual risks.**
- A Redis error at a synchronous site while the lease is not known lost (launch-loop head, pause poll, the 2 s stop poll of the wait loops) still ends the run with an exception, as before this story. The TTL rule covers the stretches where the loop is parked.
- No socket timeout on the shared client: a Redis that never answers blocks the loop's own calls.
- `stop()` waits 5 s; a tick stuck longer can finish one Redis call after the final state was published.

### Follow-up review pass — 2026-10-08

Status: awaiting-operator (unchanged; the operator actions in the frontmatter were rewritten, see below).

**Ruling on `<prefix>:active` (first AC).** The dev pass's choice is confirmed for every stretch, with the trace in the Spec Change Log: the key is beaten only from the beat in `_go` to the end of a pass, a migration is allowed during the candidate fetch, the census, the gap between passes, the budget sleep, the migration wait and (after the key lapses) a pause with nothing in flight, and it is safe there because every launch is behind a beat-then-read of `<prefix>:migrating`. No code change. The feature doc has the per-stretch table; the DW-21 resolution states the ruling.

**Changed in this pass.**
- `scripts/dev/backfill_gemma.py` — `_lease_lost_pass` (a pass that dies on a Redis error after the loss is "lease lost", exit 7, in both modes); a dry run builds its ticker without the `:active` heartbeat; the census-less lease-lost banner keeps the run's totals; the supervisor beats its key with `host:pid` and `--status` reads it once and tells a run in another process from the one the supervisor drives.
- `src/core/backfill_runner.py` — `Heartbeat(value=...)` and `Heartbeat.value()` (additive); a renew that answers after `stop()` does not latch a loss; `backfill_liveness_tick_recovered`; `run_backfill` takes the lease from the ticker when none is passed.
- Tests — 12 new test functions in `test_backfill_gemma_cli.py` and `test_backfill_liveness_ticker.py`; those that cover a code change fail on the code before it, the others pin behaviour that had no test (the pause read at pass start, the real wake-up cadence, a Redis error with the lease held, the two fallbacks of the `--status` line).
- Docs and ledger — feature doc (per-stretch table, four `--status` lines, wedged-run note, How to Test); pointers in the fu7 and s3.1 feature docs; ledger: DW-10 back to `open` and narrowed, DW-9 / DW-21 / DW-34 resolutions corrected.

**Reviewer's own findings (not from a layer).**
- Ledger: DW-10 was marked `resolved` while its second half (the socket timeout) is open. A runner-only timeout was judged not contained: rows reach Redis through `get_redis()` in the AI pacer and the enrichment pipeline on the event-loop thread, the client is shared by the API and the workers, and a timeout creates new error paths (a row counted as failed, a ledger attempt, exit 1 at a synchronous site) that need their own decision. DW-10 is `open` again with that scope. DW-9, DW-20, DW-21 and DW-34 pass the same test: what their "does not resolve" notes name is either designed behaviour or belongs to DW-10.
- Operator action 1 told the operator to run `-Mode Stop` then `-Mode Install`. On this host the task is installed but Disabled and the host is stopped; Install would re-enable and start a supervisor that was turned off on purpose. The action now reads the state first and restarts only a supervisor that is running.
- `BackfillLease` is untouched by the diff and `src/adapters/queue/scrape_single_flight.py` is not in it; `test_scrape_single_flight.py` passes unchanged. `src/core/backfill_runner.py` imports only the standard library at module level (the lazy `infra.logging` import inside the `_log_*` helpers is the file's existing pattern). The shared `get_redis()` client is used from two threads with plain commands only (no pipeline, no pub/sub), which redis-py's connection pool supports. The log calls pass `chore=` and `error=`, no reserved LogRecord key. Exit codes, signal handlers, pause TTL and `src/adapters/ai/client.py` are unchanged.

**Review findings (one pass, four layers, 36 findings).**
- Patched: 22 rows in 13 root causes. By entry verdict: medium 1 (a dry run beat and deleted `:active`), low 12 (a pass dying on Redis after the loss; docs and ledger behind the `--status` code; the pause step in How to Test; totals in the census-less banner; cadence test at the real interval; renew answering after `stop()`; recovery log line; one lease inside `run_backfill`; one read of the supervisor key; wording with two supervisors; pointer in the fu7 doc; pause-read test).
- Deferred: 1 entry (medium): a run whose main thread hangs reads as alive forever (frontmatter).
- Rejected: 13 rows. Carried from the first pass (4): calls with a lease and no started ticker, in three shapes, and tests through `tick()` instead of the outside readers. Low (2): a stuck beat landing after the clear and a stuck publish landing after a newer state, both needing a Redis call stalled for more than 2 s, both self-healing, the first in the safe direction. False (6): the meta write cannot fail a renew; the fourth `--status` line leaves the three matrix rows intact; the wider ticker surface and the extra lease-loss handling name no bad outcome; `release_heartbeat` is not a new raising site; beating `:active` during the drain after a loss is the safe direction. Plus the rejected half of one patched row (a `ValueError` for a mismatching lease pair).

**Follow-up review: not recommended (false).** This was the follow-up pass and it patched no `high` entry.

**Verification.**
- The three unit files of the story, `REDIS_URL` unset and the database on a closed port: 229 passed. With the two source files put back to the previous commit, 8 of the new cases fail (the ones that cover a code change of this pass) and everything else passes.
- `scripts/agent/validate.py` (auto tier: backend + harness) on the final commit: the exit code is in the session's final report, because writing it here would change the tree the stamp is for.
- Read-only on the host: `install-backfill-runner.ps1 -Mode Status` (task Disabled, host stopped) and `EXISTS` on four primary Redis keys (all 0).
- Not verified: anything against a real Redis under a real run (operator action 2); `-Mode Install` itself (not run; whether registering the task needs elevation on this host is unknown); the fourth `--status` line against a real supervisor.

**Residual risks (in addition to those above).**
- A wedged run reads as alive (deferred).
- With two supervisors on one prefix the `--status` line describes whichever beat last.
- A supervisor still on the old code beats `1`; `--status` then cannot tell its run from another and prints the plain busy line.
