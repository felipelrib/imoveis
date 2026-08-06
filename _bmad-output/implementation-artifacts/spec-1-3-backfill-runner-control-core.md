---
title: 'Backfill runner control core — lease, pause/resume, safe interruption'
type: 'feature'
created: '2026-08-06'
baseline_revision: '06653689c190695b10eadca5e643038a7255ee19'
final_revision: 'squash-merged to main by finish-feature.sh (see main git log)'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
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

Status: **done** (1 review pass, patch-level only — no intent-gap/bad-spec loopback).

**Implemented change:** The Gemma backfill runner graduates from a lone script into a controllable, single-instance product core. `src/core/backfill_runner.py` gains three injectable Redis-backed primitives — `BackfillLease` (`SET NX EX` + owner-token CAS renew/release, self-healing via TTL), `BackfillControl` (level-semantics pause/stop requests plus the published `idle|running|paused|backing-off` state stories 1.5/1.6 will read), and a task-class-expressed scope (`DEFAULT_BACKFILL_SCOPE`, `parse_task_classes`, `stages_for_task_classes`) — plus an atomic `DailyBudget.try_consume` (server-side Lua when the client supports `eval`), `AttemptLedger.rollback_attempt`, and a `run_backfill` that honors pause/stop, renews the lease itself, aborts on lease loss, and classifies a provider quota refusal as back-off rather than row failure. The correctness centrepiece: a persistent 429 used to be swallowed by `analyze_visuals`/`analyze_text`, which returned a fabricated `0.5` that `run_enrichment` then **persisted and checkpointed** — silently filling the DB with fake scores `mode=missing` would never re-queue. A distinguished `AIQuotaExhaustedError` now propagates past every fallback, so a quota-exhausted call writes nothing, costs no ledger attempt, and backs off. The CLI takes/releases the lease, exposes `--pause/--resume/--stop/--task-classes`, drains cleanly on SIGINT/SIGTERM, and derives its cloud backend from `ai.enrichment_routing` instead of hardcoding Gemma.

**Files changed:**
- `src/core/backfill_runner.py` — lease, control, state enum, scope helpers, quota predicate, atomic budget (+ `start_epoch` migration), `run_backfill` pause/stop/quota/lease-loss branches, `BackfillResult.{stopped,paused_seconds,quota_exhausted,lease_lost}`.
- `src/adapters/ai/client.py` — `AIQuotaExhaustedError` raised on a terminal 429/`RESOURCE_EXHAUSTED`, re-raised past all seven fabricated-score fallbacks; `EMBEDDING` never honors cloud (closes the item deferred from spec-1-2).
- `scripts/dev/backfill_gemma.py` — lease lifecycle, control flags and signal handling, routing-derived client with actionable refusals, dry-run pre-flight warning, bounded quota back-off, exit codes 5/6/7.
- `src/infra/config.py`, `configs/app_config.yaml` — `backfill.{lease_ttl_seconds,control_poll_seconds,quota_backoff_seconds}` with constraints and documented semantics.
- `src/tests/unit/test_backfill_control.py` (new), `src/tests/unit/test_ai_quota_propagation.py` (new), plus extensions to `test_backfill_runner.py`, `test_backfill_gemma_cli.py`, `test_backfill_gemma_completion_cli.py`, `test_ai_routing.py`, `test_config.py`.
- `docs/features/v0.13-s1.3-backfill-runner-control-core.md` — new feature doc.

**Review findings breakdown:** 23 patches applied (4 high: lease renewal only on successful rows, lease-loss ignored, heartbeat kept alive while paused blocking `migrate-primary.sh`, `deal_verdict`-only scope doing the wrong work; 10 medium; 9 low). 0 intent-gap, 0 bad-spec, 1 deferred (the primary-migration guard is still open across a budget-window sleep), 3 rejected.

**Follow-up review recommended:** true — the review pass rewrote the lease keepalive contract, introduced a server-side Lua budget script, changed quota back-off policy, and reshaped the CLI control surface. That is high volume across behaviour, data-integrity and operator-facing paths; an independent look at the review delta is warranted.

**Verification:** `bash scripts/agent/validate.sh fast` → green (1571 passed, 1 skipped; lint clean). `bash scripts/agent/validate-ai.sh` → green (Ollama reachable, 2 golden tests). `grep -nE "^\s*(from|import) (adapters|api)\b" src/core/backfill_runner.py` → no output (AD-1 intact). `bash scripts/agent/validate.sh all` runs at merge via `finish-feature.sh`.

**Residual risks:** The cloud backfill now refuses to start under the shipped all-local `enrichment_routing` default — an intentional FR-27/AD-13 correction that nonetheless changes an existing operator workflow (fix: route `visual`/`sentiment`/`deal_verdict` to `gemma` and export `GEMINI_API_KEY`). A pre-v0.13-s1.3 budget hash is migrated in place on first use; the migration read is not atomic with the reservation, which is harmless under the lease. The lease's non-`eval` CAS fallback exists only for test doubles — every real Redis client takes the atomic path. The runner still has no local execution mode (AD-4) and refuses a locally-routed scope rather than doing GPU work inline.
