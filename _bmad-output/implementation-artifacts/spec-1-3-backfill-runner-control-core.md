---
title: 'Backfill runner control core — lease, pause/resume, safe interruption'
type: 'feature'
created: '2026-08-06'
baseline_revision: '06653689c190695b10eadca5e643038a7255ee19'
final_revision: '8022ba90e3ebfa3a4ac8503a51371f2ca54e63f1'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/CLAUDE.md'
warnings: ['oversized']
---

<intent-contract>

## Intent

**Problem:** The Gemma backfill runner (`src/core/backfill_runner.py` + `scripts/dev/backfill_gemma.py`) has no mutual exclusion, no operator control, and two correctness holes that AC-2 of story 1.3 forbids: (a) two concurrent runs would both beat the advisory `backfill:gemma:active` heartbeat and both spend the same daily budget through a non-atomic `hgetall`→`hset` `try_consume`; (b) on provider quota exhaustion the cloud client's persistent 429 is **swallowed** by `analyze_visuals`/`analyze_text` (`except Exception → VisualResult(condition_score=0.5, analysis="Error")`), so `run_enrichment` persists a fabricated 0.5 score, checkpoints the row and counts it processed — silent data corruption instead of back-off-and-wait. There is also no pause/resume/stop the CLI or story 1.5's admin API could share, and the runner picks its cloud client by hardcoding Gemma (`_build_client`, ignoring story 1.1/1.2's `enrichment_routing` map — a second, unrouted backend-decision path AD-13 forbids).

**Approach:** Add three injectable, Redis-backed control primitives to `src/core/backfill_runner.py` — `BackfillLease` (single-instance, `SET NX EX` + owner-token CAS release/renew), `BackfillControl` (pause/resume/stop requests + published `idle|running|paused|backing-off` state for stories 1.4–1.6), and a task-class-expressed scope — make `DailyBudget.try_consume` atomic (`HINCRBY` + rollback), and teach `run_backfill` to honor pause/stop and to treat a provider quota error as back-off (no row error, no ledger attempt, no persisted score) rather than failure. Propagate quota exhaustion honestly by raising a distinguished `AIQuotaExhaustedError` from the cloud transport instead of falling back to a fabricated score, and wire the CLI to acquire/release the lease, expose `--pause/--resume/--stop`, derive its scope + cloud client from `enrichment_routing` via `resolve_enrichment_backend(..., for_backfill=True)`.

## Boundaries & Constraints

**Always:** `src/core/backfill_runner.py` stays framework-free and injectable — Redis, clock, sleep, and the quota-error predicate are all passed in; it gains no `adapters`/`api`/Celery/DB import (AD-1). At most one runner holds the lease; a second start is refused with a message naming the holder and when it was last seen. The daily request count can never exceed `backfill.daily_request_budget` — reservation is a single atomic `HINCRBY` with rollback on overshoot. All enrichment writes keep going through `run_enrichment` (`src/adapters/queue/tasks.py:701`) — second driver, never second writer (AD-10); the runner still does no GPU work and enqueues nothing on the `ai` queue (AD-4). A quota-exhausted call must never persist a score: it propagates, the row stays a `mode=missing` candidate, no checkpoint advance, no ledger attempt charged. Resume stays checkpoint-based and idempotent. Backfill scope is expressed in `EnrichmentTaskClass` values (story 1.1 vocabulary) and translated to the legacy `stages` literal at the edge. `EMBEDDING` is never cloud-eligible even for backfill (read/write vector-space symmetry — deferred item from spec-1-2). Cloud key stays env-only; no hardcoded secrets.

**Block If:** Nothing. The intent is fully resolved from epics.md AC-1/2/3, epic-1-context.md (AD-13/AD-4/AD-10/AD-1) and the code. No operator-only external action is required — the operator-visible config change (below) is documented, not performed by a human mid-story.

**Never:** Do NOT add a local-backend execution mode to the runner (AD-4 requires that path to go through the `ai` queue + GPU semaphore — not this story); refuse to start instead, with an actionable message. Do NOT build admin endpoints, schemas, or UI (stories 1.5/1.6) — this story ships the shared core primitives and the CLI only. Do NOT add coverage/telemetry queries (`src/api/system.py`, story 1.4); the published state key is control state, never a second progress metric. Do NOT change `migrate-primary.sh` or its heartbeat guard (the check-then-act race in `deferred-work.md` stays deferred — closing it needs a paired shell change outside this story's scope). Do NOT touch the primary docker stack, AI prompts, result schemas, or the live Celery routing delivered by story 1.2. Do NOT weaken the existing `AttemptLedger`/`QueueCensus`/TPM behaviour from v0.13-fu2/fu3. Do NOT change `analyze_visuals`/`analyze_text` fallback behaviour for anything except a quota error (local Ollama failures keep their template fallback).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Lease free | no `<prefix>:lease` key | `acquire()` → True, key set to owner token with TTL | No error |
| Lease held | `<prefix>:lease` held by another token | `acquire()` → False; CLI exits `EXIT_LEASE_HELD` printing holder + age | No error, no second runner |
| Lease release by non-owner | key holds a different token | `release()` deletes nothing, returns False | No error (CAS guard) |
| Lease renew keeps ownership | owner token, TTL near expiry | `renew()` → True, TTL extended; non-owner `renew()` → False | No error |
| Budget under cap | limit 10, consumed 6, `try_consume(3)` | True, counter 9 | No error |
| Budget overshoot | limit 10, consumed 9, `try_consume(3)` | False, counter stays 9 (increment rolled back) | No error |
| Budget window roll | window start older than 24h | window reset: count restarts at n, new start stamped | No error |
| Pause requested mid-run | `request_pause()` before row 3 | loop stops launching, publishes `paused`, sleeps on `poll_interval` until resumed/stopped; already-launched rows finish | No error |
| Stop requested mid-run | `request_stop()` | loop breaks, `result.stopped=True`, in-flight rows awaited, state → `idle` on exit | No error |
| Provider quota exhausted | `enrich_fn` raises `AIQuotaExhaustedError` | row NOT counted as error, ledger attempt rolled back, `result.quota_exhausted`/`budget_exhausted` True, no further launches, state `backing-off` | No error, no data written |
| Ordinary row failure | `enrich_fn` raises `ValueError` | unchanged: `errors+1`, ledger error recorded, run continues | Logged, isolated |
| Cloud 429 persists | Gemini/Gemma transport exhausts retries on 429 | raises `AIQuotaExhaustedError`; `analyze_visuals`/`analyze_text`/`_llm_verdict` re-raise it instead of returning a 0.5 fallback | Propagates to runner |
| Scope → stages | `{VISUAL, SENTIMENT, DEAL_VERDICT}` | `"all"`; `{VISUAL, SENTIMENT}` → `"visual+sentiment"`; `{DEAL_VERDICT}` → `"verdict_only"` | Unsupported combo → `ValueError` naming the classes |
| Scope excludes EMBEDDING from cloud | `enrichment_routing.embedding: gemma`, key present, `for_backfill=True` | resolves to local scalar (degrade), never `gemma` | No error, warning logged |
| CLI routing all-local | default `enrichment_routing` (all `ollama`) | CLI refuses to start naming `ai.enrichment_routing.<class>` and `GEMINI_API_KEY` | `SystemExit`, no lease taken |
| CLI mixed cloud backends | `visual: gemma`, `sentiment: gemini` | refuses with a message naming both | `SystemExit`, no lease taken |
| `--status` / `--dry-run` / control commands | any | never acquire the lease (must not block a live run) | No error |

</intent-contract>

## Code Map

- `src/core/backfill_runner.py` -- NEW `BackfillState` (str enum: `idle|running|paused|backing-off` — the wire enum stories 1.5/1.6 publish), `BackfillLease` (`acquire`/`renew`/`release`/`holder`, `SET NX EX` + owner-token CAS via `eval` when the client exposes it, else guarded check-then-act), `BackfillControl` (`request_pause`/`request_resume`/`request_stop`/`clear_requests`/`is_paused`/`should_stop`/`publish_state`/`state`), `DEFAULT_BACKFILL_SCOPE` + `stages_for_task_classes()` + `parse_task_classes()`, `is_quota_exhausted(exc)` default predicate (duck-typed on an `is_quota_exhausted` class attribute, then class-name/message match — no adapter import). CHANGE `DailyBudget.try_consume` to atomic `HINCRBY` + rollback (window roll preserved). CHANGE `AttemptLedger` with `rollback_attempt()`. CHANGE `run_backfill(..., control=None, is_quota_error=is_quota_exhausted, pause_poll_seconds=2.0)`: pause/stop checks in the launch loop, quota classification in `_worker`, stop launching on quota. CHANGE `BackfillResult` with `stopped`, `paused_seconds`, `quota_exhausted`.
- `src/adapters/ai/client.py` -- NEW `AIQuotaExhaustedError(AIClientError)` with `is_quota_exhausted = True`; `GeminiClient.chat_completions` raises it on a terminal 429 / `RESOURCE_EXHAUSTED` body; the `except Exception` fallbacks in `analyze_visuals` / `analyze_text` / `_llm_verdict` (both the Ollama and LMStudio/Gemini branches) re-raise it before falling back. CHANGE `resolve_enrichment_backend`: `EMBEDDING` never honors cloud even with `for_backfill=True` (deferred item from spec-1-2).
- `scripts/dev/backfill_gemma.py` -- `_build_client` resolves the backend per scope task class via `resolve_enrichment_backend(tc, cfg, for_backfill=True)` (all-local or mixed-cloud → actionable `SystemExit`); acquire/release the lease around real runs with periodic `renew()` from `_on_progress`; pass `control` into `run_backfill`; new `--pause` / `--resume` / `--stop` / `--task-classes` flags; `--status` reports lease holder + control state; new exit code `EXIT_LEASE_HELD = 5`; SIGINT/SIGTERM → request stop (clean drain), second signal → default abort; `_run_continuous` treats `result.stopped` as terminal and publishes `backing-off` while sleeping on budget reset.
- `src/infra/config.py` / `configs/app_config.yaml` -- add `backfill.lease_ttl_seconds` (default 900) and `backfill.control_poll_seconds` (default 2.0); document that the cloud backfill now requires cloud `ai.enrichment_routing` entries.
- `src/tests/unit/test_backfill_control.py` -- NEW. TDD for lease/control/scope/quota primitives + `run_backfill` pause/stop/quota branches (dict-backed fake Redis extended with `nx`, plus a no-`eval` and an `eval`-capable fake).
- `src/tests/unit/test_backfill_runner.py` -- extend `FakeRedis` with `nx=`/`hincrby` needs; add atomic-budget overshoot/rollback + window-roll cases.
- `src/tests/unit/test_ai_routing.py` -- add EMBEDDING-never-cloud-for-backfill case.
- `src/tests/unit/test_ai_quota_propagation.py` -- NEW. Terminal 429 → `AIQuotaExhaustedError`; `analyze_visuals`/`analyze_text`/`_llm_verdict` re-raise it; a non-quota error still returns the template/0.5 fallback.
- `src/tests/unit/test_backfill_gemma_cli.py`, `src/tests/unit/test_backfill_gemma_completion_cli.py` -- extend `_FakeRedis` (`set(nx=,ex=)`), cover lease refusal, `--pause/--resume/--stop`, routing-derived client refusal.
- `docs/features/v0.13-s1.3-backfill-runner-control-core.md` -- NEW feature doc from `docs/features/_template.md` (harness-required by `finish-feature.sh`).

## Tasks & Acceptance

**Execution:**
- [x] `src/tests/unit/test_backfill_control.py` -- TDD the I/O matrix rows for lease, control state machine, atomic budget, scope translation and `run_backfill` pause/stop/quota branches against a fake Redis -- pure `src/core/` logic gets tests first.
- [x] `src/core/backfill_runner.py` -- add `BackfillState`, `BackfillLease`, `BackfillControl`, scope helpers, `is_quota_exhausted`; make `try_consume` atomic; add `AttemptLedger.rollback_attempt`; extend `run_backfill`/`BackfillResult` for pause/stop/quota -- single-instance control + never-exceed budget (AC-1), safe interruption (AC-2), task-class scope (AC-3).
- [x] `src/tests/unit/test_ai_quota_propagation.py` + `src/tests/unit/test_ai_routing.py` -- lock the quota-propagation contract and EMBEDDING-never-cloud -- these two are the "never data loss" and vector-symmetry invariants.
- [x] `src/adapters/ai/client.py` -- add `AIQuotaExhaustedError`, raise it on terminal 429, re-raise it past the visual/text/verdict fallbacks, exclude `EMBEDDING` from backfill cloud honor -- a quota-exhausted call must back off, never persist a fabricated 0.5 score.
- [x] `src/infra/config.py`, `configs/app_config.yaml` -- add `lease_ttl_seconds` + `control_poll_seconds` with documented semantics -- config is the single source of truth (NFR-2).
- [x] `scripts/dev/backfill_gemma.py` -- lease acquire/renew/release, control flags, routing-derived client, signal-driven clean stop, `EXIT_LEASE_HELD`, status additions -- CLI is the first consumer of the shared control core; story 1.5's API is the second.
- [x] `src/tests/unit/test_backfill_runner.py`, `src/tests/unit/test_backfill_gemma_cli.py`, `src/tests/unit/test_backfill_gemma_completion_cli.py` -- extend fakes and add lease-refusal / control-command / routing-refusal coverage -- existing suites must keep passing and cover the new CLI seams.
- [x] `src/tests/unit/test_config.py` -- extend the `BackfillConfig` default lock with the two new fields.
- [x] `docs/features/v0.13-s1.3-backfill-runner-control-core.md` -- template-conformant feature doc, including the operator-visible change that the cloud backfill now requires cloud `enrichment_routing` entries.

**Acceptance Criteria:**
- Given a backfill holding the lease, when a second runner starts, then it is refused with a message naming the active run and exits non-zero without enriching anything, and the daily request count never exceeds `backfill.daily_request_budget` under any interleaving of reservations.
- Given a run interrupted by crash, quota exhaustion, or operator pause/stop, when it is restarted or resumed, then it continues from the checkpoint without re-enriching completed rows, and no property was left with a score written from a quota-failed call.
- Given the runner's scope, when rows are selected and enriched, then the scope is expressed in `EnrichmentTaskClass` values, all writes still go through `run_enrichment`, no GPU/`ai`-queue work is introduced, and `src/core/` gains no `adapters`/`api` import.
- Given the AI client surface changed, when the story completes, then `bash scripts/agent/validate-ai.sh` passes and contract tests still hold (AI scores remain floats in `[0.0, 1.0]`).

## Spec Change Log

<!-- Empty: no bad_spec loopback was triggered. -->

## Review Triage Log

### 2026-08-06 — Review pass 1 (patch-level only, no spec/intent loopback)
- intent_gap: 0
- bad_spec: 0
- patch: 23: (high 4, medium 10, low 9)
- defer: 1: (high 0, medium 1, low 0)
- reject: 3: (high 0, medium 0, low 3)
- addressed_findings:
  - `[high]` `[patch]` Lease renewal rode on `on_progress`, which `run_backfill` called only on **successful** rows — a storm of failing rows never renewed, so the 900s lease expired and a second runner could start. Renewal moved into `run_backfill` itself (`lease=` param, ticked once per launch iteration and once per pause poll); `on_progress` now also fires from `_worker`'s `finally`.
  - `[high]` `[patch]` `lease.renew()`'s `False` return (lease lost to a successor) was discarded and the runner kept writing — two writers, silently. `run_backfill` now stops launching, sets `BackfillResult.lease_lost`, and the CLI exits `EXIT_LEASE_LOST = 7` with an explicit banner.
  - `[high]` `[patch]` A *paused* runner kept beating `backfill:gemma:active` (pause polls ticked `on_progress`), permanently blocking `migrate-primary.sh` — defeating the main reason an operator pauses. Pause polls no longer tick `on_progress`; the heartbeat only beats on real row outcomes.
  - `[high]` `[patch]` `--task-classes deal_verdict` mapped to `stages="verdict_only"`, but `run_enrichment` always runs visual+sentiment and writes a verdict only for `"all"` — the scope burned cloud quota on the wrong work, overwrote `ai_score`, and never wrote the verdict. The CLI now refuses that scope with the rationale; the core vocabulary helper is unchanged.
  - `[medium]` `[patch]` `BackfillState.RUNNING` was published once against a 120s TTL, so any real run read back as `idle` from `--status` (and from story 1.5's API). Added `_STATE_REFRESH_SECONDS` and a throttled re-publish from the launch loop.
  - `[medium]` `[patch]` `_sleep_for_reset` re-published `backing-off` every `lease_ttl/3` (300s) against the same 120s TTL — absent 60% of the time. Refresh interval now strictly below the state TTL.
  - `[medium]` `[patch]` The CLI's `finally` published `IDLE` unconditionally, erasing the `BACKING_OFF` `run_backfill` publishes on quota exhaustion. It now preserves `BACKING_OFF` for a quota-ended pass.
  - `[medium]` `[patch]` `try_consume`'s window-open `hset` was a separate round-trip from the `hincrby`, so two writers could wipe each other's reservation — the docstring's atomicity claim was false. Added `_BUDGET_RESERVE_LUA` (roll + incr + limit + rollback in one server-side step) used whenever the client exposes `eval`; the multi-op path stays as an honestly-documented fallback for test doubles.
  - `[medium]` `[patch]` A terminal 429 was always read as "daily quota spent", so a per-minute throttle parked `--continuous` for up to ~24h. Added `backfill.quota_backoff_seconds` (900) and capped the wait when the **local** budget still has headroom.
  - `[medium]` `[patch]` `--dry-run` never called `_build_client`, so the operator's pre-flight command skipped the new routing validation entirely and gave false confidence. Dry-run now resolves the backend and warns (without needing a key, without failing).
  - `[medium]` `[patch]` `control.clear_requests()` on start silently discarded a pause/stop the operator had issued, and `--status` showed no pending requests. Both fixed: the discard is announced, `--status` lists pending requests.
  - `[medium]` `[patch]` Ctrl-C / `--stop` during the budget sleep went unnoticed for up to 300s (PEP 475 resumes `time.sleep` after the handler returns). The sleep now steps at `control_poll_seconds` and checks `should_stop()` each step.
  - `[medium]` `[patch]` The new EMBEDDING short-circuit in `resolve_enrichment_backend` logged at WARNING unconditionally — reintroducing the exact per-call live-path log flood story 1.2's review demoted to DEBUG. WARNING is now backfill-only.
  - `[medium]` `[patch]` Test doubles modelled pause/stop as pop-once **events** while `BackfillControl` documents **levels**, so a regression making `is_paused()` consume the key would have passed; and no test covered the owner losing its *own* lease. Added tests driving `run_backfill` against a real `BackfillControl` on the fake Redis, plus lease-loss coverage.
  - `[medium]` `[patch]` The atomic Lua compares a new `start_epoch` field, so a budget hash written before this story read as *no window* and rolled — handing the run a second full day's budget inside one real 24h, past the provider's RPD. Added `DailyBudget._migrate_start_epoch` (one-off backfill from the existing ISO `start`) plus a regression test.
  - `[low]` `[patch]` The all-local refusal advised "narrow `--task-classes`", which usually produced a second, different failure. The advice now names only the supported scopes; argparse help matches.
  - `[low]` `[patch]` A reservation larger than the whole cap left a phantom zero-count window whose `seconds_until_reset()` was ~24h — `--continuous` then slept a day per cycle forever. A refusal that opened the window now deletes it (both branches).
  - `[low]` `[patch]` `--resume` cleared only the pause key, so a pending `--stop` still stopped the run while the command printed "will continue launching rows". `--resume` now clears both and says so.
  - `[low]` `[patch]` A stop landing after the final launch left `result.stopped` False, so the documented exit 6 never appeared. Now `result.stopped or control.should_stop()`.
  - `[low]` `[patch]` `clear_requests()` / signal wiring ran after `lease.acquire()` but outside the `try/finally`, orphaning the lease for 900s on any exception there. Moved inside the `try`.
  - `[low]` `[patch]` The `processed % 25` progress log fired on every pause poll and every error tick. Now gated on `processed` actually crossing a new multiple of 25.
  - `[low]` `[patch]` A transient Redis error inside `on_progress` could abort an otherwise-resumable multi-day run. The CLI tick is now guarded and logs a warning.
  - `[low]` `[patch]` `control_poll_seconds: 0` made the paused loop busy-spin on Redis. Added Pydantic constraints (`ge=30` / `gt=0.0` / `ge=0`) on the three backfill control fields.

<!-- Deferred (1): the maintenance guard is still open while the runner sleeps out a budget window — see deferred-work.md. -->
<!-- Rejected (3): refunding the daily-budget reservation on a quota failure (the requests were genuinely sent to the provider and count against its RPD — refunding would under-report real usage); moving `budget.try_consume` back before `sem.acquire()` (the current order is deliberate and documented — it avoids reserving budget for a row a quota-exhausted run will never launch); `mode=missing` mis-selecting rows for a verdict-only pass (moot — that scope is now refused outright). -->

### 2026-08-06 — Review pass 2 (follow-up; patch-level only, no spec/intent loopback)
- intent_gap: 0
- bad_spec: 0
- patch: 17: (high 0, medium 9, low 8)
- defer: 1: (high 0, medium 1, low 0)
- reject: 3: (high 0, medium 1, low 2)
- addressed_findings:
  - `[medium]` `[patch]` `on_progress` ran before `sem.release()` in the worker's `finally` with no guard, so a raising hook skipped the release and the launch loop blocked on `sem.acquire()` **forever** while holding the lease — a hang, not an error. The hook is now wrapped and the release moved to an inner `finally`.
  - `[medium]` `[patch]` The lease was renewed only per launch-loop iteration, so the closing `asyncio.gather` drain ran on a lease nobody refreshed. The worker's `finally` now ticks it too (guarded — a Redis blip there must not strand in-flight rows), and `lease_ttl_seconds`' floor rose from a misleading `ge=30` to `ge=300`, since renewal rides on row completions.
  - `[medium]` `[patch]` `BackfillState.PAUSED` was published once against a 120s state TTL, so any pause longer than two minutes read back as `idle` — for a runner alive, holding the lease and deliberately held. The same decay was already fixed for `running` and `backing-off`; `paused` was missed.
  - `[medium]` `[patch]` `BackfillControl.request_resume()` cleared only the pause key. The CLI worked around it locally, but story 1.5's endpoints call *this* method — so "resume" would have cleared the pause, left the stop in force, and ended the run it claimed to continue. Fixed in the shared object; the CLI now goes through it.
  - `[medium]` `[patch]` The CLI's `finally` released the lease *before* publishing its final state (letting a newly started runner's `running` be stamped with `idle`) and published even when the lease had been **lost** — overwriting the state key that now describes the successor. Publishes first, and publishes nothing on lease loss.
  - `[medium]` `[patch]` `--reset-quarantine` rewrote the shared attempt ledger with no lease check, so clearing it under a live run released that runner's quarantined rows and made it re-spend cloud quota on properties already proven unenrichable. Now refused while the lease is held.
  - `[medium]` `[patch]` `quota_backoff_seconds` was `ge=0`, and `0` — a plausible reading of "no cap" — meant *no back-off at all*: a provider refusal became a tight retry loop against an already-throttled account. Floored at 60.
  - `[medium]` `[patch]` `--task-classes visual,sentiment` was accepted but writes `ai_score` without a deal verdict, and `mode=missing` keys only on `ai_score` — so every row it touched stopped being a candidate and would never get a verdict from a later full pass (recoverable only by a `--force` re-run of the whole spend). This is the mirror image of the `deal_verdict`-only hazard pass 1 refused; now refused symmetrically, core vocabulary unchanged.
  - `[medium]` `[patch]` The `eval` test doubles dispatch on script *identity* and re-implement the logic in Python, so `_BUDGET_RESERVE_LUA` / `_LEASE_RENEW_LUA` / `_LEASE_RELEASE_LUA` — the mutual-exclusion and never-exceed-budget core — shipped as never-executed text; a typo would have passed the whole unit suite and died on row one against a real Redis. Added `src/tests/integration/test_backfill_lua_scripts.py`, which executes them against the test-stack Redis.
  - `[low]` `[patch]` `_sleep_for_reset` polled only `should_stop()`, so a pause issued during a budget/back-off wait was unacknowledged for the whole window — the state key kept reading `backing-off`. It now reports `paused`.
  - `[low]` `[patch]` `_sleep_for_reset` discarded `lease.renew()`'s `False`, sleeping out hours on a lease someone else owned. It now returns so the next pass exits `EXIT_LEASE_LOST`.
  - `[low]` `[patch]` A honored `--stop` was never cleared, so `--status` reported it pending for the 7-day request TTL and the next start announced it as an operator request being *discarded* — when it had already been served. Added `BackfillControl.clear_stop()`, called on both stop-exit paths.
  - `[low]` `[patch]` The CAS reply decode fell back to `bool(raw)`, and `bool(b"0")` is `True` — so for any client returning the Lua reply as bytes a **refused** lease renew read as success: two writers, silently. Both the lease and the budget now decode before comparing.
  - `[low]` `[patch]` `_resolve_backfill_backend`'s docstring claimed it refuses "before taking the lease", but it ran inside `_run` — after `lease.acquire()` and `clear_requests()`, so a misconfigured start discarded an operator's pending pause/stop on its way to dying. Scope and routing are now validated before the lease is taken.
  - `[low]` `[patch]` A missing `GEMINI_API_KEY` degrades cloud routing to local, so the all-local refusal told the operator to set routing keys they had already set. The missing-key case is now diagnosed as itself.
  - `[low]` `[patch]` `_is_quota_response` knew only 429 / `resource_exhausted`, and the non-quota `AIClientError` dropped the response body — so a quota refusal arriving as 403/400 fabricated 0.5 scores, and core's text-matching safety net had nothing to match on. Markers broadened; the body is kept on the message.
  - `[low]` `[patch]` `--continuous` with a daily budget below `requests_per_property` could never reserve a property, so every pass ended `budget_exhausted` with nothing processed and the loop slept a 24h window forever — the stall detector only fires when the budget is *not* exhausted. Now refused up front.

<!-- Deferred (1): a single row outliving `lease_ttl_seconds` can still let the lease lapse; the complete fix is a background renewer that restructures the run — see deferred-work.md. -->
<!-- Rejected (3): refunding the daily-budget reservation on a quota failure (re-raised from pass 1 — the requests were genuinely sent and count against the provider's RPD); `is_quota_exhausted`'s substring safety net being over-broad (it is the design the Code Map specifies, and the duck-typed flag is the real contract); hardening every lease/control Redis read against transient errors (Redis is a hard dependency of the budget and checkpoint too — a blip ends the pass by design, and the one place it must not, the worker's `finally`, is now guarded).
-->

### 2026-08-06 — Review pass 3 (follow-up; patch-level only, no spec/intent loopback)
- intent_gap: 0
- bad_spec: 0
- patch: 21: (high 0, medium 6, low 15)
- defer: 1: (high 0, medium 1, low 0)
- reject: 8: (high 0, medium 2, low 6)
- addressed_findings:
  - `[medium]` `[patch]` Every Redis touch in the launch loop (lease renew, control reads, budget reservation, ledger writes) was unguarded, so a transient blip escaped `run_backfill` with rows still in flight and `asyncio.run` cancelled them at an arbitrary await point — mid-enrichment, mid-write. The exact policy the worker's `finally` already applies two lines away. The drain is now a `finally`, and the gather uses `return_exceptions` because `checkpoint.advance()` runs outside the worker's `except` and would otherwise abort it on the first failure.
  - `[medium]` `[patch]` A quota refusal also sets `budget_exhausted`, which puts the pass out of reach of the stall detector — so a provider refusing everything (spent RPD, revoked key) produced ~96 identical zero-progress `--continuous` passes a day, forever, each re-spending the client's retry budget against an already-refusing account. After `_MAX_QUOTA_BACKOFF_CYCLES` consecutive zero-progress refusals the per-minute-throttle reading is ruled out and the runner waits out the RPD window instead.
  - `[medium]` `[patch]` The published state was refreshed once per launch-loop iteration, so with `concurrency=1` the cadence *is* the row duration: a single row slower than the 120s state TTL (3 cloud calls with client-side retries) made a live run read back as `idle` from `--status` and story 1.5's API. The worker's tick now refreshes it too — re-publishing the *current* state, so it can never stamp `running` over a deliberate pause or a back-off.
  - `[medium]` `[patch]` `main` read and cleared the stop request *after* `lease.release()`. A runner that started in that window owns those keys, so an operator's stop aimed at the new live run was reported as served by the exiting one and then deleted — and the live run never stopped. Both now happen while the lease is still held.
  - `[medium]` `[patch]` `--continuous` checked `census.is_complete` before `result.lease_lost`, so a displaced runner whose successor drained the queue reported *itself* as the one that completed the backfill (exit 0) and let `main` stamp its final state over the successor's. Lease loss now takes precedence over everything.
  - `[medium]` `[patch]` The `--task-classes` help and the module docstring still advertised the `visual,sentiment` scope that pass 2 made `_stages_for` refuse — an operator following `--help` got a hard `SystemExit` on the thing the help had just recommended.
  - `[low]` `[patch]` `--reset-quarantine`'s lease guard read `holder()` and then rewrote the ledger: check-then-act, so a run starting in the gap still got its quarantine wiped underneath it. It takes the lease now, and hands it back.
  - `[low]` `[patch]` `_sleep_for_reset` published state *before* verifying ownership, and on a cadence 10× faster than its renew check — so a runner whose lease lapsed mid-wait stamped `backing-off` over the successor's `running` up to ten times before noticing. Renew first, return on failure.
  - `[low]` `[patch]` `_sleep_for_reset` accumulated the *requested* chunk lengths as elapsed time. `time.sleep` only guarantees a lower bound, so on a suspended host the renew cadence silently drifted past the lease TTL. Elapsed is now the later of the accumulator and the wall clock, on a fixed (non-drifting) cadence.
  - `[low]` `[patch]` `BackfillLease.acquire()` wrote its advisory meta hash *after* the atomic `SET NX`, outside any `try/finally` the caller had yet — so a Redis blip on a cosmetic write orphaned the lease for the full TTL and locked the next run out. The meta write can no longer fail a lease.
  - `[low]` `[patch]` A raising `control.publish_state()` in `main`'s `finally` skipped `lease.release()` — same lock-out, from the other end. Guarded.
  - `[low]` `[patch]` A negative `--reset-margin` could drive the post-budget wait to zero, and a zero-length sleep turns `--continuous` into a tight loop of passes that can reserve nothing. Rejected at parse time.
  - `[low]` `[patch]` The non-atomic lease renew returned an unconditional `True`: Redis `EXPIRE` answers 0 when the key is already gone, so a runner whose lease had lapsed believed it still owned one a successor may hold.
  - `[low]` `[patch]` `run_backfill(pause_poll_seconds=0)` busy-spins the paused loop on Redis. `AppConfig` constrains the CLI's value, but this is the public core entry point story 1.5 calls directly; it now floors its own poll.
  - `[low]` `[patch]` The state refresh interval was the module constant, while `BackfillControl` accepts a `state_ttl_seconds` — a caller (story 1.5) constructing a shorter TTL would refresh too slowly and let the key expire under a live run. The cadence is now derived from the control's own TTL.
  - `[low]` `[patch]` `cloud_available` strips before testing the key but the CLI did not, so a whitespace-only `GEMINI_API_KEY` routed local and took the "your routing map is wrong" branch — the exact misdiagnosis pass 2 fixed for an absent key — and would have sent the blank bearer to the provider.
  - `[low]` `[patch]` A `--continuous` run that drained the queue on a pass which had published `backing-off` exited publishing `backing-off` for a *finished* backfill.
  - `[low]` `[patch]` `--stop --status` ran the stop and silently ignored the status; `--reset-quarantine --pause` never paused. The command flags are mutually exclusive now, not first-wins.
  - `[low]` `[patch]` A pause/stop request outstanding when the queue drains was left set, so `--status` reported it pending for the 7-day TTL with no runner alive — the symptom pass 2 fixed for the stop-exit path, one exit path over.
  - `[low]` `[patch]` The lease CAS and the budget reservation silently downgrade to non-atomic multi-round-trip sequences whenever the injected client exposes no callable `eval`. That is right for test doubles, but a production client that lacked it would quietly stop enforcing mutual exclusion and the RPD ceiling with nothing in the log. It says so once per object now.
  - `[low]` `[patch]` `control_poll_seconds` and `lease_ttl_seconds` each passed their own floor while the *ratio* between them was free — and the lease is renewed once per poll, so a slow poll lets it expire under a paused or waiting runner. Added a cross-field validator (`poll < ttl/3`).

<!-- Deferred (1): a provider throttle arriving as connection resets/timeouts is charged to the row and can permanently quarantine good properties — pre-existing ledger behaviour, and the fix needs a deliberate heuristic. See deferred-work.md. -->
<!-- Rejected (8): refunding the daily-budget reservation on a quota failure (re-raised a third time — the requests were genuinely sent and count against the provider's RPD); `is_quota_exhausted`'s substring breadth (re-raised from pass 2 — it is the specified design, and the duck-typed flag is the contract); blocking Redis I/O in the signal handler (redis-py checks a *different* pooled connection out for the nested call, and moving the write into the loop needs plumbing for no real defect); the TPM tokens reserved for a row abandoned on a quota/budget break (the pass ends there and the next one is ≥ the back-off away, far past the 60s TPM window); the `_migrate_start_epoch` hgetall→hset race (single-writer under the lease, and a stale `start_epoch` self-heals on the next roll); `_migrate_start_epoch` no-opping on a hash with `count` but no parseable `start` (no version of this code ever wrote that shape); replacing the injected clock with server-side `redis TIME` for window rolls (the injected clock is the design and the testability seam — a redesign, not a patch); a distinguished exit code for a single pass that ended on quota (single-pass mode exits 0 on every partial outcome, including `budget_exhausted`; a new code is a new CLI contract, not a review fix).
-->

### 2026-08-11 — Review pass 4 (deferred-work bundle DW-1; patch-level only, no spec/intent loopback)
- intent_gap: 0
- bad_spec: 0
- patch: 3: (high 0, medium 1, low 2)
- defer: 7: (high 1, medium 4, low 2)
- reject: 3: (high 0, medium 1, low 2)
- addressed_findings:
  - `[medium]` `[patch]` A lease lost *between* passes was invisible, so a displaced runner reported the successor's work as its own completion. `_sleep_for_reset` signalled a lost lease with a bare `return`, indistinguishable from "the window elapsed", and the pass that followed found the queue already drained by the successor — an empty row set never reaches the launch loop, so nothing verified ownership, `lease_lost` stayed False, `--continuous` took the `census.is_complete` branch (exit 0, "BACKFILL COMPLETE"), cleared the pause/stop requests aimed at the **live** successor and stamped `idle` over its `running`. `_sleep_for_reset` now returns an outcome like `_wait_out_migration` (`elapsed` / `stopped` / `lease_lost`) and the caller exits `EXIT_LEASE_LOST`; `run_backfill` verifies ownership once at pass entry, *before* publishing `running`, so every route into an empty or short-circuited pass reports the displacement instead of hiding it.
  - `[low]` `[patch]` The exit path could replace a multi-day run's return code with a traceback: `lease.release()` in `main`'s `finally` and the `control.state()` read that decides the final published state were the last unguarded Redis touches there — the `publish_state` between them was already wrapped precisely so a blip could never cost the release. A completed backfill exiting 1 is indistinguishable from a crash to a supervisor, and the lease self-heals on its TTL anyway. Both are guarded and logged now.
  - `[low]` `[patch]` A transient Redis blip on the purely decorative state key killed the whole unattended run: `_sleep_for_reset` and `_wait_out_migration` are where a multi-day `--continuous` run spends most of its wall clock, and an unguarded `publish_state` there escaped to `main` as an undocumented exit 1 despite an intact checkpoint and a healthy provider — the one asymmetry left against `run_backfill`'s own guarded bookkeeping. Both loops now publish through `_publish_wait_state`, which logs and continues. The stop poll and `lease.renew()` around it stay unguarded on purpose: they decide whether this process may keep writing, and a blip there ends the pass by design (the standing rejection from passes 2-3).

<!-- Deferred (7): DW-17 every non-quota client failure still persists a fabricated 0.5 and retires the row (the story's headline corruption, closed for quota only — and fenced by the intent contract's "never change the fallback for anything except a quota error"); DW-18 the budget counts properties, not the client's retries, so a throttled account overshoots the provider RPD; DW-19 `--continuous` never exits on a permanently refusing provider; DW-20 the published state still decays to `idle` during one in-flight row (the renewer deliberately never refreshes it — the injected-clock seam this pass was barred from redesigning); DW-21 nothing renews the lease outside `run_backfill` (candidate fetch, census, inter-pass window); DW-22 the signal handler's blocking Redis I/O can deadlock on redis-py's pool lock (pass 3 rejected this on a reason that covers connection state but not the pool lock); DW-23 a pause request self-expires after 7 days and the run silently resumes. See deferred-work.md. -->
<!-- Rejected (3): the `:active` heartbeat lapsing under one slow row so `migrate-primary.sh` reads "idle" (real, but already open as DW-9 — this bundle's intent excludes what DW-3/4/6/7 and their descendants already capture); a quota refusal at the verdict stage discarding the visual+sentiment spend already paid for that row (the rollback is correct — an `ai_score` with no verdict is exactly the stranding `_stages_for` refuses — and the cost is one row per pass); `_wait_out_migration` returning "cleared" before polling a pending stop (the stop is still honored at the next `_may_launch`; the cost is one candidate fetch, and moving the poll ahead of the gate re-orders a sequence pass 3 placed deliberately).
-->

## Design Notes

**Why the 0.5 fabrication is the heart of AC-2.** `GeminiClient.chat_completions` raises `AIClientError` after exhausting 429 retries, but `analyze_visuals`/`analyze_text` catch *every* exception and return `condition_score=0.5` / `sentiment_score=0.5`. `run_enrichment` then computes a non-falsy `a_score`, persists it, and `run_backfill` checkpoints the row as processed — so a quota-exhausted multi-day run quietly fills the DB with fake 0.5 scores that `mode=missing` will never re-queue. Back-off is only meaningful if the failure is visible, so the fix is a distinguished exception that the fallbacks let through:

```python
class AIQuotaExhaustedError(AIClientError):
    """Provider quota/rate limit is exhausted — back off, never fall back."""
    is_quota_exhausted = True  # duck-typed flag core reads without importing adapters

# in each `except Exception as exc:` fallback, first line:
if getattr(exc, "is_quota_exhausted", False):
    raise
```

**Lease vs heartbeat.** The existing `Heartbeat` (`<prefix>:active`) stays exactly as-is — it is the *advisory* signal `migrate-primary.sh` observes and must keep observing. The lease is a separate, *enforcing* key (`<prefix>:lease`) holding a per-process token; `acquire()` is `SET key token NX EX ttl` (atomic), `renew()`/`release()` are owner-token CAS so a runner can never extend or delete a successor's lease. TTL (default 900s, renewed from `_on_progress`) is what recovers the lease after a crash, so a hard kill self-heals without operator action.

**Atomic budget.** `try_consume` becomes: roll the window if stale (single-writer under the lease), then `count = HINCRBY key count n`; if `count > limit`, `HINCRBY key count -n` and return False. The read-modify-write lost-update window disappears; `consumed`/`remaining`/`seconds_until_reset` semantics are unchanged, so the existing budget tests keep passing.

**Control is state + requests, not a queue.** `BackfillControl` writes single-field request keys (`<prefix>:control:pause`, `:stop`) and publishes `<prefix>:state` with a TTL slightly above the lease renew interval, so a crashed runner reads back as `idle` rather than a stuck `running`. Story 1.5's admin endpoints call the same object — no second control path, no second quota consumer (AD-13).

**Scope translation lives at the edge.** `stages_for_task_classes()` maps a frozenset of `EnrichmentTaskClass` onto the three supported `stages` literals from `core.enrichment_rerun` (`all`, `visual+sentiment`, `verdict_only`) and raises on an unsupported combination. The runner and CLI speak task classes; only `fetch_candidate_rows`/`run_enrichment` still see the legacy string.

**Operator-visible change (document loudly).** `_build_client` stops hardcoding Gemma and asks the routing map. With the shipped all-local default the cloud backfill now refuses to start until the operator sets e.g. `ai.enrichment_routing.{visual,sentiment,deal_verdict}: gemma` and exports `GEMINI_API_KEY`. That is FR-27/AD-13 working as designed (one `AppConfig`-owned source of truth for backend selection), but it changes an existing operator workflow, so the error message must name the exact keys and the feature doc must call it out.

## Verification

**Commands:**
- `bash scripts/agent/validate.sh fast` -- expected: lint (pre-commit, all files) + unit green, including the new `test_backfill_control.py` and `test_ai_quota_propagation.py`.
- `bash scripts/agent/validate-ai.sh` -- expected: AI-quality golden pass (merge-blocking AI-client-change gate). From WSL set `OLLAMA_HOST=http://$(ip route show default | awk '/default/{print $3}'):11434`.
- `grep -nE "^\s*(from|import) (adapters|api)\b" src/core/backfill_runner.py` -- expected: no output (AD-1 layering intact; the existing lazy `infra.logging` import inside `_log_row_error` is allowed and unchanged).
- `bash scripts/agent/validate.sh all` -- expected: full gate green incl. `src/tests/contract/` (no API schema change). Run by `finish-feature.sh`.

## Auto Run Result

Status: **done** (fourth review pass — deferred-work bundle DW-1; 3 patches, no intent-gap/bad-spec loopback).

**Implemented change:** The independent follow-up review DW-1 preserved after story 1.3's damping cap was spent. Two blind reviewers (adversarial + edge-case) read the full `06653689..7bb09136` delta and verified every claim against the *current* tree, which has moved on since 1.3 (the fu6 migration mutual exclusion, the fu7 background lease renewer and the fu8 transport-quota inference all landed after `7bb09136`). Fourteen findings survived that verification: 3 were patched, 7 deferred as DW-17..DW-23, 3 rejected. The patches are one cluster — **truth under handover and on the way out**. A lease lost *between* passes (during the budget sleep, the candidate fetch or the census) was structurally invisible: `_sleep_for_reset` reported it with a bare `return`, and the pass that followed found the queue already drained by the successor, so an empty row set never reached the launch loop, never verified ownership, and `--continuous` reported the successor's completed backfill as its own (exit 0), cleared the control requests aimed at that live successor and stamped `idle` over its `running`. The sleep now returns an outcome the caller maps to `EXIT_LEASE_LOST`, and `run_backfill` verifies ownership once at pass entry before publishing `running`. The other two close the exit path: `lease.release()` and the final `control.state()` read could replace a multi-day run's return code with an exit-1 traceback, and an unguarded `publish_state` in the two sync wait loops — where an unattended run spends most of its wall clock — let a Redis blip on a purely decorative key kill a run with an intact checkpoint. The stop poll and `lease.renew()` beside them stay unguarded, per the standing rejection from passes 2-3: those decide whether this process may keep writing.

**The deferrals are the substantive result of this pass.** DW-17 is the largest: story 1.3 closed the fabricated-0.5 corruption for *quota* only, so a revoked key (401), a retired model id (404) or a DNS outage still returns `condition_score=0.5`, persists it, advances the checkpoint and — because `mode=missing` keys on `not score` — retires the property from the candidate set permanently, at roughly 4,600 rows a day behind a healthy-looking banner. It is fenced by this story's own intent contract ("do not change the fallback for anything except a quota error"), so it is a deliberate next change, not a review patch. DW-18 (the budget counts properties, never the client's retries, so AC-1's never-exceed guarantee measures the wrong quantity) and DW-21 (nothing renews the lease outside `run_backfill`) are the other two worth scheduling early.

**Files changed:**
- `src/core/backfill_runner.py` — `run_backfill` verifies lease ownership at pass entry, before publishing `running`, so a pass with no workable rows can no longer return `lease_lost=False` for a displaced runner.
- `scripts/dev/backfill_gemma.py` — `_sleep_for_reset` returns `elapsed`/`stopped`/`lease_lost` (mirroring `_wait_out_migration`) and `_run_continuous` exits `EXIT_LEASE_LOST` on the last; new `_publish_wait_state` guards the decorative state publish in both sync wait loops; `lease.release()` and the final `control.state()` read are guarded so the exit path cannot discard the run's return code.
- `src/tests/unit/test_backfill_control.py`, `src/tests/unit/test_backfill_gemma_cli.py` — 6 regressions: an empty pass under a stolen lease reports `lease_lost` and publishes nothing, an empty pass under a *held* lease still publishes normally, the three `_sleep_for_reset` outcomes, a lease lost during the budget sleep exiting `EXIT_LEASE_LOST`, a publish blip during the wait not killing the run, and a failing release not replacing the exit code.
- `_bmad-output/implementation-artifacts/deferred-work.md` — **appended** DW-17..DW-23. No existing entry was modified (the orchestrator owns resolution).
- `docs/features/v0.13-s1.3-backfill-runner-control-core.md` — this pass recorded.

**Review findings breakdown:** 3 patches applied (medium 1, low 2). 0 intent-gap, 0 bad-spec. 7 deferred (DW-17..DW-23; high 1, medium 4, low 2). 3 rejected: the `:active` heartbeat lapsing under one slow row (real, but already open as DW-9, which this bundle's intent excludes as a descendant of DW-3/4); a quota refusal at the verdict stage discarding that row's visual+sentiment spend (the rollback is correct and costs one row per pass); and `_wait_out_migration` returning "cleared" before polling a pending stop (the stop is still honored at the next `_may_launch`). None of the eight rejections from passes 1-3 was re-raised as a patch; DW-22 records that pass 3's stated reason for rejecting the signal-handler Redis I/O covers connection state but not redis-py's pool lock, without re-litigating the decision itself.

**Verification:** `bash scripts/agent/validate.sh fast` → **green** (exit 0): pre-commit over all files + eslint, **1699 unit** passed, 1 skipped. Each of the 5 behavioural regressions was mutation-checked — reverting all three patches at once fails exactly those 5 and nothing else beyond two collateral failures caused by the crude textual revert also hitting `_wait_out_migration`'s returns; the sources were restored and the suite re-run green (199 passed across the three backfill suites). `validate.sh backend` was **not** run: this pass changes no DB schema, no API schema and no AI prompt or client code (`src/adapters/ai/client.py` is untouched), so `alembic check`, the contract suite and `validate-ai.sh` all cover surfaces this diff does not touch. `validate.sh all` runs at merge — the orchestrator owns finishing. The worktree needed the sanctioned `.venv` symlink from the primary checkout (what `setup-worktree.sh` does; its branch-name validator rejects the `bmad-loop/` prefix, so the symlink was made directly) — without it the host pytest falls back to a system python missing `slowapi`/`pgvector`.

**Residual risks:** The pass-entry ownership check costs one extra `renew()` round-trip per pass — negligible against a pass that fetches ~26k candidate rows, but it does mean a Redis blip at pass entry now ends the pass rather than being discovered one row later (the same policy the launch loop already applies one line further on). The three guards added here are deliberately narrow: a Redis outage that outlives the lease TTL is still swallowed (DW-10), and the two wait loops still die on a failing `should_stop()` or `renew()` by design. Everything the reviewers found beyond these three fixes is open in the ledger rather than fixed — most consequentially DW-17, which means the story's headline "never persist a fabricated score" guarantee still holds only for provider quota refusals, not for authentication, model-id or transport failures.
