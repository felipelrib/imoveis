---
title: 'The daily budget must count requests, not properties'
type: 'bugfix'
created: '2026-08-12'
status: 'awaiting-operator'
baseline_revision: 'c134c0fca4a86e056a9904c70d59946dbc046953'
final_revision: '5cec437'
review_loop_iteration: 1
followup_review_recommended: true
operator_actions:
  - 'Start Docker Desktop on the Windows host and enable WSL integration for this distro. The daemon is down (`docker` is not a usable binary in this distro), which is the only reason the full gate could not run.'
  - 'With Docker up, re-run `bash scripts/agent/validate.sh all` from this worktree and confirm it is green — this is the one acceptance criterion this run could not verify. It is also the first execution of the 6 new real-Redis tests in `src/tests/integration/test_backfill_lua_scripts.py` and of the amended budget assertion in `src/tests/contract/test_api_contract.py`. Expect the two `test_no_data_destroying_scripts.py::test_volumes_flag_is_refused_not_silently_ignored[stop.sh|clean.sh]` failures to disappear: they shell out to `stop.sh --volumes`, which aborts with "docker is not running" before printing the refusal they assert, and they fail identically on the untouched baseline.'
  - 'Let the bmad-loop orchestrator merge this branch. `finish-feature.sh` refuses it ("branch does not have a valid conventional type prefix"), as it does every `bmad-loop/<run>/<story>` branch — do not merge by hand.'
  - 'After the merge lands on `main` and is pushed, set `3-3-budget-counts-requests: done` in `_bmad-output/implementation-artifacts/sprint-status.yaml` (it is `in-progress` now).'
  - 'Optionally prove the reconciliation against the live provider, which no agent can do here: run one `scripts/dev/backfill_gemma.py` pass over a handful of properties and confirm the `backfill_progress` journal line shows `requests_consumed` above `requests_reserved` whenever `retry_count` is non-zero, and that `--status` reports the same consumed figure.'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-3-context.md'
warnings: ['oversized']
---

<intent-contract>

## Intent

**Problem:** The launch loop charges the daily budget a flat `requests_per_property` (3) per row — `budget.try_consume(requests_per_property)` (`src/core/backfill_runner.py:1953`) — and never reconciles it, while one property is 3 stages × up to 3 JSON attempts (`_run_json_retry_loop`, `client.py:506,511`) × up to 5 HTTP attempts (`GeminiClient.max_retries`, `client.py:969,1171`) = up to **45** real requests and as few as **2**. `429` is in `_RETRY_STATUS` (`client.py:949`), so the undercount is worst exactly when the account is already throttled: AC-1's never-exceed guarantee is atomic and correct about a quantity that is not the provider's RPD (DW-18).

**Approach:** Keep the flat reservation as a *forecast* and add reconciliation against reality. `DailyBudget` gains `settle(delta)` — a second atomic Lua step on the same key that adjusts the live window's `count` up or down, never opening or rolling a window. `run_backfill` takes an injected `request_counter` callable (the client's monotonic `request_count`, `client.py:988,1172`), and after every finished row settles the difference between the requests actually sent and what this run has charged, keeping a forecast reserved for rows still in flight.

## Boundaries & Constraints

**Always:**
- The counter's unit becomes **provider HTTP requests**. `request_count` alone is that quantity — it is incremented once per attempt at the top of the retry loop (`client.py:1171-1172`), so retries are already inside it; `retry_count` is a diagnostic *subset* and adding it would double-count.
- `settle` never opens a window, never rolls one, and never writes `start`/`start_epoch`. No live window ⇒ no-op returning `False` (those requests belong to a window that has already reset). The reserve script's limit-check and phantom-window deletion must stay unreachable from `settle`.
- `settle` may push `count` **past** `daily_limit` — an overshoot already happened and hiding it would re-create DW-18 in the reporting layer. It can never *grant* anything: `try_consume` still refuses on `count > limit`, `remaining()` still floors at 0 (`backfill_runner.py:242`), and `BackfillCard.tsx:127-132` already clamps the percentage for exactly this case.
- Reconciliation keeps a forecast reserved for in-flight rows, so the charge is never *below* reality: target = `observed + inflight × requests_per_property`. With `concurrency: 1` the in-flight term is 0 at every settle and the reconciliation is exact.
- `src/core/backfill_runner.py` learns the count through an injected `Callable[[], int]`, exactly like `is_quota_error` / `is_degraded_error` — **no new `core` → `adapters`/`api` import** (AD-1).
- `request_counter=None` (the default) reproduces today's behaviour byte-for-byte: flat charge, no settle. Local backends have no such counter (`OllamaClient`/`LMStudioClient`/`RoutingAIClient` expose none) and must keep working.
- The reservation stays atomic and its rollback path untouched: `_BUDGET_RESERVE_LUA` (`:145-172`) is not edited, and every assertion in `src/tests/integration/test_backfill_lua_scripts.py` still holds verbatim.
- A settle failure (Redis blip) is logged and swallowed — it never aborts a row, never skips `sem.release()`, never raises out of `_worker`.
- `backfill.daily_request_budget`'s documented meaning in `configs/app_config.yaml` and `src/infra/config.py` says **requests actually sent**, and states that ~4,600 properties/day is now a best-case figure because retries spend real budget.

**Block If:**
- Making the reported `consumed` truthful would require adding or renaming a field on `BackfillBudgetModel` / `BackfillStatusResponse` (`src/api/schemas.py:256-270`) — a wire-contract change this story does not own. (It does not: only the `consumed + remaining == limit` *assertion* changes, to the equivalent-in-domain `remaining == max(0, limit - consumed)`.)
- Reconciliation cannot be expressed without `src/core/` importing the AI client.

**Never:**
- Do NOT change the *values* of `daily_request_budget` (14000) or `requests_per_property` (3) — `src/tests/unit/test_config.py:673-680` pins both against the shipped YAML. Only their documented meaning changes.
- Do NOT clamp, cap or otherwise silence a recorded overshoot anywhere except the two floors that already ship (`remaining()`'s `max(0, …)` and the frontend percentage clamp).
- Do NOT touch `checkpoint.advance` (story 3.4), the degraded/circuit-breaker machinery or `AttemptLedger` semantics (story 3.2), `_migrate_start_epoch`'s rule, the quota classification path, the TPM `TokenBudget`, the scrapers, the primary docker stack, or the live Celery routing.
- Do NOT add a per-row attribution scheme: the client is shared across `concurrency` tasks in one event loop (`backfill_gemma.py:695,799`), so `after - before` around one row is not that row's spend. Reconcile the aggregate.
- Do NOT weaken `src/tests/integration/test_backfill_lua_scripts.py` or `src/tests/unit/test_backfill_control.py`'s budget locks — extend them.
- Do NOT reset or re-key an existing budget hash on upgrade (that is precisely how a run gets a second day's spend).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Under the forecast | row reserved 3, client sent 2 (no description) | settle(-1); window `count` drops by 1; `requests_consumed == 2` | No error expected |
| At the forecast | row reserved 3, client sent 3 | delta 0 → no Redis call; `count` unchanged | No error expected |
| Heavy-retry row | row reserved 3, client sent 21 | settle(+18); `count` reflects 21; the next `try_consume` sees the real headroom | No error expected |
| Fails before sending | row reserved 3, client sent 0 (row errored pre-call) | settle(-3): the forecast is given back in full | Row still counts as an error as today |
| Over the cap | reconciliation pushes `count` past `daily_limit` | `count` records the overshoot; `remaining()` reads 0; next `try_consume` refuses → `budget_exhausted` → `--continuous` sleeps to the reset | No error expected |
| In flight, `concurrency > 1` | A finishes (5 sent), B still running | target = `observed + 1 × 3`, so B keeps a forecast; when B finishes the charge equals the real total exactly | No error expected |
| Window rolls mid-run | settle finds no live window | settle returns `False`, writes nothing; the run resets its window accounting base and keeps going | Not an error; logged once |
| Redis raises on settle | `eval`/`hincrby` throws | logged via `_log_budget_settle_failed`; the row completes, progress ticks, `sem.release()` still runs | Swallowed |
| Refund below zero | cumulative refunds exceed `count` | `count` floors at 0, never negative | No error expected |
| No counter injected | `request_counter=None` (local backend, existing tests) | flat charge only, zero settles — behaviour identical to today | No error expected |
| Legacy hash on upgrade | window opened by the old flat-charging code (`count=300`, legacy `start` only) | `_migrate_start_epoch` backfills `start_epoch`, the window continues, settles land on top of 300 — no roll, no second day | No error expected |
| Dry run | `--dry-run` | projects with the flat forecast and settles nothing (no requests are sent) | No error expected |

</intent-contract>

## Code Map

- `src/core/backfill_runner.py:145-172` -- `_BUDGET_RESERVE_LUA`; read-only, the model for the new script.
- `src/core/backfill_runner.py:175-235` -- `DailyBudget.__init__`, `_key`, `_migrate_start_epoch`, `_active_window`.
- `src/core/backfill_runner.py:238-318` -- `consumed`/`remaining`/`try_consume` (atomic + non-atomic fallback)/`seconds_until_reset`; `settle` goes beside `try_consume` with a matching fallback.
- `src/core/backfill_runner.py:101-118` -- `_reply_is_true`, `_decode`; reused for the settle reply.
- `src/core/backfill_runner.py:1240-1300` -- `BackfillResult` + `to_dict`.
- `src/core/backfill_runner.py:1419-1445` -- `run_backfill` keyword-only signature (`requests_per_property`, the injected predicates).
- `src/core/backfill_runner.py:1708-1806` -- `_worker`: the three except branches, the `else`, and the `finally` whose top is where reconciliation belongs (before `on_progress`).
- `src/core/backfill_runner.py:1948-1967` -- launch loop: `try_consume`, `ledger.record_attempt`, `result.requests_consumed +=`, `create_task(_worker(prop))`.
- `src/core/backfill_runner.py:1390-1414` -- `_run_dry`; forecast-only, unchanged.
- `src/core/backfill_runner.py:1883-1958` (log helpers) -- lazy `get_logger` pattern for `_log_budget_settle_failed` / `_log_budget_window_rolled`.
- `src/adapters/ai/client.py:988-990,1171-1172` -- `request_count` / `retry_count` and the increment site (per HTTP attempt).
- `scripts/dev/backfill_gemma.py:695,777-803` -- client construction, `_on_progress` logging, the single `run_backfill` call site.
- `scripts/dev/backfill_gemma.py:562-592,1114-1130,1319-1382` -- `--status` budget line, the `--continuous` budget guard, and the back-off / window-roll / stall branches (`rpd_spent = headroom < requests_per_property`).
- `configs/app_config.yaml:338-350` + `src/infra/config.py:125-153` -- `daily_request_budget` / `requests_per_property` and their comments.
- `src/tests/unit/test_backfill_control.py:100-147,357-475` -- `FakeRedis`/`EvalRedis` doubles and the budget locks to extend.
- `src/tests/integration/test_backfill_lua_scripts.py:54-146` -- real-Redis atomicity + the never-exceed contention test.
- `src/tests/contract/test_api_contract.py:656` -- the budget arithmetic assertion.

## Tasks & Acceptance

**Execution:**
- [x] `src/core/backfill_runner.py` -- add `_BUDGET_SETTLE_LUA` and `DailyBudget.settle(delta: int) -> bool` (atomic branch + non-atomic fallback mirroring `try_consume`): no live window ⇒ return `False` writing nothing; otherwise `hincrby count delta`, floor at 0, refresh TTL, return `True`. Delta 0 short-circuits.
- [x] `src/core/backfill_runner.py` -- `run_backfill(..., request_counter: Optional[Callable[[], int]] = None)`; snapshot the counter at run start; in `_worker`'s `finally` (ahead of `on_progress`) reconcile `target = observed + inflight × requests_per_property` against the units this run has charged and `settle` the difference; track in-flight rows; on `settle` returning `False` reset the window accounting base and log once. Wrap the whole reconciliation so no failure escapes.
- [x] `src/core/backfill_runner.py` -- `BackfillResult.requests_reserved` (flat forecast, monotonic) alongside `requests_consumed`, now the reconciled real count; both in `to_dict`. Add `_log_budget_settle_failed` / `_log_budget_window_rolled`.
- [x] `scripts/dev/backfill_gemma.py` -- pass `request_counter` into `run_backfill`, derived from the client only when it exposes `request_count` (local backends keep the legacy path); log `requests_reserved` next to `requests_consumed` in `_on_progress`; note in `--status`/ETA that the properties-per-day figure is a best-case conversion.
- [x] `configs/app_config.yaml` + `src/infra/config.py` -- restate `daily_request_budget` as *requests actually sent to the provider (retries included)* and `requests_per_property` as the *launch forecast* reconciled after each row; values unchanged.
- [x] `src/tests/unit/test_backfill_request_reconciliation.py` -- NEW; TDD over every matrix row that belongs to `DailyBudget.settle` and `run_backfill` (under/at/over the forecast, heavy retries, fail-before-send, over the cap, in-flight with `concurrency=2`, window roll mid-run, Redis raising, refund floor, `request_counter=None` parity, legacy hash continuation), against both `FakeRedis` and `EvalRedis`.
- [x] `src/tests/integration/test_backfill_lua_scripts.py` -- extend: `settle` never opens a window; concurrent settles lose no update; a recorded overshoot blocks the next reservation; never-exceed re-derived against the reconciled quantity.
- [x] `src/tests/unit/test_backfill_gemma_cli.py` -- extend: a pass whose real requests exhausted the window takes the sleep-to-reset branch (not the stall branch), and `--continuous`'s budget guard still rejects `--daily-budget` below `requests_per_property`.
- [x] `src/tests/contract/test_api_contract.py` -- replace `consumed + remaining == limit` with `remaining == max(0, limit - consumed)` (identical in-domain, correct once an overshoot is recordable).
- [x] `docs/features/v0.13-s3.3-budget-counts-requests.md` -- feature doc from `docs/features/_template.md` (all sections), including what an operator sees when a retry storm spends the day early.
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` -- close DW-18 with the resolution (`status: done 2026-08-12`).

**Acceptance Criteria:**
- Given a backfill pass against a client that retried heavily, when the pass ends, then the window's `count` equals the client's real `request_count` delta for that pass, and `BackfillResult.requests_consumed` reports that same number rather than `3 × properties`.
- Given the reconciled counter reaches `daily_request_budget`, when the launch loop tries the next row, then `try_consume` refuses, `budget_exhausted` is set, and `--continuous` sleeps to the window reset instead of taking the stall branch.
- Given `src/tests/integration/test_backfill_lua_scripts.py` under real contention, when reservations and settles race, then no update is lost and the never-exceed guarantee holds against the reconciled quantity.
- Given a budget hash written by the pre-story runner, when the new code attaches mid-window, then the window continues (no roll, no reset) and no run receives a second day's spend.
- Given `bash scripts/agent/validate.sh all`, when it runs, then it is green and `git grep -n "from adapters" src/core/backfill_runner.py` still returns nothing (AD-1).

## Spec Change Log

## Review Triage Log

### 2026-08-12 — Review pass (iteration 1)

- intent_gap: 0
- bad_spec: 0
- patch: 16: (high 0, medium 4, low 12)
- defer: 3: (high 0, medium 2, low 1)
- reject: 2: (high 0, medium 0, low 2)
- addressed_findings:
  - `[medium]` `[patch]` `result.requests_consumed` was assigned *below* `budget.settle()` inside the same `try`, though it needs no Redis at all — so one settle blip reported a pass that really sent 18 requests as having sent **0**, DW-18's own lie in the field an operator reads. Moved above the settle (one `request_counter()` call now serves both), and the blip test, which asserted everything except that number, now pins it.
  - `[medium]` `[patch]` `_reconcile_requests()` sat *outside* the `try` whose entire purpose is guaranteeing `sem.release()`. It catches `Exception`, but its handler logs, and a raise out of an `except` (BIN-87's LogRecord collision is exactly that shape) would skip the release and hang the run at 100% lease retention. Moved inside the guard, ahead of the progress hook.
  - `[medium]` `[patch]` A window rolling mid-run **discarded** the spend the refused settle was carrying (`charged, observed_base = 0, request_counter()`): up to one row's real requests charged nowhere. Now only `charged` re-anchors — the spend stays pending and the next window absorbs it. That over-charges the new window by at most the in-flight set instead of under-charging by it, and under-charging is the one direction that can push a real account past its RPD.
  - `[medium]` `[patch]` `--continuous` slept out the whole ~24h window on a pass that ended `budget_exhausted` even when drain-phase refunds had since restored headroom — a state only reconciliation can produce (before it, a refusal was final for the window). It now runs the next pass instead, guarded on `result.processed > 0` so a pass that enriched nothing still falls through to the wait rather than spinning. Two CLI tests, one per side of the guard.
  - `[low]` `[patch]` `window_roll_logged` was never cleared, so a second genuine roll in the same pass was silent. Reset on the next settle that lands.
  - `[low]` `[patch]` `_log_budget_window_rolled` asserted "no requests were lost or re-charged" — an invariant the code never checked, on a path any unreadable reply also reaches. Reworded to state what was observed (no live window took the settle) and what the run did.
  - `[low]` `[patch]` `settle`'s summary line said "`False` = there is no window" while `settle(0)` returns `True` unconditionally. Documented precisely.
  - `[low]` `[patch]` The `EvalRedis` double did `hashes.setdefault(key, {})` *before* its no-window check, materialising an empty hash where real Redis writes nothing — so `assert r.hashes.get("t:budget", {}) == {}` could not tell "no window" from "empty window". Fake reads without creating; the assertion is now key-absence.
  - `[low]` `[patch]` The re-derived never-exceed integration assertion `accepted * 3 <= limit` held with enormous slack and would survive a broken reserve. Dropped for the two assertions that carry the claim (`final + 3 > limit`, `remaining() == 0`).
  - `[low]` `[patch]` `_request_counter_for` failed open in silence: any wiring change reverts the run to pre-DW-18 flat charging, and the only clue would be `consumed == reserved`, which reads as "no retries today". Now logs `backfill_request_counter_unavailable` with the impact.
  - `[low]` `[patch]` `_run_dry` never set `requests_reserved`, so the one mode whose entire output *is* the forecast reported it as 0 beside a non-zero `would_process`.
  - `[low]` `[patch]` `_warn_non_atomic_fallback` latched per object, so the reservation's warning silenced the settle's — the quieter half, since a non-atomic settle loses updates against the counter the reservation is trusted to bound. Latched per surface.
  - `[low]` `[patch]` The feature doc claimed a swallowed settle leaves the run reporting the flat forecast; it reported 0 (the defect above). Corrected, and the window-roll carry-forward documented.
  - `[low]` `[patch]` The new CLI overshoot test claimed more than it proved (`_run` is stubbed, so no story code executes) and carried a dead `assert rc != EXIT_STALLED` implied by the line above it. Docstring now says it locks the *loop's* branching over a state only reconciliation can reach; dead assert removed.
  - `[low]` `[patch]` The window-roll unit test was named and asserted for the discard behaviour; renamed and re-asserted for the carry-forward, with the direction-of-error reasoning recorded.
  - `[low]` `[patch]` `sprint-status.yaml` still had `3-3-budget-counts-requests: backlog` and `epic-3: backlog` with the work committed and story 3-1 already `done`. Both moved to `in-progress` (never `done` — that follows the merge).

Deferred (3, ledger): no pre-launch bound on a row's worst-case cost, so the recorded count can pass the cap by `concurrency × 42` — inside the 14,000/14,400 margin at the shipped `concurrency: 1`, outside it at 10, and pinned by nothing; the RPM pacer and dry-run projection still divide by the flat forecast, leaving the per-minute ceiling with DW-18's mismatch; `requests_reserved` reaches the CLI log but not the wire, so the Operações card cannot show `consumed ≫ reserved`.

Rejected (2): hedging the `--status` "requests sent (retries included)" label because a pre-upgrade window is a mixture — the label describes what the counter means from here on, and permanently qualified operator copy is worse than a one-time transient; and the reservation that rolls the window while earlier rows are in flight leaving the new window short by their forecast — unreachable at the shipped `concurrency: 1` (no rows are in flight at the reservation), bounded by `concurrency × 3` requests against a 400-request margin, and closing it would mean a new `DailyBudget` window-identity accessor for a sub-1% imprecision.

## Design Notes

**Why a second script, not a mode flag on the reserve.** `_BUDGET_RESERVE_LUA` is the object `test_backfill_lua_scripts.py` locks as *the* never-exceed guarantee. A settle must be able to do what a reserve must never do (exceed the cap) and must not do what a reserve must always do (open a window). Branching one script on a flag puts both policies one `if` apart in a file where a mistake overspends a real account; a separate 12-line script keeps the reserve's proof intact.

**Why aggregate reconciliation, not per-row.** One `GeminiClient` is shared by all `concurrency` tasks (`backfill_gemma.py:695,799`) and `request_count` is a single monotonic int, so a per-row `after - before` attributes other rows' retries to whichever row finishes first. Reconciling the *aggregate* — with a forecast still held for rows in flight — is attribution-free, self-correcting, and exact once the last row drains.

```python
# src/core/backfill_runner.py — _worker's finally, before on_progress
if request_counter is not None:
    inflight -= 1
    try:
        observed = request_counter() - observed_base
        target = observed + inflight * requests_per_property
        delta = target - charged
        if delta and not budget.settle(delta):
            charged, observed_base = 0, request_counter()  # window rolled
            _log_budget_window_rolled()
        elif delta:
            charged = target
        result.requests_consumed = request_counter() - run_base
    except Exception as exc:  # a settle blip never aborts a row
        _log_budget_settle_failed(exc)
```

**Why the overshoot is recorded rather than capped.** The provider has already counted those requests; a counter that stops at the cap would under-report exactly the condition this story exists to expose, and the two consumers that could be surprised are already defensive — `remaining()` floors at 0 (`:242`) and `BackfillCard.tsx:127` clamps the percentage with a comment naming retries as the cause.

**Why the old hash needs no migration.** `count`'s unit does not change — it was always nominally "requests"; the old writer simply wrote a wrong number. Carrying it forward is the conservative direction (it can only under-state, never grant), and leaving `_migrate_start_epoch` and the window rule untouched is what keeps an upgrade mid-window from opening a second day (the hazard fu6/1.3 wrote that helper for).

**`--continuous` re-verified.** `rpd_spent = headroom < requests_per_property` (`:1335`) still asks the right question — "can another property be reserved?" — now against a truthful `headroom`. The stall detector stays reachable only when `budget_exhausted` is False; a run whose *last* row overshoots ends normally, and the next cycle is refused at its first reservation, giving `processed == 0` **with** `budget_exhausted` True, which routes to the sleep branch, not the stall exit.

## Verification

**Commands:**
- `bash scripts/agent/validate.sh fast` -- expected: lint + unit green, including the new reconciliation suite.
- `bash scripts/agent/validate.sh backend` -- expected: green; runs the extended Lua integration tests against the ephemeral test-stack Redis.
- `bash scripts/agent/validate.sh all` -- expected: full gate green (also run by `finish-feature.sh`).
- `git grep -n "from adapters\|from api" src/core/backfill_runner.py` -- expected: no matches (AD-1).

**Manual checks (if no CLI):**
- The regression must fail on the pre-fix tree: confirm the "heavy-retry row overshoots the window" test fails when `settle` is not called, not merely that it passes afterwards.

## Auto Run Result

**Status:** `awaiting-operator` — every part an agent can do is implemented, reviewed, patched, committed and verified as far as this host allows. What remains is a host-level action outside the repo: the Docker daemon is down, so `validate.sh all` (and with it the new Lua integration tests and the contract assertion) could not run. See frontmatter `operator_actions`.

**Implemented change.** The cloud backfill's daily budget now counts what the provider counts (DW-18). The flat `requests_per_property` charge stays as a launch-time *forecast*; a new `_BUDGET_SETTLE_LUA` + `DailyBudget.settle(delta)` reconciles it against reality after every finished row. `settle` is deliberately asymmetric to `try_consume`: it never opens, rolls or re-stamps a window (no live window is a no-op returning `False`), and it may push `count` **past** `daily_limit` — an overshoot the provider has already counted, which `remaining()`'s existing `max(0, …)` floor and the frontend's percentage clamp absorb — while never being able to *grant* anything. `_BUDGET_RESERVE_LUA` and every pre-existing assertion locking it are untouched. `run_backfill` learns the real count through an injected `request_counter: Callable[[], int]` fed by `GeminiClient.request_count` (already incremented per HTTP attempt, so retries are inside it; `retry_count` is a subset and would double-count) — duck-typed exactly like `is_quota_error`, so `src/core` still imports nothing from `adapters`/`api`. Reconciliation is on the **aggregate**, never per row: one client is shared by all `concurrency` tasks, so `after - before` around a row attributes other rows' retries to whichever finished first. Each finished row targets `observed + inflight × requests_per_property` and settles the difference — attribution-free, never dipping below reality mid-flight, exact once the last row drains, and exact at every settle at the shipped `concurrency: 1`. `request_counter=None` (the default, every local backend, and `--dry-run`) reproduces the old flat behaviour byte-for-byte.

**Files changed**
- `src/core/backfill_runner.py` — `_BUDGET_SETTLE_LUA`; `DailyBudget.settle()` (atomic + non-atomic fallback); `run_backfill(request_counter=)`; `_reconcile_requests()` inside `_worker`'s release guard; `BackfillResult.requests_reserved` (+ `to_dict`); `_log_budget_settle_failed` / `_log_budget_window_rolled`; `_warn_non_atomic_fallback` latched per surface; `_run_dry` fills the forecast.
- `scripts/dev/backfill_gemma.py` — `_request_counter_for(client)` (attribute-gated, warns when it yields nothing) threaded into `run_backfill`; `requests_reserved` logged beside `requests_consumed`; `--status` budget line reads "requests sent (retries included)" with a best-case ETA label; `--continuous` runs the next pass instead of parking a live window that drain refunds re-funded.
- `src/infra/config.py` + `configs/app_config.yaml` — restated meanings of `daily_request_budget` (requests actually sent) and `requests_per_property` (launch forecast); values unchanged, so `test_config.py`'s pin still binds.
- `src/tests/unit/test_backfill_request_reconciliation.py` (NEW, 20 tests over both fake clients), extended `test_backfill_lua_scripts.py` (6 new real-Redis tests), `test_backfill_control.py` (settle branch in the `EvalRedis` double), `test_backfill_gemma_cli.py` (3 new), `test_api_contract.py` (budget arithmetic).
- `docs/features/v0.13-s3.3-budget-counts-requests.md` (NEW); `deferred-work.md` — DW-18 closed, 3 entries opened; `sprint-status.yaml` — `3-3` and `epic-3` to `in-progress`.

**Review findings.** One pass, two reviewers. 0 intent_gap, 0 bad_spec, **16 patched** (4 medium, 12 low), **3 deferred**, 2 rejected. The four medium patches were real: `requests_consumed` was assigned below the fallible settle, so one Redis blip reported a pass that sent 18 requests as having sent 0 — DW-18's own lie one layer up; `_reconcile_requests()` sat outside the `try` that guarantees `sem.release()`, where a raise from its own log handler (BIN-87's shape) would hang the run holding the lease; a mid-run window roll *discarded* the spend it could not settle, under-charging in the one direction that can pass a real RPD; and `--continuous` parked ~24h on a window that drain refunds had re-funded. Full breakdown in the Review Triage Log.

**Verification**
- `bash scripts/agent/validate.sh fast` — lint **all 12 hooks Passed** + eslint OK; **2075 passed**, 2 failed. Both failures are `test_no_data_destroying_scripts.py::test_volumes_flag_is_refused_not_silently_ignored[stop.sh|clean.sh]`, which shell out to `stop.sh --volumes` and get "docker is not running" before the refusal they assert. Proven independent of this change: `git diff HEAD -- scripts/stop.sh scripts/clean.sh src/tests/unit/test_no_data_destroying_scripts.py` is empty, and story 3.2 recorded the identical pair on this host.
- Pre-fix regression confirmed for the story itself (the implementation pass neutered `_reconcile_requests` and got 16 failures, including `test_a_heavy_retry_row_is_charged_what_it_really_sent` → `assert 3 == 21`) **and** for the highest-severity review patch (moving `requests_consumed` back below the settle reproduces `assert 0 == 18`, then restored).
- `git grep -n "from adapters\|from api" src/core/backfill_runner.py` — no matches (AD-1 holds).
- `bash scripts/agent/validate.sh backend` / `all` — **not run.** Docker Desktop's WSL integration is off, so the ephemeral test stack cannot start. Not claimed as green.
- `validate-ai.sh` — not applicable: no AI prompt or client surface changed (the client is only *read*, through an injected counter).

**Residual risks**
- The integration and contract stages never ran on this host, so the 6 new real-Redis Lua tests and the amended budget-arithmetic assertion are unverified against real Redis / the live app. Everything else is unit-covered.
- A mid-run window roll now over-charges the new window by up to the in-flight set's spend (previously it under-charged by the same amount). That is the deliberate direction — under-charging is what can pass a real RPD — but it costs a little throughput at a boundary a long pass can cross.
- Nothing bounds a single row's worst-case cost *before* launch: the loop still reserves 3 for a row that can spend ~45. Inside the 400-request margin between `14000` and the free-tier 14,400 at `concurrency: 1`, outside it at `concurrency: 10`. Deferred with its options.
- The `--continuous` headroom shortcut skips one `_sleep_for_reset`, which is also where a displaced runner notices a lost lease. Bounded to one extra pass — that pass cannot launch without the lease and sets `lease_lost` at its own loop head — and gated on a live window so the no-window path (where the wait is only `reset_margin`) keeps the old behaviour.
