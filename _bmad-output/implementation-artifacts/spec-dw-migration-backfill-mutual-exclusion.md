---
title: 'Migration ↔ backfill mutual exclusion (DW-3, DW-4)'
type: 'bugfix'
created: '2026-08-11'
status: 'done'
baseline_revision: '45986fbe033706c338a3611d55c4d1ad6244447e'
final_revision: '7e5e84637358044002f35021db1a5f5c02503a57'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/project-context.md'
warnings: ['oversized']
---

<intent-contract>

## Intent

**Problem:** `migrate-primary.sh` reads the advisory heartbeat `backfill:gemma:active` once and then runs `alembic upgrade head` with nothing holding the window, so a backfill runner that starts inside that gap migrates against a live writer (DW-3); and because `_go`'s `finally` clears the heartbeat before `_sleep_for_reset`, a runner sleeping out its RPD window reads as idle to the guard, keeps its Redis lease, and resumes writing mid-migration when the window resets (DW-4). Same root cause: the guard is check-then-act with no key the runner can honor.

**Approach:** Add a migration-held mutual-exclusion key `backfill:gemma:migrating`. `migrate-primary.sh` takes it atomically (`SET NX EX` with a per-invocation token) **before** it reads the heartbeat and releases it from an `EXIT` trap; the runner beats its heartbeat **before** it reads the migrating key, at pass entry, in the launch loop and in the pause poll. Set-then-check on both sides makes the two mutually exclusive: whichever wrote first, at least one side sees the other's key. A continuous runner blocked this way waits the migration out and resumes instead of dying.

## Boundaries & Constraints

**Always:** `src/core/backfill_runner.py` stays framework-free and injectable (AD-1) — the new gate is a small Redis-duck-typed class beside `Heartbeat`/`BackfillLease`, and `run_backfill` receives a plain `Callable[[], bool]` exactly like `is_quota_error`/`clock`. `migrate-primary.sh` keeps its current fail-closed behaviour: Redis unreachable ⇒ refuse to migrate. The migrating key is released by token compare-and-swap only, so a refused invocation can never delete the holder's key. The runner's checkpoint stays intact through every refusal — a blocked pass is never a stall, a stop, or a completion.

**Block If:** the guard cannot be made mutually exclusive without changing the primary Redis connection contract (host/port/db) that `migrate-primary.sh` uses today.

**Never:** do not change `Heartbeat`'s semantics, its key, or its TTL — `:active` stays the advisory signal it is. Do not make the runner delete or expire the migrating key. Do not touch the primary compose stack, `validate.sh`, or `finish-feature.sh`. Do not add a second Redis client factory. Do not edit `_bmad-output/implementation-artifacts/deferred-work.md` (the orchestrator records resolution). Do not change `_sleep_for_reset`'s sleep/renew/publish cadences.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Idle primary | no `:active`, no `:migrating` | script takes `:migrating`, reports idle, runs `alembic upgrade head`, releases the key on exit | No error expected |
| Runner actively working | `:active` alive | script takes `:migrating`, refuses (`exit 1`, existing message), trap releases `:migrating` | Refusal, primary untouched |
| Runner starts during migration | `:migrating` held by the script | runner beats `:active`, reads `:migrating`, refuses to launch any row; single pass exits `EXIT_MIGRATION_ACTIVE`; `--continuous` waits for the key to clear, then resumes | No rows launched, checkpoint intact |
| Runner wakes from `_sleep_for_reset` mid-migration | lease held, `:active` cleared, `:migrating` held | the next pass entry beats `:active`, sees `:migrating`, returns `migration_blocked` without launching a row (DW-4) | Same as above |
| Migration starts while runner is paused | `:migrating` set during the pause poll | pause loop stops launching, result flagged `migration_blocked` (not `stopped`) | Checkpoint intact |
| Second migration invocation | `:migrating` already held by another token | script refuses (`exit 1`), does **not** delete the other holder's key | Fail closed |
| Primary Redis unreachable from the script | connection error | script refuses (`exit 1`), fail-closed message unchanged | No migration |
| `--continuous` waits past the limit | `:migrating` still held after `backfill.migration_wait_seconds` | banner + `EXIT_MIGRATION_ACTIVE` | Operator restarts after the migration |
| Migration script killed hard | `:migrating` left behind | key self-clears within its TTL (`MIGRATE_LOCK_TTL_SECONDS`, default 1800s); never deleted manually | Documented, same contract as `:active` |

</intent-contract>

## Code Map

- `scripts/agent/migrate-primary.sh` -- CHANGE: take `backfill:gemma:migrating` (`SET NX EX` + token) and arm the release trap **before** the existing `:active` probe; add `busy` refusal; update the header contract comment.
- `src/core/backfill_runner.py` -- NEW `MigrationGate` (`<prefix>:migrating`, read-only: `is_migrating()`, `holder_token()`); CHANGE `run_backfill(..., is_migrating=None)` checked at the launch-loop head and in `_may_launch`'s pause poll; CHANGE `BackfillResult` + `to_dict()` gain `migration_blocked`.
- `scripts/dev/backfill_gemma.py` -- NEW `_migration_gate_for`, `_migration_refusal`, `_wait_out_migration`, `EXIT_MIGRATION_ACTIVE = 8`; CHANGE `main` (startup refusal), `_run`/`_go` (beat-then-check at pass entry, pass the predicate into `run_backfill`), `_run_continuous` (wait out a blocked pass, else exit 8).
- `src/infra/config.py` + `configs/app_config.yaml` -- NEW `backfill.migration_wait_seconds` (default 1800, `ge=0`).
- `src/tests/unit/test_backfill_control.py` -- NEW core coverage: gate key/read, launch-loop refusal, pause-poll refusal, `migration_blocked` not `stopped`.
- `src/tests/unit/test_backfill_gemma_cli.py` -- NEW CLI coverage: startup refusal + exit code, beat-then-check at pass entry (the DW-4 wake-up path), predicate wiring.
- `src/tests/unit/test_backfill_gemma_completion_cli.py` -- NEW `--continuous` coverage: wait-out-and-resume, and wait timeout → exit 8.
- `src/tests/unit/test_migrate_primary_guard.py` -- NEW shell-level test (throwaway git repo + fake `redis` module on `PYTHONPATH`, per `test_setup_worktree_isolation.py`): asserts set-before-check ordering, release on exit, and the busy/alive/unreachable refusals.
- `docs/features/v0.13-fu6-migration-backfill-mutual-exclusion.md` -- NEW feature doc from `docs/features/_template.md` (all six sections).
- `_bmad-output/implementation-artifacts/sprint-status.yaml` -- NEW key `v0.13-fu6-migration-backfill-mutual-exclusion`.

## Tasks & Acceptance

**Execution:**
- [x] `src/tests/unit/test_backfill_control.py` -- add failing tests for `MigrationGate` and the two `run_backfill` refusal points -- TDD on `src/core/` per project testing rules
- [x] `src/core/backfill_runner.py` -- add `MigrationGate`, the `is_migrating` predicate parameter and `BackfillResult.migration_blocked` -- the injectable, framework-free half of the mutual exclusion (AD-1)
- [x] `src/infra/config.py`, `configs/app_config.yaml` -- add `backfill.migration_wait_seconds` -- bounds how long a continuous runner waits out a migration
- [x] `scripts/dev/backfill_gemma.py` -- construct the gate, refuse at startup and at pass entry after `heartbeat.beat()`, pass the predicate into `run_backfill`, wait out a blocked pass in `_run_continuous` -- closes DW-4's wake-up hole
- [x] `scripts/agent/migrate-primary.sh` -- acquire `:migrating` + arm the trap before the `:active` probe, refuse on `busy`, release by token CAS -- closes DW-3's check-then-act window
- [x] `src/tests/unit/test_backfill_gemma_cli.py`, `src/tests/unit/test_backfill_gemma_completion_cli.py` -- CLI refusal, exit codes and the continuous wait/resume path -- the runner half must be exercised end-to-end through `main`
- [x] `src/tests/unit/test_migrate_primary_guard.py` -- shell guard test over a throwaway repo with a fake `redis` module -- the set/release path and ordering are the DW-3 fix and are otherwise untested
- [x] `docs/features/v0.13-fu6-migration-backfill-mutual-exclusion.md`, `_bmad-output/implementation-artifacts/sprint-status.yaml`, `CLAUDE.md` -- document the new key and mint the follow-up story key; update the one-line `migrate-primary.sh` description in CLAUDE.md's "Primary stack is inviolable" bullet -- harness-required, and the old text says the guard keys off the heartbeat alone

**Acceptance Criteria:**
- Given a migration holding `backfill:gemma:migrating`, when a backfill runner starts or wakes from `_sleep_for_reset`, then it launches no row, leaves the checkpoint untouched, and reports `migration_blocked` rather than a stall or an operator stop.
- Given a live runner and a migration invoked concurrently, when both complete their set-then-check sequence in any interleaving, then at least one of the two refuses — never both proceed.
- Given `migrate-primary.sh` exits for any reason (success, refusal, or error) after taking `backfill:gemma:migrating`, when the process ends, then the key it owns is released and a key owned by anyone else is left alone.
- Given the primary Redis is unreachable, when `migrate-primary.sh` runs, then it refuses with exit 1 and does not run alembic — unchanged from today.
- Given `--continuous` is blocked by a migration that finishes within `backfill.migration_wait_seconds`, when the key clears, then the runner resumes with a fresh pass instead of exiting.
- Given `src/core/backfill_runner.py` after the change, when its imports are inspected, then it still imports no `adapters`/`api`/Celery/DB module and the gate is reachable only through injected values (AD-1).

## Spec Change Log

## Review Triage Log

### 2026-08-11 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 13: (high 1, medium 7, low 5)
- defer: 2: (high 0, medium 2, low 0)
- reject: 4
- addressed_findings:
  - `[high]` `[patch]` The lock was taken once with a fixed 1800s TTL and never renewed, so an `alembic upgrade` outrunning it lost mutual exclusion mid-DDL — DW-3 reintroduced by the clock. Added a background token-CAS renewal watchdog (TTL/3), killed from the EXIT trap, plus a post-alembic ownership re-check that warns if the window was ever unguarded.
  - `[medium]` `[patch]` `_wait_out_migration` returned `True` on a lost lease claiming the next pass would classify it, but `_go` short-circuits on the gate before `run_backfill` ever renews — the runner looped on `migration_blocked` forever, re-beating `:active` and blocking the next legitimate migration. Now returns `cleared`/`stopped`/`lease_lost`/`timeout`, mapped to exits 0/6/7/8.
  - `[medium]` `[patch]` `migration_wait_seconds` bounded a single call, not the total wait the config comment and AC describe; repeated blocked cycles reset it. Now a cumulative budget threaded through `_run_continuous`.
  - `[medium]` `[patch]` The wait never re-published control state, so a live lease-holding runner read back `idle` from `--status` for up to 30 min — the same bug s1.3 fixed in `_sleep_for_reset`. Mirrored that cadence.
  - `[medium]` `[patch]` The gate was read at the launch-loop head but not after `launch_interval` + the TPM window + `await sem.acquire()`, so a row could launch minutes later into a live migration. Re-checked beside the existing `quota_exhausted` re-check, before any budget is consumed.
  - `[medium]` `[patch]` A blocked pass still ran `fetch_candidate_rows` + `_census` against the migrating DB, where an `ACCESS EXCLUSIVE` lock-wait could stall it past its lease TTL. Added an early gate read at the top of `_run` (a pure optimization — the authoritative beat-then-check stays in `_go`) and skipped the census on a blocked cycle.
  - `[medium]` `[patch]` Every shell test ran `--dry-run`, which returns before `alembic upgrade head` — the DW-3 window itself was untested. Added real-path coverage with a stub `alembic` (key held while alembic runs, released after, renewed across a long upgrade) plus a script/config prefix-parity test.
  - `[medium]` `[patch]` The headline AC ("never both proceed") was argued in prose in four places and tested nowhere. Added a joint-property test driving both halves against one shared fake Redis in both interleavings.
  - `[low]` `[patch]` `--dry-run` took the production lock for the 1-2s its probes cost, bouncing a runner starting in that window to exit 8 for a command that by contract changes nothing. Now a read-only probe that reports both keys and takes nothing.
  - `[low]` `[patch]` A blocked pass logged identically to an ordinary empty pass. `migration_blocked` now appears in the `backfill_cycle_done` structured log, the `[cycle N]` line and the single-pass output.
  - `[low]` `[patch]` `test_migration_gate_reads_with_get_not_exists` asserted `not hasattr(r, "exists")` — a property of the test double, not the gate (coverage theater by this project's own rules). Replaced with the real requirement.
  - `[low]` `[patch]` The feature doc claimed "one writer at a time on the primary DB" though in-flight rows deliberately drain, and named a story-1.5 caller that does not exist while omitting the real ungated writer. Corrected both.
  - `[low]` `[patch]` The `migration_wait_seconds` comment asserted a cross-language coupling to the script's TTL that an operator breaks with `MIGRATE_LOCK_TTL_SECONDS`. Reworded to name the env var and the cost of divergence.

### 2026-08-11 — Review pass (follow-up)

- intent_gap: 0
- bad_spec: 0
- patch: 9: (high 1, medium 4, low 4)
- defer: 2: (high 0, medium 2, low 0)
- reject: 9
- addressed_findings:
  - `[high]` `[patch]` The renewal watchdog outlived a hard-killed migration. SIGKILL runs no `EXIT` trap, so the orphaned subshell kept re-`EXPIRE`ing `:migrating` **forever** — directly contradicting the edge-case matrix row that says a hard-killed migration self-clears on its TTL, and wedging every backfill behind a key the contract forbids deleting by hand. The watchdog now checks its owner pid every second and exits with it; covered by a SIGKILL regression test.
  - `[medium]` `[patch]` `migration_wait_seconds` was spent down over the runner's whole lifetime and never reset, so a multi-day `--continuous` run gave its entire budget to the first migration and then exited 8 instantly on every later one — on keys that were about to clear. The budget now bounds one stretch of consecutive blocked cycles and restarts after any cycle that ran.
  - `[medium]` `[patch]` A migration-blocked runner published `BACKING_OFF`, which in this wire vocabulary means "the provider refused on quota" — sending an operator (and stories 1.5/1.6) to the Gemini dashboard over a migration in their own terminal. Added `BackfillState.BLOCKED`, published it from the wait's first poll (it was one 30s refresh interval in, so `--status` read a live lease-holding runner as `idle`), and stopped exit-8 runs from stamping `backing-off` on the way out.
  - `[medium]` `[patch]` The shell test's fake `redis` was not a store: `get` always returned `None`, so NX, the renewal CAS and the post-upgrade ownership re-check were all unassertable — and the "idle" happy path printed *"the upgrade ran part of the time without mutual exclusion"* on every green run with no test noticing. Replaced with a file-backed fake carrying real NX/CAS semantics, plus tests for the lock-lost warning and for the key surviving a refused invocation.
  - `[medium]` `[patch]` The post-alembic ownership check sat after `ok "...migrated to head"` on a `set -e` script, so a *failed* upgrade — the case where "was this guarded?" matters most — skipped it and exited. The upgrade's status is now captured and reported after the check, preserving alembic's own exit code.
  - `[medium]` `[patch]` The watchdog ran `state="$(renew_migration_lock)"` under `set -e`: any failure to launch the renewal (interpreter gone, OOM-killed child) killed the loop silently and the lock lapsed mid-upgrade with nothing said. Now tolerated and warned about.
  - `[low]` `[patch]` A stop request arriving on the timing-out iteration of the migration wait (including every stop when `migration_wait_seconds` is 0) was never observed, so it was neither honored nor cleared and stayed pending for its 7-day TTL. The stop check now precedes the timeout return.
  - `[low]` `[patch]` `MIGRATE_LOCK_TTL_SECONDS` was unvalidated: `0` made redis reject `ex=0`, which the blanket `except` reported as *"is the primary Redis up?"* — blaming healthy infrastructure for an operator typo — and a non-numeric value aborted on the watchdog's arithmetic with no message at all. Validated up front.
  - `[low]` `[patch]` Redis clients in the script set `socket_connect_timeout` but no `socket_timeout`, so a connected-but-unresponsive server could wedge the release inside the `EXIT` trap and stop the script exiting at all. Added; also `remaining` is logged as `None` rather than the string `"unmeasured"` in an otherwise-int field, `--status` now names the migration holder, and the gate's read test no longer pins an exact call count (coverage theater by this project's rules).
- Deferred (appended to `deferred-work.md` as **DW-8**, **DW-9**; existing entries untouched): the script's hardcoded Redis endpoint/key literals vs the runner's `REDIS_URL` + `redis_prefix` (any divergence silently disables both halves), and the `:active` heartbeat's per-completed-row cadence (a slow row lets it lapse under a live writer, capping what this exclusion can guarantee).
- Rejected: `--dry-run` no longer exiting 1 on a live heartbeat (documented contract of the new read-only probe; no automation consumes it); the ~1-2s a *refused* invocation holds `:migrating` bouncing a live runner (inherent to set-then-check, and the matrix specifies the acquire-first order); the joint-property test modelling the script's two steps in Python (the real ordering is asserted against the actual script in the shell test); the renewal test's timing margin; unguarded gate reads dying on a Redis blip (identical to the pre-existing `control.should_stop()` reads in the same loop); `_migration_holds()` preceding `_lease_held()` in the pause poll (right outcome, discovered one renew tick later); re-acquiring the lock after a lost CAS (would claim exclusion a runner may already have taken); the suspend-clock accumulator (`monotonic` alone is the stronger of the two bounds here); and the status metadata disagreeing across spec/sprint-status/feature-doc (harness-owned, mid-run).

## Design Notes

**Why set-then-check on both sides is sufficient.** The migration does `SET :migrating NX` at t1 then reads `:active` at t2 > t1. The runner does `SET :active` at t3 then reads `:migrating` at t4 > t3. Suppose the runner does *not* see `:migrating`; then t4 < t1, so t3 < t4 < t1 < t2 and the migration reads `:active` after it was written — the migration refuses. Symmetric in the other direction. Both may refuse in a narrow interleaving; that is safe, and `--continuous` recovers by waiting. This is why the pass-entry check must come **after** `heartbeat.beat()`, and the script's acquire must come **before** its probe.

**Pass entry is the wake-up gate.** Every `_run_continuous` cycle funnels through `_run` → `_go`, so the check in `_go` (after the beat, inside the existing `try` whose `finally` clears the heartbeat) is exactly "at wake-up from `_sleep_for_reset`, before it resumes launching rows". `_sleep_for_reset` itself is deliberately left unchanged — a sleeping runner writes nothing, so only the resume needs gating.

**Read with `get`, not `exists`.** The key always carries a non-empty token, so `bool(redis.get(key))` is equivalent, works with the minimal fakes the backfill tests already use, and lets the refusal message name the holding token.

**Dry runs are not gated, on either side.** The runner's `--dry-run` takes no lease and no control keys because it writes nothing, and the migration gate follows the same rule. The *script's* `--dry-run` likewise never takes the lock — it probes both keys read-only and reports what a real run would do. Taking a production key for the second its probes cost would bounce a runner starting in that window over a command that by contract changes nothing.

**The lock is renewed, so its TTL is not a cap on migration length.** `SET NX EX` alone made `MIGRATE_LOCK_TTL_SECONDS` an undocumented ceiling on how long an upgrade could safely run: past it the key expires, a waiting runner sees a free guard and resumes writing into live DDL. A background watchdog re-`EXPIRE`s by the same owner token every TTL/3 and is killed from the EXIT trap. It never aborts a running alembic on a failed CAS — a half-applied migration is worse than an unguarded one — it warns, and the script re-checks ownership once alembic returns so an operator never has to infer from scrollback whether the upgrade was guarded throughout.

**Shell release sketch** (token CAS, so a refused invocation never deletes the holder's key):

```bash
release_migration_lock() { ... eval "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('del',KEYS[1]) end return 0" ... }
trap release_migration_lock EXIT   # armed BEFORE the acquire probe runs
```

## Verification

**Commands:**
- `bash scripts/agent/validate.sh backend` -- expected: green (lint + unit + integration + contract; new unit tests pass, `alembic check` unaffected — no schema change)
- `bash scripts/agent/migrate-primary.sh --dry-run` -- expected: from the primary checkout, reports the idle guard and exits 0 leaving no `backfill:gemma:migrating` key behind
- `bash scripts/agent/validate.sh all` -- expected: green, run by `finish-feature.sh` before the merge

**Manual checks (operator, against the primary stack — not runnable from an agent worktree):**
- With `redis-cli -p $REDIS_PORT set backfill:gemma:migrating tok ex 60`, `python scripts/dev/backfill_gemma.py --limit 1` refuses with exit 8 and enriches nothing; after `del`, it runs normally.

## Auto Run Result

Status: done — a second, independent review pass over the same diff (baseline `45986fbe`), findings
verified against the code, patched, and re-validated. Committed on
`bmad-loop/20260810-193244-9de6/dw-migration-backfill-mutual-exclusion`; **not merged, not pushed**
(the bmad-loop orchestrator owns finishing).

**Change.** The feature itself is unchanged: `migrate-primary.sh` and the Gemma backfill runner are
mutually exclusive through the migration-held Redis key `backfill:gemma:migrating`, set-then-check on
both sides (DW-3 / DW-4). This pass hardened the edges around it. The headline defect was in the
renewal watchdog added by the previous pass: a `SIGKILL`ed migration runs no `EXIT` trap, so the
orphaned subshell kept renewing `:migrating` **forever** — the key the spec's own edge-case matrix
promises "self-clears within its TTL" would have blocked every backfill indefinitely, behind a
contract that forbids deleting it manually. The wait path was also made honest: its budget no longer
decays over a runner's lifetime, and a blocked runner reports a new `blocked` control state instead of
`backing-off` (which in this vocabulary means a provider quota refusal).

**Files changed in this pass**

- `scripts/agent/migrate-primary.sh` -- watchdog exits with its owner pid; renewal failure no longer kills the watchdog under `set -e`; the ownership re-check runs on the alembic *failure* path too (preserving alembic's exit code); `MIGRATE_LOCK_TTL_SECONDS` validated; `socket_timeout` on every embedded client.
- `src/core/backfill_runner.py` -- NEW `BackfillState.BLOCKED`.
- `scripts/dev/backfill_gemma.py` -- migration-wait budget resets after a cycle that ran; publishes `BLOCKED` from the wait's first poll; stop observed before the timeout return; exit 8 no longer stamps `backing-off`; `--status` reports the migration holder; `remaining` logged as `None`, not `"unmeasured"`.
- `src/infra/config.py`, `configs/app_config.yaml` -- `migration_wait_seconds` documented as a per-blocked-stretch bound.
- `src/tests/unit/test_migrate_primary_guard.py` -- the fake `redis` is now a file-backed store with real NX/CAS semantics (the old one made NX, the renewal CAS and the ownership check unassertable, and printed an "unguarded upgrade" alarm on every green run); NEW tests for the SIGKILL orphan, a lock lost mid-upgrade, a failed upgrade, and an invalid TTL.
- `src/tests/unit/test_backfill_gemma_completion_cli.py` -- NEW budget-reset and no-false-quota-backoff tests.
- `src/tests/unit/test_backfill_control.py` -- gate read test no longer pins an exact call count.
- `docs/features/v0.13-fu6-migration-backfill-mutual-exclusion.md` -- new behaviour documented; the `--status` follow-up note replaced with the (real) Redis-endpoint drift note.

**Review findings.** Two independent reviewers (adversarial + edge-case) on the full diff. 0 intent
gaps, 0 spec defects. 9 patches applied (1 high, 4 medium, 4 low); 2 deferred to the ledger as
**DW-8** / **DW-9**; 9 rejected — see the Review Triage Log for each and why.

**Verification.** `bash scripts/agent/validate.sh backend` **green** on the committed tree:
pre-commit (all files) + eslint, **1657 unit** passed, **90 integration**, **32 contract**,
`alembic check` clean (the PostGIS system-table output is the gate's known informational case; it
reports OK). Every new test was confirmed to **fail without the fix**: with the three source files
stashed, `validate.sh fast` failed exactly the five new assertions (including "the renewal watchdog
outlived the migration it was renewing for") and passed with them restored. `validate.sh all` was not
run — `finish-feature.sh` runs it before any merge. The operator checks against the live primary
stack (`migrate-primary.sh --dry-run`, the `redis-cli` round-trip) were **not** executed: the primary
stack is off-limits from an agent worktree.

**Residual risks.**

- The shell guard is still exercised against a *fake* `redis` and a *stub* `alembic`. The fake now has
  real NX/CAS/expiry-free store semantics, but it is not Redis: the live round-trip remains an
  operator check.
- Mutual exclusion is still only as good as the heartbeat's liveness (DW-9) and the two halves still
  have to be pointed at the same Redis by hand (DW-8).
- `BackfillState.BLOCKED` extends the wire vocabulary stories 1.5/1.6 will read. It is additive and
  those stories do not exist yet, but whoever builds them must handle it.
- The SIGKILL regression test drives real processes and real 1s sleeps (~7s). It is deterministic in
  what it asserts (renewal count after the kill) but it is the slowest unit test in the file.
- `.cursor/rules/imoveis-core.mdc` (untracked, primary checkout only) still carries the old one-line
  `migrate-primary.sh` description. Mirror the `CLAUDE.md` edit into it **after** this branch merges.
