---
title: 'Background lease renewer for run_backfill (DW-6)'
type: 'bugfix'
created: '2026-08-11'
status: 'done'
baseline_revision: '1e0839712b9ce7c25d3e614f0802f32a7ce02768'
final_revision: 'f1b0931a9fc4ac84df0120562d32cff4f40f47e0'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/project-context.md'
warnings: ['oversized']
---

<intent-contract>

## Intent

**Problem:** `run_backfill` renews the backfill lease only from *event* sites — once per launch-loop iteration (`_lease_held()`, `src/core/backfill_runner.py:1262`), once per pause poll, and once per finished row (`_tick_lease()` in `_worker`'s `finally`). Nothing renews *while a row is in flight*. One property whose enrichment (≈3 cloud calls plus image downloads, each with client-side 429 retries) outlives `backfill.lease_ttl_seconds` therefore lets the lease lapse under a live writer, and a second runner can acquire it and work the same queue. The same gap covers every long await in the loop that is not a row: the launch-interval sleep, the TPM wait, `await sem.acquire()` and the final `gather` drain when only one slow row remains (DW-6).

**Approach:** Run an asyncio background task for the whole body of `run_backfill` that renews the lease on a timer (≈`lease.ttl_seconds / 3`) independent of what the launch loop or the workers are doing. On a `renew()` that returns `False` it flags `BackfillResult.lease_lost` exactly like the existing inline path, and the launch loop stops launching at its next observation point. The task is created only when a `lease` was supplied and is cancelled deterministically in the existing `finally` — *after* the in-flight drain, so the drain is covered too, and without swallowing the drain's exceptions.

## Boundaries & Constraints

**Always:** `src/core/backfill_runner.py` stays framework-free and injectable (AD-1) — no config import, no adapters, the renewer's cadence derives from the injected `lease.ttl_seconds` and its sleep is a parameter. Renewal stays owner-token CAS (`BackfillLease.renew`), so a runner whose lease was taken over can never extend or steal back its successor's key. A Redis blip inside the renewer is logged and the timer keeps ticking — bookkeeping never aborts a run, and never propagates into the launch loop. In-flight rows still always drain: the renewer is cancelled only after `asyncio.gather`, and its cancellation must not replace or suppress an exception the loop or the drain is raising. `result.lease_lost` remains distinct from `result.stopped` (a lost lease is not an operator stop).

**Block If:** closing DW-6 would require changing `BackfillLease`'s key layout, its CAS contract, or the `backfill.lease_ttl_seconds` config bounds.

**Never:** do not touch the `:active` heartbeat cadence or `on_progress` — the heartbeat's own liveness gap is **DW-9**, a separate open ledger entry with different consequences (a paused runner deliberately stops beating `:active`). Do not renew the lease from a thread. Do not change `scripts/dev/backfill_gemma.py`'s sync `_sleep_for_reset` / `_wait_out_migration` renewal loops (they already tick at TTL/3 outside the event loop). Do not remove the existing per-iteration or per-row renewals — they are the loop's *stop* signal as well as a renewal. Do not have the background renewer call `clock()` or `_refresh_state()`. Do not edit `_bmad-output/implementation-artifacts/deferred-work.md` (the orchestrator records resolution).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Single slow row in flight | one row whose `enrich_fn` outlives the TTL; lease held | renewer ticks repeatedly during the row; lease TTL restored each tick; row completes normally | No error expected |
| Long drain | loop exhausted, last workers still running | renewer keeps ticking until after `gather` returns, then is cancelled | No error expected |
| Lease lost mid-row | another runner overwrites the lease key while a row is in flight | renewer sets `lease_lost`, logs, and stops; launch loop launches nothing further; `stopped` stays `False`; the successor's key is never stolen back | Run ends cleanly, checkpoint intact |
| Lease lost while blocked on a launch gate | loop parked in the TPM wait / `sem.acquire()` when the renewer loses the lease | no further row is launched — the flag is re-checked after the acquire, before any budget is consumed | No budget spent on the aborted row |
| Redis blip inside the renewer | `renew()` raises `ConnectionError` | logged; the timer keeps ticking; the run is unaffected and `lease_lost` is not set | Logged, never propagated |
| No lease supplied | `lease=None` | no renewer task is created at all; behavior byte-identical to today | No error expected |
| Loop raises (Redis error in the launch loop) | exception escapes the `for` body | in-flight rows still drain, the renewer is cancelled, and the original exception propagates unchanged | Exception preserved |
| Dry run | `dry_run=True` | returns before any task is created | No error expected |

</intent-contract>

## Code Map

- `src/core/backfill_runner.py` -- CHANGE `run_backfill`: NEW params `lease_renew_interval: Optional[float] = None` (default `lease.ttl_seconds / 3`) and `lease_sleep_fn: SleepFn = asyncio.sleep`; NEW inner coroutine that renews on a timer; the task is created at the head of the existing `try` and cancelled in the inner `finally` after the drain; NEW `result.lease_lost` re-checks at the launch-loop head and after `await sem.acquire()`; NEW `_log_lease_renewer_failed` beside the other log helpers (`:1494+`).
- `src/core/backfill_runner.py:1262` (`_lease_held`) -- REUSED unchanged by the renewer: it is the single place that flags `lease_lost` and logs the loss.
- `src/tests/unit/test_backfill_control.py` -- NEW unit coverage in the lease section (`:925+`), following the file's conventions: `FakeRedis`/`EvalRedis`, plain sync tests calling `asyncio.run(asyncio.wait_for(..., timeout=5))`, `_rows()`, `asyncio.Event`-gated `enrich_fn`.
- `docs/features/v0.13-fu7-backfill-lease-background-renewer.md` -- NEW feature doc from `docs/features/_template.md` (all sections mandatory).
- `_bmad-output/implementation-artifacts/sprint-status.yaml` -- NEW key `v0.13-fu7-backfill-lease-background-renewer`.

## Tasks & Acceptance

**Execution:**
- [x] `src/tests/unit/test_backfill_control.py` -- add failing tests for renewal during a slow row, loss mid-row stopping launches, cancellation on the normal and the exceptional exit paths, and a raising `renew()` not aborting the run -- TDD on `src/core/` per the project testing rules
- [x] `src/core/backfill_runner.py` -- add the background renewer task, its two parameters, the `lease_lost` re-checks and the log helper; extend the `run_backfill` docstring to state which renewals exist and why all of them stay -- the DW-6 fix
- [x] `docs/features/v0.13-fu7-backfill-lease-background-renewer.md`, `_bmad-output/implementation-artifacts/sprint-status.yaml` -- feature doc + minted follow-up story key -- harness-required for every completed change

**Acceptance Criteria:**
- Given a lease with TTL *t* and a single row whose enrichment takes longer than *t*, when `run_backfill` runs it, then the lease key's TTL is refreshed at least once during that row and the run never reports `lease_lost`.
- Given the lease is taken over by another runner while a row is in flight, when the renewer's next tick observes it, then `result.lease_lost` is `True`, `result.stopped` is `False`, no further row is launched, and the successor's key is left untouched.
- Given `run_backfill` returns — normally, after a lost lease, or by propagating an exception raised inside the launch loop — when the caller inspects the event loop, then no renewer task is left pending and the exception (if any) is the original one.
- Given `lease=None`, when `run_backfill` runs, then no background task other than the row workers is created.
- Given `src/core/backfill_runner.py` after the change, when its imports are inspected, then it still imports no `adapters`/`api`/Celery/DB module and the renewer's cadence and sleep are injected values (AD-1).

## Spec Change Log

## Review Triage Log

### 2026-08-11 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 13: (high 0, medium 4, low 9)
- defer: 0
- reject: 9
- addressed_findings:
  - `[medium]` `[patch]` The cancel block swallowed **every** `CancelledError`, so a cancellation delivered to `run_backfill` itself (Ctrl-C, a supervising `wait_for`) while awaiting the renewer made a cancelled run return a result as if nothing had happened. Now only the renewer's own cancellation is swallowed (`if not renewer.cancelled(): raise`).
  - `[medium]` `[patch]` `await lease_sleep_fn(...)` and the yield sat *outside* the renewer's `try`, so a raising caller-supplied sleep killed the timer silently and reopened DW-6 for the rest of the run, observable only after it ended. The whole loop body is guarded now, with a yield after a failed tick so a raising sleep cannot busy-spin either.
  - `[medium]` `[patch]` `lease_renew_interval` was floored but not capped, so a caller could pass an interval beyond the TTL and reinstate the exact lapse this change exists to prevent, silently. It is now clamped to at most `lease.ttl_seconds / 3`.
  - `[medium]` `[patch]` Nothing pinned the `ttl/3` cadence — the six original tests drive the timer through an injected sleep that ignores the interval it is handed, so changing the default to `ttl * 3` kept the suite green. Added a test asserting the interval actually slept for the default, an explicit tighter value, and a clamped absurd one.
  - `[low]` `[patch]` With loss now discoverable mid-row, every still-draining row's `_tick_lease` → `_refresh_state` re-published *this* runner's liveness over the successor's state key — the same thing the closing publish is already guarded against. `_publish` now no-ops once `lease_lost`; covered by a regression test that fails without it.
  - `[low]` `[patch]` A lost lease is terminal, but every draining row (and the timer) re-ran the CAS against a key another runner owns and re-emitted the "stopped launching" warning. `_lease_held()` short-circuits once `lease_lost` is set.
  - `[low]` `[patch]` `backfill_lease_renewer_failed` was emitted for both "one tick blipped, timer still running" and "the timer failed on the way out" with nothing to tell them apart. Added a `renewer_phase` field.
  - `[low]` `[patch]` The only production call site (`scripts/dev/backfill_gemma.py`) still commented that the lease is renewed "once per launch-loop iteration and once per pause poll" — the sentence this change invalidated. Updated (comment only; the sync renewal loops are untouched).
  - `[low]` `[patch]` "Independent of what the launch loop or the workers are doing" overstated the guarantee: the timer is a coroutine on the same event loop, so a blocking section in `enrich_fn` delays the tick like everything else. Docstring and feature doc now say so, and name TTL/3 as the absorbing margin.
  - `[low]` `[patch]` The headline slow-row test depended on an undocumented statement order inside its own fake and would have passed vacuously if the tick preceded the row. Added the `at_row_start >= 0` sentinel and a comment marking the ordering load-bearing.
  - `[low]` `[patch]` `test_no_background_task_is_created_when_no_lease_is_supplied` compared task *counts* across two event loops, proving nothing about which task existed (and built its lease over a different fake Redis than the run used). It now asserts the renewer coroutine by name, on the run's own client.
  - `[low]` `[patch]` "The in-flight row still drained" was vacuous — the row's `enrich` returned immediately, so the assertion held with the drain removed. The row is now gated open only by the timer, which also pins that the renewer is alive *during* the drain.
  - `[low]` `[patch]` The feature doc's file table marked the pre-existing test module `NEW`, elided its own filename, and omitted the CLI comment change; the TTL assertion's dependence on a fake that never expires keys was undocumented. Both corrected.
- Rejected: bounding `await renewer` with a timeout (`lease.renew()` is a *synchronous* Redis call — a hang there stalls the whole event loop, so the timeout could not fire anyway); the `0.05` floor differing from the CLI's `1.0` (different roles — the CLI floors a real `time.sleep`, this floors an injectable timer that tests drive with 0); the TPM reservation charged for a row aborted at `sem.acquire()` (pre-existing and identical for the quota and migration breaks; the run stops launching immediately afterwards, so the trailing window simply decays); the 90-line re-indent (the nested `finally` is precisely what guarantees the cancel if the drain itself raises); the absence of a generic ticker seam for DW-9 (a separate scheduled bundle over a different key, whose paused-runner semantics deliberately differ and whose CLI half is synchronous); the absence of a real-Redis integration test for the timer (the CAS is covered against real Redis by `src/tests/integration/test_backfill_lua_scripts.py`; the live tick stays an operator check, now documented); `v0.13-fu6`'s key still reading `in-progress` (orchestrator-owned post-merge bookkeeping, not this change); this spec's own mid-run frontmatter and empty logs (harness-owned, written by this very step); and the renewer raising a non-`Exception` `BaseException` in the shutdown handler.

### 2026-08-11 — Review pass (follow-up)

- intent_gap: 0
- bad_spec: 0
- patch: 6: (high 0, medium 1, low 5)
- defer: 2: (high 0, medium 2, low 0)
- reject: 17
- addressed_findings:
  - `[medium]` `[patch]` The previous pass's own cancellation guard did not do what it claimed. `await renewer` raises the *renewer's* `CancelledError`, and `renewer.cancelled()` is `True` in both the case it meant to catch and the case it meant to re-raise — a cancellation delivered to `run_backfill` itself while that line is awaiting is therefore consumed by the guard, and the cancelled run returns a normal `BackfillResult`. Both reviewers reached this independently and one reproduced it on a live interpreter. Replaced with `await asyncio.wait({renewer})`, which never re-raises what the awaited task raised, so a `CancelledError` out of that line is unambiguously the caller's and propagates; the renewer's own outcome is read off the task and logged as before.
  - `[low]` `[patch]` The loop-head `result.lease_lost` break claimed it avoided "asking Redis (and logging the loss) a second time" — untrue since the same pass gave `_lease_held()` its own short-circuit on the flag. Comment corrected to what the check actually buys (naming the timer's verdict at that break rather than an ordinary failed renew).
  - `[low]` `[patch]` The `asyncio.sleep(0)` in the renewer's `except` arm was commented "a raising sleep must not busy-spin"; `sleep(0)` yields, it does not delay, so a persistently raising seam still retries at event-loop speed. Comment corrected to state what it guarantees (no starvation) and why the retry rate is acceptable (production's sleep is `asyncio.sleep`; the reachable failure — a raising `renew()` — is paced by the sleep at the top of the loop).
  - `[low]` `[patch]` The renewer docstring described only one direction of the cooperative-scheduling caveat. `lease.renew()` is a synchronous client call, so every tick also blocks the loop — including the rows it protects — for one Redis round trip. Docstring and feature doc now say so.
  - `[low]` `[patch]` The stated reason the *whole* renewer body is guarded (a raising `lease_sleep_fn` would kill the timer silently) had no test; the existing blip test only makes `renew()` raise, a different call site. Added `test_a_raising_sleep_does_not_kill_the_renewer`, where the row is gated open only by the tick *after* the raise.
  - `[low]` `[patch]` The interval test covered default/tighter/slower but not the floor, so `lease_renew_interval=0` (a 20-CAS-per-second Redis spin) was unpinned. Added the `0` and negative cases; the test is renamed to `…_is_clamped_both_ways` to stay honest about what it asserts.
  - `[medium]` `[defer]` DW-10 — the renewer swallows `renew()` failures indefinitely, so a Redis outage longer than the TTL lets the lease genuinely lapse while this run keeps writing. Real, but flagging `lease_lost` on it directly contradicts this spec's intent contract ("logged; the timer keeps ticking; `lease_lost` is not set"), so it is a deliberate later decision, not a patch.
  - `[medium]` `[defer]` DW-11 — after a lost lease, draining rows still `checkpoint.advance()` on a hash the successor now owns, rewinding its `last_property_id` and inflating `processed_total`. Pre-existing (drain-after-loss is older than the timer, which only made the loss observable mid-row) and the fix is a checkpoint-semantics choice, not a review patch.
- Rejected: the loop-head `lease_lost` check being redundant with `_lease_held()`'s short-circuit (it is, harmlessly — the Code Map specifies both re-checks and the comment is now accurate); the missing-yield regression "hanging the suite instead of failing it" (`validate.sh` installs `pytest-timeout` and runs unit tests with `--timeout=30`); the `0.05` floor being tighter than the CLI's `1.0`, the silent clamp of an out-of-range interval, and the absence of a config knob / production caller for it (re-rejected: this is an injectable test seam on a framework-free core function, not an operator knob, and the ceiling is documented); `renewer.exception()` now logging a `BaseException` that previously escaped (consistent with "bookkeeping never aborts a run"); a NaN interval; the phantom TPM reservation on the post-`acquire` `lease_lost` break (re-rejected, unchanged reasoning); `_publish` no-opping without refreshing `last_state_publish`; the un-parameterized `Optional[asyncio.Task]` (matches the neighbouring `list[asyncio.Task]`); the ~200-line re-indent (re-rejected); `EvalRedis` never decaying a TTL and the absence of a real-Redis timer test (re-rejected, documented as the operator check); tests reaching into fake internals, patching `lease.renew`, asserting the renewer by coroutine name and pinning a scheduling interleave (all file conventions, several of them this pass's predecessors' own patches); `phase="shutdown"` having no test (the branch needs a renewer that raises a non-`CancelledError` *while being cancelled* — not reachable without contriving the timer itself); the feature doc's `redis-cli -p "$REDIS_PORT"` (the sibling `v0.13-fu6` doc uses exactly this form — a docs-wide convention, not a defect of this story); the doc header reading `Status: implemented` while sprint-status says `in-progress` (the orchestrator flips the key after the merge) and its `Story:` field using the full sprint-status key (it matches the filename, which is what CLAUDE.md requires); and closing DW-9 by hanging a `control.is_paused()` guard on this timer (the intent contract forbids touching the `:active` cadence here).

## Design Notes

**Why the renewer gets its own sleep function.** `sleep_fn` is the launch loop's pacing seam: the existing unit tests inject counting closures that mutate control/Redis state on the *n*-th poll. A renewer sharing that seam would fire those side effects on its own schedule and silently change what a dozen existing tests exercise. `lease_sleep_fn` defaults to `asyncio.sleep`, so production behavior is unaffected and only the new tests drive it.

**The renewer must yield even when its sleep does not.** An injected `async def sleep(_): return None` never suspends, so `while True: await lease_sleep_fn(i)` would spin without handing control back and hang the loop. The body therefore also awaits `asyncio.sleep(0)` once per tick — a real yield point regardless of what was injected. For the same reason the renewer never calls `clock()`: existing tests inject finite `iter([...])` clocks that a timer loop would exhaust.

**Sketch:**

```python
async def _renew_lease_periodically() -> None:
    while True:
        await lease_sleep_fn(renew_interval)
        await asyncio.sleep(0)          # yield even for a non-suspending sleep
        try:
            if not _lease_held():       # flags result.lease_lost + logs
                return
        except Exception as exc:        # a Redis blip never aborts a run
            _log_lease_renewer_failed(exc)
```

**All three renewal sites stay.** The launch-loop and pause-poll calls double as the loop's *stop* decision, and the per-row `_tick_lease()` also refreshes the published control state (which has a tighter TTL than the lease). The timer is an addition, not a replacement; renewing more often than necessary costs one CAS per tick.

**Cancellation order.** Cancel *after* `asyncio.gather` — a drain of one slow row is precisely a window the timer must cover — and inside a nested `finally`, so it runs whether the loop completed, broke, or raised. The cancelled task is then observed with `asyncio.wait({renewer})`, not `await renewer`: `await` re-raises the renewer's own `CancelledError`, which is indistinguishable from a cancellation delivered to `run_backfill` itself landing on the same line (`renewer.cancelled()` is `True` either way), so catching it there swallows the caller's cancellation. `wait` never re-raises the awaited task's exception, so whatever the renewer ended with is read off the task and logged, and a `CancelledError` escaping that line is unambiguously the caller's.

## Verification

**Commands:**
- `bash scripts/agent/validate.sh backend` -- expected: green (lint over all files + unit + integration + contract); the new unit tests must fail with the renewer removed and pass with it
- `bash scripts/agent/validate.sh all` -- expected: green, run by `finish-feature.sh` before the merge (the orchestrator owns finishing)

**Manual checks (operator, against the primary stack — not runnable from an agent worktree):**
- During a live `python scripts/dev/backfill_gemma.py` pass, `redis-cli ttl backfill:gemma:lease` never decays below roughly two thirds of `backfill.lease_ttl_seconds`, including while a single slow property is being enriched.

## Auto Run Result

Status: done — follow-up review pass over the same delta (baseline `1e08397`), patches applied and
re-validated. Committed on `bmad-loop/20260810-193244-9de6/dw-backfill-lease-background-renewer`;
**not merged, not pushed** (the bmad-loop orchestrator owns finishing).

**Change (DW-6).** `run_backfill` renews the backfill lease from a background asyncio timer running
for the whole body of the call at `lease.ttl_seconds / 3`, instead of only from event sites (per
launch-loop iteration, per pause poll, per finished row). That closes the window the ledger entry
describes: a single property whose enrichment outlives the TTL — and equally the launch-interval
sleep, the TPM wait, `sem.acquire()` and the closing drain — no longer runs on a lease nobody is
refreshing. Losing the lease from the timer flags `BackfillResult.lease_lost` exactly as the inline
path does; the launch loop stops launching at its next observation point (loop head, and again after
`sem.acquire()` before any budget is spent). The task exists only when a lease was supplied and is
cancelled in the existing `finally` **after** the in-flight drain. All three pre-existing renewal
sites stay — they double as the loop's stop decision and the control state's refresh.

**This pass** re-reviewed the whole delta with two fresh reviewers and applied six patches, the only
behavioural one being the shutdown path: the previous pass's cancellation guard
(`await renewer` + `if not renewer.cancelled(): raise`) could not distinguish the renewer's own
`CancelledError` from a cancellation delivered to `run_backfill` while that line was awaiting, so it
swallowed the caller's cancellation and returned a normal result. It is now
`await asyncio.wait({renewer})`, which never re-raises the awaited task's exception; the renewer's
outcome is read off the task and logged.

**Files changed (whole delta)**

- `src/core/backfill_runner.py` -- the renewer task, `lease_renew_interval` (default and hard ceiling `ttl/3`, floor `0.05`) and `lease_sleep_fn` (a seam separate from the loop's `sleep_fn`); `lease_lost` re-checks at the loop head and after `sem.acquire()`; `_lease_held()` and `_publish()` short-circuit once the lease is lost; `_log_lease_renewer_failed(exc, phase=...)`; the shutdown observation via `asyncio.wait`; docstrings covering all four renewal sites and both directions of the cooperative-scheduling caveat.
- `src/tests/unit/test_backfill_control.py` -- nine new unit tests: renewal during a slow row, loss mid-row stopping launches, cancellation on the normal and the exceptional exit paths, a raising `renew()` not aborting the run, a raising `lease_sleep_fn` not killing the timer, no renewer when `lease=None`, nothing published after a loss, and the interval clamped in both directions.
- `scripts/dev/backfill_gemma.py` -- comment only: the call site documented the two renewal sites this change superseded.
- `docs/features/v0.13-fu7-backfill-lease-background-renewer.md` -- NEW feature doc (template verbatim).
- `_bmad-output/implementation-artifacts/sprint-status.yaml` -- NEW key `v0.13-fu7-backfill-lease-background-renewer: in-progress` (the orchestrator flips it to `done` after the merge).

**Review findings (this pass).** 0 intent gaps, 0 spec defects, 6 patches applied (1 medium, 5 low),
2 deferrals appended to the ledger as **DW-10** and **DW-11**, 17 rejected — each with its reason in
the Review Triage Log. No existing ledger entry was read back, reopened or edited.

**Verification.** `bash scripts/agent/validate.sh backend` **green** (exit 0) on the patched tree:
pre-commit over all files + eslint, **1666 unit**, **90 integration**, **32 contract**, `alembic check`
(the PostGIS system-table output is the gate's known informational case; it does not set the exit
code). Both new tests were confirmed to fail without their fix by mutating the source and re-running
`validate.sh fast`: moving the sleep back outside the renewer's `try` failed
`test_a_raising_sleep_does_not_kill_the_renewer` (`TimeoutError`) and removing the interval floor
failed `…_is_clamped_both_ways` (`assert {0.0} == {0.05}`) — exactly those two, 1664 others still
passing. The source was restored byte-for-byte afterwards. `validate.sh all` was **not** run —
`finish-feature.sh` runs it before any merge. The operator check against the live primary stack
(`redis-cli ttl backfill:gemma:lease` during a real pass) was **not** executed: the primary stack is
off-limits from an agent worktree.

**Residual risks.**

- The shutdown fix ships without a deterministic test, for the same reason its predecessor did: the
  window needs a cancellation delivered exactly while the `finally` is awaiting the renewer. What is
  testable — that nothing is left pending on the normal and the exceptional exit paths — is covered.
- The TTL refresh is asserted against the suite's `EvalRedis` fake, which records expirations but
  never decays them. The CAS itself is covered against real Redis by
  `src/tests/integration/test_backfill_lua_scripts.py`; a timer ticking against a live server remains
  the operator check.
- The timer is cooperative, not preemptive, in both directions: a blocking section inside `enrich_fn`
  delays a tick, and each tick's synchronous `lease.renew()` briefly blocks the rows it protects.
  TTL/3 is the margin.
- A Redis outage longer than the TTL is swallowed by design (**DW-10**, deferred), and rows draining
  after a lost lease still advance the shared checkpoint (**DW-11**, deferred).
- The advisory `:active` heartbeat still ticks only per finished row (**DW-9**, open, deliberately
  untouched), so migration exclusion keeps its own liveness gap.
