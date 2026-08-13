---
title: 'Checkpoint advance semantics under lease loss'
type: 'bugfix'
created: '2026-08-12'
status: done
baseline_revision: '2651da0a1f309e760469fbbb514f5f8ad9748685'
final_revision: '036a9fb'
review_loop_iteration: 1
followup_review_recommended: true
operator_actions:
  - 'Start Docker Desktop on the Windows host and enable WSL integration for this distro. The daemon is down (`docker info` fails; `docker` is not a usable binary in this distro), which is the only reason the full gate could not run.'
  - 'With Docker up, re-run `bash scripts/agent/validate.sh all` from this worktree and confirm it is green — this is the one acceptance criterion this run could not verify, and the first execution of the 5 new real-Redis tests in `src/tests/integration/test_backfill_lua_scripts.py` that prove the shipped Lua body itself (the unit suite only exercises a Python mirror of it). Expect the two `test_no_data_destroying_scripts.py::test_volumes_flag_is_refused_not_silently_ignored[stop.sh|clean.sh]` failures to disappear: they shell out to `stop.sh --volumes`, which aborts with "docker is not running" before printing the refusal they assert, and they fail identically on the untouched baseline.'
  - 'Let the bmad-loop orchestrator merge this branch. `finish-feature.sh` refuses it ("branch does not have a valid conventional type prefix"), as it does every `bmad-loop/<run>/<story>` branch — do not merge by hand.'
  - 'After the merge lands on `main` and is pushed, set `3-4-checkpoint-advance-semantics: done` in `_bmad-output/implementation-artifacts/sprint-status.yaml` (it is `in-progress` now).'
  - 'Optionally prove the handover end to end, which no agent can do here: with a backfill running, take its lease from a second shell (`redis-cli SET backfill:gemma:lease other-token KEEPTTL`), then confirm the pass exits 7 with the BACKFILL LEASE LOST banner naming the rows it drained, that `redis-cli HGETALL backfill:gemma:checkpoint` still shows the marker and `processed_total` you set, and that the journal carries one `backfill_checkpoint_declined` line.'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-3-context.md'
warnings: ['oversized']
---

<intent-contract>

## Intent

**Problem:** `Checkpoint.advance()` (`src/core/backfill_runner.py:446-454`) is an unconditional two-op write — `hset last_property_id/last_run_date` + `hincrby processed_total` — on `<prefix>:checkpoint`, a key **every** runner shares, and it is called from `_worker`'s success branch (`:1974-1976`) with no reference to who owns the lease. In-flight rows always drain after a lease loss by design (cancelling mid-enrichment leaves half-written properties), so a displaced runner keeps stamping its own row id and run date over the successor's marker and keeps incrementing the shared all-time counter for rows the successor may be enriching too — they were still `mode=missing` candidates when it fetched. v0.13-fu7 guarded `_publish` against exactly this overwrite class (`:1703-1713`, `:2216-2219`) and deliberately left the checkpoint alone, because the same call also records genuinely completed work (DW-11). The window is not theoretical: at the shipped `lease_ttl_seconds: 900` the renewer only observes a loss every 300s (`:1777-1785`), so an in-process check-then-act guard alone would leave five minutes of drained rows stamping the successor's key.

**Approach:** Lease-gate the advance **at the write**. `Checkpoint` takes an optional lease handle and `advance()` becomes a token compare-and-set returning `bool` — Lua when the client exposes `eval`, the codebase's standard non-atomic fallback otherwise. `run_backfill` routes the advance and `_publish` through **one** predicate (`_owns_shared_state()` = `not result.lease_lost`), and a CAS refusal feeds that same flag, so the checkpoint rule and fu7's state-key guard converge on one handover policy instead of two. Rows that finish after the loss are counted in `BackfillResult.unrecorded_completions` and named in the CLI's lease-lost banner, so the suppressed bookkeeping is visible rather than silently dropped.

## Boundaries & Constraints

**Always:**
- The drain completes — no row is cancelled mid-enrichment, and a suppressed checkpoint write never changes whether `enrich_fn` ran or what it persisted.
- `advance(property_id)` keeps its single positional argument: duck-typed doubles (`test_backfill_completion.py:308-313`, `OneShotCheckpoint` at `test_backfill_control.py:2103-2118`) define exactly that signature.
- Only an explicit `False` return counts as a refusal — a double returning `None` must read as "recorded", or every duck-typed checkpoint would fabricate a lease loss.
- `src/core/backfill_runner.py` gains no `adapters`/`api` import (AD-1); the lease handle is duck-typed on `.key`/`.token` and already lives in this module.
- Any new eval reply goes through `_reply_is_true` (`:110-124` — `bool(b"0")` is `True`), and the eval-less path degrades through `_warn_non_atomic_fallback(self, "checkpoint advance")` (`:64-92`), because the unit fakes have no `eval`.
- Failure containment is unchanged: `checkpoint.advance()` still runs outside `_worker`'s `except`, absorbed by `asyncio.gather(..., return_exceptions=True)` (`:2185-2190`).

**Block If:**
- A consumer is found that reads `last_property_id` back to drive resume ordering (that would revive the monotonic-CAS option and change the mechanism).
- Making the advance lease-aware would require `src/core` to import an adapter, or would change `advance()`'s call signature at any existing call site.

**Never:**
- No new Redis key, no change to `_LEASE_RENEW_LUA` / `_LEASE_RELEASE_LUA` / `_BUDGET_RESERVE_LUA` / `_BUDGET_SETTLE_LUA` or the assertions locking them.
- No wire-schema, admin-API or frontend change; `BackfillCheckpointModel` and the Operações card stay as they are.
- No change to the `:active` heartbeat policy (a draining runner is genuinely writing rows, so beating it stays honest), to `result.processed`, or to the error/quota/degraded branches — they never advanced and still must not.
- No reset/clear of `processed_total`, no re-enrichment of already-drained rows, no weakening of any gate.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Owner records a row | lease wired, `get(<prefix>:lease) == token`, row succeeded | `hset last_property_id/last_run_date` + `hincrby processed_total 1`; `advance` → `True` | No error expected |
| Loss already observed | `result.lease_lost` True, row finishes during drain | No Redis call at all; `result.unrecorded_completions += 1` | No error expected |
| Lease stolen, not yet observed | lease key holds a foreign token; renew has not run yet | CAS refuses → `advance` → `False`; `result.lease_lost` set + `backfill_lease_lost` logged once; `unrecorded_completions += 1`; launch loop stops at its next check | No error expected |
| No lease wired | `Checkpoint(redis, prefix=…)` (status paths, `--dry-run`, existing tests) | Legacy unconditional write, `advance` → `True` | No error expected |
| Client without `eval` | `FakeRedis`, token matches | `get` → compare → `hset` + `hincrby`; one `backfill_non_atomic_redis_fallback` WARNING with `surface="checkpoint advance"` | Latched once per object |
| Client without `eval`, foreign token | `FakeRedis`, `kv[lease] != token` | Nothing written, `advance` → `False` | No error expected |
| Bytes reply | real Redis returns `b"0"` for a refused CAS | `_reply_is_true` decodes → `False` (never truthy-bytes) | No error expected |
| Duck-typed checkpoint double | `advance()` returns `None` | Treated as recorded; no lease loss inferred | No error expected |
| Redis raises inside `advance` | connection error on the CAS | Propagates as today; the gather absorbs it and the siblings still drain; the row is already in `result.processed` | `_log_row_error` on the gathered exception |
| Non-success row | error / quota / degraded branch | No advance, no `unrecorded_completions` — unchanged | Unchanged |

</intent-contract>

## Code Map

- `src/core/backfill_runner.py:419-454` -- `Checkpoint`: the class this story changes (`load`, `processed_total`, `advance`).
- `src/core/backfill_runner.py:550-562` -- `_LEASE_RENEW_LUA` / `_LEASE_RELEASE_LUA`: the shape and comment style the new script follows.
- `src/core/backfill_runner.py:565-668` -- `BackfillLease`: `key`, `token`, `_cas`'s eval-or-fallback pattern to mirror (note it branches on script identity).
- `src/core/backfill_runner.py:64-124` -- `_warn_non_atomic_fallback` (per-surface latch), `_decode`, `_reply_is_true`.
- `src/core/backfill_runner.py:1335-1405` -- `BackfillResult` + `to_dict` (no test pins the exact key set; `test_backfill_runner.py:644` reads individual keys).
- `src/core/backfill_runner.py:1703-1713` -- `_publish`, fu7's guard: the policy this story must share, not duplicate.
- `src/core/backfill_runner.py:1729-1743` -- `_lease_held` / `result.lease_lost` (terminal, logs once).
- `src/core/backfill_runner.py:1973-1986` -- `_worker`'s success branch: the single `checkpoint.advance` call site.
- `src/core/backfill_runner.py:2183-2190`, `:2216-2219` -- the drain's `return_exceptions=True` (it exists *because* `advance` is outside the worker's `except`) and the closing guarded publish.
- `src/core/backfill_runner.py:2233-2239` -- `_log_lease_lost` (its `reason=` must stop claiming "renew refused" as the only cause).
- `scripts/dev/backfill_gemma.py:771` -- the run's `Checkpoint(...)` construction, where the lease gets wired; `:572` is the read-only `--status` one that must stay lease-less.
- `scripts/dev/backfill_gemma.py:2007-2011` -- `lease` is `None` only for `--dry-run`; every real pass holds it before `_run`.
- `scripts/dev/backfill_gemma.py:203-213`, `:1296-1307`, `:2139-2141` -- `_LEASE_LOST_TITLE` / `_LEASE_LOST_LINES` ("The checkpoint is intact…") and the two exit-7 banner sites.
- `src/api/admin.py:687-697` -- the API's read-only `Checkpoint` (its `BackfillLease` carries a foreign owner token; it must not be wired in).
- `src/core/enrichment_rerun.py:249-290` + `scripts/dev/backfill_gemma.py:761-762` -- proof that resume is `mode=missing` set subtraction ordered by `first_seen`, never by `last_property_id`.
- `src/adapters/db/models.py:113-122` -- `Property.id` is a random UUID (`public_id` is the monotonic one, and it is not what the checkpoint stores).
- `src/tests/unit/test_backfill_control.py:48-176` -- `FakeRedis` (no `eval`), `EvalRedis` (identity dispatch, `assert numkeys == 1`), `BytesRedis`; `:850-863` `_run_with_real_control`; `:984-1043`, `:1168-1212` the existing lease-steal tests to model the handover on.
- `src/tests/unit/test_backfill_runner.py:177-185`, `:307-308`; `test_backfill_circuit_breaker.py:363-387`; `test_backfill_start_request.py:413-446` -- the existing checkpoint locks that must keep passing unchanged (all construct `Checkpoint` without a lease).
- `src/tests/integration/test_backfill_lua_scripts.py:31-111` -- real-Redis fixture, prefix hygiene, and the lease-CAS tests the new script's test sits beside.

## Tasks & Acceptance

**Execution:**
- [x] `src/core/backfill_runner.py` -- add `_CHECKPOINT_ADVANCE_LUA` (KEYS[1] checkpoint, KEYS[2] lease; ARGV token/id/date; refuse with `0` when the token does not match, else `hset` + `hincrby` and return `1`) and give `Checkpoint.__init__` an optional `lease` handle; `advance()` returns `bool`, taking the eval path when available and the `_warn_non_atomic_fallback("checkpoint advance")` get-then-write path otherwise, and keeping today's unconditional write when no lease is wired.
- [x] `src/core/backfill_runner.py` -- in `run_backfill`, add `_owns_shared_state()` (`not result.lease_lost`) and use it in `_publish`; add `_note_lease_lost(reason)` used by both `_lease_held` and the new `_record_completion(property_id)`, which skips the write when the run no longer owns shared state and treats `advance(...) is False` as a fresh loss; call it from `_worker`'s success branch in place of `checkpoint.advance`.
- [x] `src/core/backfill_runner.py` -- `BackfillResult.unrecorded_completions` (+ `to_dict`), and a `_log_checkpoint_declined` line naming how many completions the shared checkpoint declined and why; widen `_log_lease_lost`'s `reason` so it covers both detectors.
- [x] `scripts/dev/backfill_gemma.py` -- wire `lease=lease` into `_run`'s `Checkpoint` (and only that one); make the lease-lost banner body a function of the result so a drain with unrecorded completions says so instead of only "The checkpoint is intact".
- [x] `src/tests/unit/test_backfill_checkpoint_handover.py` -- NEW; TDD over every I/O matrix row: `Checkpoint.advance` with/without a lease against `FakeRedis`, `EvalRedis` and `BytesRedis`; the real handover through `run_backfill` (owner loses the lease mid-drain, successor has already advanced past, rows finish) asserting no rewind and no double count; the CAS-as-detector case; the `None`-returning double; the non-atomic fallback warning.
- [x] `src/tests/unit/test_backfill_control.py` -- extend `EvalRedis` to dispatch the new script (two keys) without disturbing the existing four; keep the `assert numkeys` guard meaningful.
- [x] `src/tests/integration/test_backfill_lua_scripts.py` -- real-Redis coverage: the advance CAS writes for the owner, writes nothing for a foreign token (key stays absent), refuses as `False` against bytes replies, and never touches the lease key.
- [x] `src/tests/unit/test_backfill_gemma_cli.py` -- the run's checkpoint is constructed with the lease and `--status`'s is not; the exit-7 banner reports unrecorded completions when there are any.
- [x] `docs/features/v0.13-s3.4-checkpoint-advance-semantics.md` -- feature doc from `docs/features/_template.md` (all sections), recording the mechanism choice, the rejected monotonic-ordering option with its evidence, and what an operator sees after a handover.
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` -- close DW-11 with a `resolution:` and `status: done 2026-08-12`.
- [x] `_bmad-output/implementation-artifacts/sprint-status.yaml` -- `3-4-checkpoint-advance-semantics: in-progress` (never `done` — that follows the merge).

**Acceptance Criteria:**
- Given a runner that lost its lease while rows were still draining and a successor that has already advanced the shared checkpoint, when the drained rows finish, then the checkpoint hash still holds the successor's `last_property_id`, `last_run_date` and `processed_total`, and the displaced run reports those rows in `processed` + `unrecorded_completions` instead.
- Given the lease is stolen without any renew having failed yet, when the next successful row tries to record itself, then the write is refused at Redis, `result.lease_lost` becomes True with one log line, the launch loop stops launching, and the drain still completes.
- Given `Checkpoint` constructed without a lease (status snapshot, `--dry-run`, every pre-existing test), when `advance()` is called, then it writes exactly as before and the existing checkpoint tests pass unmodified.
- Given the regression suite, when the new handover test runs against the pre-fix `advance`, then it fails (rewind and/or double count observed) — the fix is what makes it pass.
- Given `bash scripts/agent/validate.sh all`, when it runs, then it is green and `git grep -n "from adapters\|from api" src/core/backfill_runner.py` returns nothing (AD-1).

## Spec Change Log

## Review Triage Log

### 2026-08-12 — Review pass (iteration 1)

- intent_gap: 0
- bad_spec: 0
- patch: 10: (high 0, medium 4, low 6)
- defer: 3: (high 0, medium 2, low 1)
- reject: 7: (high 0, medium 1, low 6)
- addressed_findings:
  - `[medium]` `[patch]` Nothing enforced the wiring the whole guarantee rests on: `run_backfill(lease=<real>, checkpoint=<ungated>)` is constructible, reinstates DW-11 for a whole pass, and `advance()` returns `True` for it. Added the public `Checkpoint.lease_gated` and a one-time `backfill_checkpoint_ungated` warning naming DW-11, plus tests for both the ungated and the correctly-wired/lease-less cases (`is False`, so duck-typed doubles stay silent).
  - `[medium]` `[patch]` The headline regression stole the lease on the *first* row, so no row of the displaced run was ever recorded — a fix that suppressed **every** checkpoint write would have passed it unchanged. Added `test_rows_recorded_before_the_loss_survive_it`: two rows recorded under our own lease, the third declined after the steal, both halves asserted in one run.
  - `[medium]` `[patch]` `_record_completion` sat *above* the success branch's `consecutive_degraded = 0` / `degraded_run_ids.clear()`, and it talks to Redis and propagates by design — so one blip left a genuinely successful row counted as consecutive degradation and walked story 3.2's AI breaker towards a trip with no evidence. Resets moved ahead of the write, with a regression that opens the breaker on the pre-fix ordering.
  - `[medium]` `[patch]` A raising `advance` (Redis blip) left the row uncounted in `unrecorded_completions`, so the banner under-reported exactly the `processed` vs `processed_total` gap it exists to explain. Counted before the re-raise; containment unchanged (the drain's `return_exceptions` still absorbs it).
  - `[low]` `[patch]` A raising `eval` — scripting disabled, a rejected script body, a `CROSSSLOT` on a clustered client — surfaced once per finished row as an anonymous row error and froze the checkpoint for the whole run. It now degrades once to the still-token-guarded fallback (`backfill_checkpoint_eval_failed`), so DW-11 stays closed either way.
  - `[low]` `[patch]` The refusal reason asserted "another runner holds the lease" as fact, but the CAS also refuses when the key simply lapsed with no successor at all — while `_lease_held` deliberately says "may hold" for the same evidence. Reworded to what is actually proven: this run no longer holds it.
  - `[low]` `[patch]` `result.last_property_id` can now disagree with the shared marker after a handover; documented at the assignment (it is this run's own last row, and `unrecorded_completions` says whether the two can be expected to agree).
  - `[low]` `[patch]` The feature doc's reproduction recipe did not reproduce: reverting the pre-fix `advance` also drops the `lease=` constructor argument, so the module dies with `TypeError` before any assertion. Corrected to "revert the body, keep the argument", with the mixed-case test named as the regression's other half.
  - `[low]` `[patch]` `--continuous` prints the declined-rows line under a summary whose `enriched this run` is cumulative across cycles while the count is the final pass's. Line now says "in this pass", and the doc's "once per run" corrected to once per pass.
  - `[low]` `[patch]` The doc claimed the counter delivers "each row once"; it delivers **at most** once (a drained row the successor never re-fetches is counted zero times). Stated precisely, and the two-key script's single-node assumption documented in the Lua comment.

Deferred (3, ledger): the displaced runner still *clears* the successor's `:active` heartbeat at the end of its drain (pre-existing, in the CLI's `_go` finally, one row wide against `migrate-primary.sh`); epics.md's story 3.4 still promises a re-enrichment gap that never existed and an exactly-once counter that is at-most-once (a plan-of-record edit for the epic retrospective); `unrecorded_completions` stays off the wire, so the Operações card shows a `processed_total` that silently stops moving.

Rejected (7): `_reply_is_true`'s permissive tail turning an odd client reply into a fabricated lease loss (fail-safe direction — it stops writing — and the reply shape is Redis's integer contract, which this module's convention already encodes); `assert 0 < len(seen) < 6` being a range where the schedule is arguably deterministic (matches the sibling lease-steal tests, and over-tightening a scheduler-dependent bound is fragile); the unit suite mirroring the Lua in Python (the documented reason `test_backfill_lua_scripts.py` exists); the new test module re-declaring `_rows`/`_budget` and `BytesEvalRedis` duplicating two bytes methods; `lease: Any` instead of a `Protocol` (every other injected collaborator in this module is duck-typed the same way); DW-11 being closed in the branch that has not merged yet and its long `resolution:` (both are the project's established convention — DW-18 closed identically); and the newline-only diff on `.bmad-loop/operator/3-3-budget-counts-requests.json` (a pre-commit fixer edit, which CLAUDE.md says to commit). One reviewer claim was checked and found false — `_log_checkpoint_declined` *is* called (`src/core/backfill_runner.py`, end of `run_backfill`) — so only its "no test asserts it" half survived, now covered by the mixed-case test; likewise `getattr(result, "unrecorded_completions", …)` is load-bearing, because the migration-wait path calls `_lease_lost_lines()` with no result at all.

## Design Notes

**Why lease-gating and not a monotonic compare-and-set on the id ordering.** The epic left both open. Monotonic ordering is not expressible over what is actually stored: `Property.id` is a random UUID (`models.py:113-117`), the launch order is `first_seen` (`backfill_gemma.py:761-762`), and rows land in completion order from up to `concurrency` workers — so "forward" has no definition. It would also protect nothing: `fetch_candidate_rows` never receives `last_property_id`; resume is `mode=missing` set subtraction (`enrichment_rerun.py:279-286`). DW-11's "the next resume rewinds and re-enriches the gap" therefore overstates the harm — the real damage is a lying resume marker and an inflated all-time counter on the two operator surfaces that read them (`--status`, `GET /admin/backfill/status`). Lease-gating is the only mechanism that matches the actual failure.

**The trade-off, stated.** A drained row's work is real and this drops its bookkeeping: `processed_total` will not count it and `last_property_id` will not name it. That is the deliberate price of the AC's "counts each row once", and it is the right direction — the successor re-fetched those same rows as candidates, so counting the loser's copy double-counts the *property*, while declining it merely under-reports an all-time counter nobody resumes from. Nothing that matters is lost: the enrichment itself is committed to Postgres by `run_enrichment`, the row leaves the candidate set, and the run still reports the work in `result.processed`, in `backfill_done`, and now in `unrecorded_completions` plus the exit-7 banner.

**One policy, two surfaces.** fu7's guard and this one must not drift, so `_publish` and the advance both ask `_owns_shared_state()`, and the CAS refusal — a *detector*, not a second policy — sets the same `result.lease_lost` flag that predicate reads. That also closes the check-then-act window an in-process flag leaves open (up to `lease_ttl/3` = 300s at the shipped 900s TTL), which is the same defect class `migrate-primary.sh` was fixed for in v0.13-fu6.

```lua
-- KEYS[1] <prefix>:checkpoint, KEYS[2] <prefix>:lease
-- ARGV[1] our lease token, ARGV[2] property id, ARGV[3] run date (ISO, Python-computed)
if redis.call('get', KEYS[2]) ~= ARGV[1] then
  return 0
end
redis.call('hset', KEYS[1], 'last_property_id', ARGV[2], 'last_run_date', ARGV[3])
redis.call('hincrby', KEYS[1], 'processed_total', 1)
return 1
```

```python
# run_backfill — the success branch's recorder
def _record_completion(property_id: str) -> None:
    if not _owns_shared_state():
        result.unrecorded_completions += 1
        return
    # ``is False`` and not falsiness: duck-typed checkpoints in the suite
    # return None, and a None read as a refusal would fabricate a lease loss.
    if checkpoint.advance(property_id) is False:
        _note_lease_lost("checkpoint CAS refused — another runner holds the lease")
        result.unrecorded_completions += 1
```

**Why the API's checkpoint stays lease-less.** `_backfill_primitives()` builds a `BackfillLease` with owner `admin-api` purely to *name* a holder in refusals; wiring that token into its `Checkpoint` would gate a read-only object on a token it never holds. It never advances, so it keeps today's constructor.

## Verification

**Commands:**
- `bash scripts/agent/validate.sh fast` -- expected: lint + unit green, including the new handover suite.
- `bash scripts/agent/validate.sh backend` -- expected: green; runs the new real-Redis CAS tests against the ephemeral test stack.
- `bash scripts/agent/validate.sh all` -- expected: full gate green (also run by `finish-feature.sh`).
- `git grep -n "from adapters\|from api" src/core/backfill_runner.py` -- expected: no matches (AD-1).

**Manual checks (if no CLI):**
- Confirm the handover regression fails on the pre-fix tree (stash the `advance` change alone and watch the rewind/double-count assertions fail), not merely that it passes afterwards.

## Auto Run Result

**Status:** `awaiting-operator` — everything an agent can do is implemented, reviewed, patched, committed and verified as far as this host allows. What remains is outside the repo: the Docker daemon is down, so `validate.sh all` (and with it the new real-Redis Lua tests) could not run, and the merge belongs to the orchestrator. See frontmatter `operator_actions`.

**Implemented change.** `<prefix>:checkpoint` is one hash every runner writes, and in-flight rows always drain after a lease loss by design — so a displaced runner's late completions stamped their own row id and run date over the successor's marker and inflated the shared all-time counter (DW-11). `Checkpoint` now takes an optional lease handle and `advance()` is an owner-token compare-and-set returning `bool`: `_CHECKPOINT_ADVANCE_LUA` (checkpoint + lease as KEYS, token/id/Python-computed date as ARGV) on any client exposing `eval`, degrading once — never per row — to the codebase's token-guarded `get`-then-write fallback when scripting is unavailable, and keeping the unconditional legacy write when no lease is wired (`--status`, `--dry-run`, the admin API's read-only checkpoint, every pre-existing test). `run_backfill` has **one** ownership predicate, `_owns_shared_state()`, behind both `_publish` (v0.13-fu7's guard) and the new `_record_completion`; a CAS refusal is a *detector* feeding the same `_note_lease_lost` latch, which closes the up-to-300s window an in-process flag alone leaves at the shipped `lease_ttl_seconds: 900`. Declined bookkeeping is never silent: `BackfillResult.unrecorded_completions` (in `to_dict`), one end-of-pass `backfill_checkpoint_declined` line, and the exit-7 banner. The monotonic-CAS alternative was ruled out on evidence, not taste — `Property.id` is a random UUID, launch order is `first_seen`, and nothing reads `last_property_id` back (resume is `mode=missing` set subtraction), which also means DW-11's "re-enrichment gap" never existed and the real damage was a lying marker plus an inflated counter.

**Files changed**
- `src/core/backfill_runner.py` — `_CHECKPOINT_ADVANCE_LUA`; `Checkpoint(lease=…)`, `.lease_gated`, `advance() -> bool` (CAS / degrading fallback / legacy); `_owns_shared_state`, `_note_lease_lost`, `_record_completion`, the ungated-wiring warning; the success branch's breaker resets moved ahead of the shared write; `BackfillResult.unrecorded_completions`; `_log_checkpoint_declined` / `_log_checkpoint_eval_failed` / `_log_checkpoint_ungated` and a widened `_log_lease_lost(reason)`.
- `scripts/dev/backfill_gemma.py` — the run's `Checkpoint` is built with the run's lease (`--status`/`--dry-run` unchanged); `_unrecorded_completion_lines` / `_lease_lost_lines` make the exit-7 banner a function of the result, worded per pass.
- `src/tests/unit/test_backfill_checkpoint_handover.py` (NEW, 30 tests), `test_backfill_control.py` (`EvalRedis` dispatches the two-key script), `test_backfill_gemma_cli.py` (lease wiring + banner), `test_backfill_lua_scripts.py` (real-Redis CAS).
- `docs/features/v0.13-s3.4-checkpoint-advance-semantics.md` (NEW); `deferred-work.md` — DW-11 closed, 3 entries opened; `sprint-status.yaml` — `3-4` to `in-progress`.

**Review findings.** 10 patches applied (4 medium, 6 low), 3 deferred to the ledger, 7 rejected, 0 intent gaps, 0 spec repairs — full breakdown in the Review Triage Log above. Two reviewer claims were checked against the tree and found false (`_log_checkpoint_declined` is called; the CLI's `getattr` on `unrecorded_completions` is load-bearing) and are recorded as such rather than "fixed".

**Verification.** `bash scripts/agent/validate.sh fast` — lint green (all pre-commit hooks + eslint, no fixer edits), unit `2 failed, 2110 passed`; both failures are `test_no_data_destroying_scripts.py::test_volumes_flag_is_refused_not_silently_ignored[stop.sh|clean.sh]`, which shell out to `stop.sh --volumes` and die on "docker is not running" before printing the refusal they assert — untouched by this diff and failing identically on the baseline. `git grep -n "from adapters\|from api" src/core/backfill_runner.py` → no matches (AD-1). The regression was observed failing on the pre-fix tree (`assert 'prop-2' == 'successor-row'` — the rewind itself — plus 21 others) before the fix made it pass.

**Residual risks.** The real-Redis Lua tests have never executed (no Docker), so the shipped script body is proven only against the `EvalRedis` mirror — that is the first thing the merge gate exercises. The counter's semantics is at-most-once, not exactly-once, for drained rows the successor never re-fetches (documented). A displaced runner still clears the successor's `:active` heartbeat at the end of its drain (deferred, pre-existing).

## Operator Confirmation

Confirmed 2026-08-13: the external actions this story owed were carried out.

- Start Docker Desktop on the Windows host and enable WSL integration for this distro. The daemon is down (`docker info` fails; `docker` is not a usable binary in this distro), which is the only reason the full gate could not run.
- With Docker up, re-run `bash scripts/agent/validate.sh all` from this worktree and confirm it is green — this is the one acceptance criterion this run could not verify, and the first execution of the 5 new real-Redis tests in `src/tests/integration/test_backfill_lua_scripts.py` that prove the shipped Lua body itself (the unit suite only exercises a Python mirror of it). Expect the two `test_no_data_destroying_scripts.py::test_volumes_flag_is_refused_not_silently_ignored[stop.sh|clean.sh]` failures to disappear: they shell out to `stop.sh --volumes`, which aborts with "docker is not running" before printing the refusal they assert, and they fail identically on the untouched baseline.
- Let the bmad-loop orchestrator merge this branch. `finish-feature.sh` refuses it ("branch does not have a valid conventional type prefix"), as it does every `bmad-loop/<run>/<story>` branch — do not merge by hand.
- After the merge lands on `main` and is pushed, set `3-4-checkpoint-advance-semantics: done` in `_bmad-output/implementation-artifacts/sprint-status.yaml` (it is `in-progress` now).
- Optionally prove the handover end to end, which no agent can do here: with a backfill running, take its lease from a second shell (`redis-cli SET backfill:gemma:lease other-token KEEPTTL`), then confirm the pass exits 7 with the BACKFILL LEASE LOST banner naming the rows it drained, that `redis-cli HGETALL backfill:gemma:checkpoint` still shows the marker and `processed_total` you set, and that the journal carries one `backfill_checkpoint_declined` line.

_Appended by the bmad-loop orchestrator (`bmad-loop confirm`, #335): a human confirmed these external actions out of band, and the story was advanced from `awaiting-operator` to `done`._
