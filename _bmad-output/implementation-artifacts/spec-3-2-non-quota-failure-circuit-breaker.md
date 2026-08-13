---
title: 'Non-quota AI failures must not fabricate a score'
type: 'bugfix'
created: '2026-08-12'
status: done
baseline_revision: '4bad757b565197ab375da927e0d584f3522c8df4'
final_revision: '64ee0fbf1b931b68445b587b5f33f576da119632'
review_loop_iteration: 1
followup_review_recommended: true
operator_actions:
  - 'Start Docker Desktop on the Windows host and enable WSL integration for this distro. The daemon is down (`docker.exe info` reports the `dockerDesktopLinuxEngine` pipe missing, and `docker` is not a usable binary in this distro), which is the only reason the full gate could not run.'
  - 'With Docker up, re-run `bash scripts/agent/validate.sh all` from this worktree and confirm it is green — this is the one acceptance criterion this run could not verify. Expect the two `test_no_data_destroying_scripts.py::test_volumes_flag_is_refused_not_silently_ignored[stop.sh|clean.sh]` failures to disappear: they shell out to `stop.sh --volumes`, which aborts with "docker is not running" before printing the refusal they assert, and they fail identically on the untouched baseline.'
  - 'Let the bmad-loop orchestrator merge this branch. `finish-feature.sh` refuses it ("branch does not have a valid conventional type prefix"), as it does every `bmad-loop/<run>/<story>` branch — do not merge by hand.'
  - 'After the merge lands on `main` and is pushed, set `3-2-non-quota-failure-circuit-breaker: done` in `_bmad-output/implementation-artifacts/sprint-status.yaml`.'
  - 'Optionally prove the breaker end to end, which no agent can do: point `GEMINI_API_KEY` at a revoked value, run one `scripts/dev/backfill_gemma.py` pass, and confirm it exits 9 with the "AI backend kept returning fabricated results" banner, that no `ai_score` was written for those rows, and that they are still counted as candidates by `--status`.'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-3-context.md'
warnings: ['oversized']
---

<intent-contract>

## Intent

**Problem:** Every AI-client exception that is not a quota refusal is swallowed into a fabricated result — `VisualResult(condition_score=0.5, analysis="Error")` / `SentimentResult(sentiment_score=0.5, ...)` (`src/adapters/ai/client.py:639,667,823,858`) — which `run_enrichment` blends into `ai_score = 0.5`, persists and commits (`src/adapters/queue/tasks.py:741-764`); because `mode_is_missing_ai` is `not score` (`src/core/enrichment_rerun.py:85-90`), `0.5` is truthy and the row leaves the candidate set permanently. A revoked `GEMINI_API_KEY` (401), a retired model id (404) or a DNS/proxy outage is none of `_RETRY_STATUS` or `_QUOTA_BODY_MARKERS`, so an unattended `--continuous` run stamps ~4,600 properties a day with a fake score behind a healthy-looking progress banner (DW-17).

**Approach:** Carry the failure as a **typed marker on the result** — a `degraded: bool` field on the three result models, set only on the exception fallbacks — and act on it in two places: `run_enrichment` refuses to persist a score built from a degraded visual/sentiment result (raising a distinguished `AIResultDegradedError` before it opens a session), and `run_backfill` counts *consecutive* degraded rows into a circuit breaker that stops launching once a threshold is crossed. The client still degrades exactly as it does today — nothing about the local template fallback or the quota re-raise changes.

## Boundaries & Constraints

**Always:**
- The signal is the typed marker plus the distinguished exception. **Never** `analysis == "Error"`, never a score-value comparison (`== 0.5`), never a class-name string in feature code.
- `src/core/backfill_runner.py` recognises the degraded error **duck-typed** (`getattr(exc, "is_degraded_result", False)`), exactly like `is_quota_exhausted` (`backfill_runner.py:982-996`) — no new `core` → `adapters`/`api` import (AD-1).
- The quota path is untouched: `_reraise_if_quota` still fires first, so a quota error never becomes a degraded result; the `_worker` quota branch (`backfill_runner.py:1657-1667`) keeps its rollback + `BACKING_OFF` publish, and a quota refusal never feeds the breaker counter.
- The local template fallback is preserved: `template_deal_verdict()` still returns the same verdict text and `confidence=0.0`, `_llm_verdict` still swallows its exception rather than raising, and a degraded *verdict alone* still persists (it does not touch `ai_score` and so cannot retire a row).
- `neutral_sentiment_no_description()` (`src/adapters/ai/enrich_pipeline.py:21`) is a legitimate 0.5 and must stay `degraded=False`.
- A degraded row leaves **no** persisted score, **no** advanced checkpoint and **no** retired row: the raise happens before `SessionLocal()` in `run_enrichment`, so `_worker`'s `except` branch skips the `else:` that calls `checkpoint.advance` (`backfill_runner.py:1674-1677`).
- The breaker threshold is config (`backfill.max_consecutive_ai_failures`, NFR-2) with its meaning documented in `configs/app_config.yaml`; `<= 0` disables the breaker without re-enabling fabrication.
- New `degraded` fields default to `False` so `VisualResult(condition_score=0.5)` in `src/tests/unit/test_ai_quality.py:150` (the `validate-ai.sh` gate) keeps constructing.

**Block If:**
- Closing the persist gate would require changing `mode_is_missing_ai`'s predicate or the candidate-set SQL (`src/core/enrichment_rerun.py:279-286`) — that is a corpus-semantics decision this story does not own.
- The chosen mechanism cannot avoid a new `BackfillState` wire value (see **Never**).

**Never:**
- Do NOT add or rename a `BackfillState` value, its pt-BR label or any admin/UI surface: `BACKING_OFF` is documented as "the provider refused on quota" (`backfill_runner.py:441-447`) and the frontend maps the enum exhaustively (`frontend/src/api.ts:262`, `frontend/src/components/operations/lines.ts:17`). A tripped breaker publishes what a finished pass publishes today and reports itself through `BackfillResult`, logs and the CLI exit code instead.
- Do NOT touch `mode_is_missing_ai`, the candidate-set SQL, `AttemptLedger` semantics, `DailyBudget` accounting (story 3.3), `checkpoint.advance`'s own rule (story 3.4), the scrapers, the primary docker stack, or the live Celery routing.
- Do NOT weaken or neutralize the existing tests that pin the 0.5 fallback value (`test_ai_quota_propagation.py:162-190`, `test_ai_client.py:253,271,503,515`) — the fallback *value* is unchanged; extend them with the marker assertion.
- Do NOT make the breaker count ordinary row errors (a DB failure, a bad image) — `test_backfill_control.py:761` pins that one ordinary error must not stop a run.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Healthy row | client returns real results (`degraded=False`) | `run_enrichment` persists + commits; `_worker` counts `processed`, advances checkpoint; consecutive counter resets to 0 | No error expected |
| Revoked key / retired model / DNS outage | `analyze_visuals` or `analyze_text` returns its fallback with `degraded=True` | `run_enrichment` raises `AIResultDegradedError` **before** `SessionLocal()`; nothing persisted, no commit, no checkpoint advance | `_worker` counts `errors`, appends `error_ids`, `ledger.record_error(pid)`, `result.ai_fallbacks += 1`, consecutive += 1 |
| Threshold crossed | `max_consecutive_ai_failures` consecutive degraded rows | `result.ai_circuit_open = True`; launch loop breaks at the same two points quota does (`:1752`, `:1811`); in-flight rows still drain via the final `gather` | Run returns normally; no exception escapes `run_backfill` |
| Recovery | degraded rows then one successful row | counter resets to 0; breaker never trips | No error expected |
| Interleaved with quota | degraded row(s), then a 429 that survives retries | quota branch wins: `quota_exhausted`/`budget_exhausted` set, `rollback_attempt`, `BACKING_OFF` published, run stops on quota; counter untouched, `ai_circuit_open` stays False | Existing quota behaviour unchanged |
| Breaker disabled | `max_consecutive_ai_failures <= 0` | no trip, run continues; every degraded row still persists nothing | Rows keep erroring; `AttemptLedger` quarantines them on `max_attempts` as it does any failing row |
| Degraded verdict only | visual+sentiment real, `summarize_deal`/`_llm_verdict` falls back | scores persist as today; `meta["deal_verdict"]` gains `"degraded": true` next to the unchanged verdict/confidence; row counts as processed | Not an error; breaker not fed |
| No description | `neutral_sentiment_no_description()` | `degraded=False` → persists normally | No error expected |
| `--continuous` pass with the breaker tripped | `result.ai_circuit_open` | loop returns `EXIT_AI_CIRCUIT_OPEN` with a banner naming the likely causes — not a 24h RPD sleep, not `EXIT_STALLED`, not exit 0 | Terminal; `--serve` survives the non-zero child (`backfill_gemma.py:1589`) |
| Live `ai_enrich` task | degraded result on the Celery path | `run_enrichment` raises → existing `except` retries (`tasks.py:924-926`, `max_retries=5`); no `0.5` ever committed | Unchanged retry policy |

</intent-contract>

## Code Map

- `src/adapters/ai/client.py:300-334` -- `VisualResult` / `DealVerdictResult` / `SentimentResult` Pydantic models; the marker field lands here.
- `src/adapters/ai/client.py:225-270` -- `AIClientError`, `AIQuotaExhaustedError` (`is_quota_exhausted = True`), `_reraise_if_quota`; the new `AIResultDegradedError` belongs beside them.
- `src/adapters/ai/client.py:387-405,570-575,637-639,665-667,741-746,821-823,856-858` -- the seven non-quota fallback returns to mark.
- `src/adapters/ai/client.py:191` -- `template_deal_verdict()`; unchanged.
- `src/adapters/ai/enrich_pipeline.py:21,33-54` -- honest neutral sentiment (stays undegraded) and the visual→text sequence.
- `src/adapters/queue/tasks.py:701-768` -- `run_enrichment`: the persist gate goes between `analyze_visual_and_sentiment` (`:734`) and `a_score` (`:741`).
- `src/adapters/queue/tasks.py:625-652` -- `_write_deal_verdict`; records the verdict marker in `meta`.
- `src/adapters/queue/tasks.py:924-926` -- `ai_enrich`'s `except` → `self.retry`; the live path's reaction.
- `src/core/backfill_runner.py:973-996` -- `_QUOTA_MARKERS` / `is_quota_exhausted`, the duck-typed pattern to mirror.
- `src/core/backfill_runner.py:1220-1266` -- `BackfillResult` + `to_dict`.
- `src/core/backfill_runner.py:1391-1488,1652-1696,1749-1841` -- `run_backfill` signature, `_worker`, launch loop (quota breaks at `:1752`, `:1811`).
- `src/core/backfill_runner.py:1883-1958` -- `_log_*` helpers (lazy `get_logger`).
- `src/core/backfill_runner.py:430-448` -- `BackfillState`; read-only here.
- `scripts/dev/backfill_gemma.py:175-181` -- `EXIT_*` codes (0,3,4,5,6,7,8 taken).
- `scripts/dev/backfill_gemma.py:523-540,777-803` -- `_enrich_one`, the single `run_backfill` call site.
- `scripts/dev/backfill_gemma.py:1202-1263,2001-2010` -- `_run_continuous` terminal branches and `main`'s one-shot exit mapping.
- `configs/app_config.yaml:341-381` + `src/infra/config.py` (`backfill` model) -- threshold config.
- `src/tests/unit/test_backfill_control.py:47-210` -- `FakeRedis`/`EvalRedis`/`BytesRedis`, `_rows`, `_budget`, `_checkpoint`, `_noop_sleep`, `_ScriptedControl`, `_QuotaError`; the doubles a new runner test reuses.
- `src/tests/unit/test_ai_quota_propagation.py:38-59,162-190` -- client doubles and the non-quota-fallback lock to extend.

## Tasks & Acceptance

**Execution:**
- [x] `src/adapters/ai/client.py` -- add `degraded: bool = False` to `VisualResult`, `SentimentResult`, `DealVerdictResult`; add `AIResultDegradedError(AIClientError)` with `is_degraded_result = True`; set `degraded=True` on all seven non-quota fallback returns -- the typed marker AC-1 demands instead of the `"Error"` string.
- [x] `src/adapters/queue/tasks.py` -- in `run_enrichment`, raise `AIResultDegradedError` when `v_res.degraded or s_res.degraded`, before `a_score`/`SessionLocal()`; in `_write_deal_verdict`, record `"degraded": verdict_res.degraded` alongside verdict/confidence -- stops the fabricated score at the single write authority (AD-10) on both the backfill and live paths.
- [x] `src/core/backfill_runner.py` -- add `is_degraded_result(exc)` (duck-typed, no text safety net); `BackfillResult.ai_fallbacks`/`ai_circuit_open` (+ `to_dict`); `run_backfill(..., is_degraded_error=is_degraded_result, max_consecutive_ai_failures=3)`; a third `_worker` branch that counts, logs and trips; reset-on-success; launch-loop breaks beside the quota ones; `_log_ai_fallback` / `_log_ai_circuit_open` -- the consecutive-fallback breaker AC-1 specifies.
- [x] `configs/app_config.yaml` + `src/infra/config.py` -- `backfill.max_consecutive_ai_failures: 3` with a comment stating the meaning and that `<= 0` disables the breaker only, never the persist gate -- NFR-2.
- [x] `scripts/dev/backfill_gemma.py` -- pass the config threshold into `run_backfill`; add `EXIT_AI_CIRCUIT_OPEN = 9`; terminal branch + operator banner in `_run_continuous` (after the stop branch, before the budget/stall branches) and in `main`'s one-shot exit -- so an unattended run reports the real cause instead of sleeping a 24h window or exiting 0.
- [x] `src/tests/unit/test_backfill_circuit_breaker.py` -- NEW; TDD over the matrix rows that belong to `run_backfill`: below threshold, at threshold, recovery reset, interleaving with quota back-off, breaker disabled, in-flight drain, no checkpoint advance / no double-count, `to_dict` shape.
- [x] `src/tests/unit/test_ai_quota_propagation.py` + `src/tests/unit/test_ai_client.py` -- extend (never neutralize) the existing fallback locks with `degraded is True`, and assert a quota error still re-raises undegraded.
- [x] `src/tests/unit/test_run_enrichment_degraded.py` -- NEW; the regression that fails before the fix: a degraded visual/sentiment result persists no `MetricsScoring` row, commits nothing and raises; an undegraded one (including `neutral_sentiment_no_description`) persists exactly as today.
- [x] `src/tests/unit/test_backfill_gemma_cli.py` -- extend: a tripped breaker exits `EXIT_AI_CIRCUIT_OPEN` from both `--continuous` and one-shot, and does not take the quota/stall branch.
- [x] `docs/features/v0.13-s3.2-non-quota-failure-circuit-breaker.md` -- feature doc from `docs/features/_template.md` (all sections), including the threshold knob and what an operator sees when it trips.
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` -- close DW-17 with the resolution.

**Acceptance Criteria:**
- Given a revoked key, a retired model id or a transport outage during a backfill pass, when the run reaches its `max_consecutive_ai_failures`-th consecutive degraded row, then no property has a persisted `ai_score`, the checkpoint has not advanced past any of them, every one of them is still a `mode=missing` candidate, and the run stops launching.
- Given a local backend whose call fails transiently, when the fallback is produced, then `template_deal_verdict()`'s text and `confidence=0.0` are byte-identical to today and the client raises nothing — only the result's marker and what the *consumer* does with it differ.
- Given a provider 429 that survives the client's retries, when it propagates, then the story-1.3 quota path behaves exactly as before (re-raise, `rollback_attempt`, `BACKING_OFF`, stop) and the breaker counter is untouched.
- Given `bash scripts/agent/validate.sh all` and `bash scripts/agent/validate-ai.sh`, when they run, then both are green and `src/core/backfill_runner.py` has gained no `adapters`/`api` import.

## Spec Change Log

## Review Triage Log

### 2026-08-12 — Review pass (iteration 1)

- intent_gap: 0
- bad_spec: 0
- patch: 7: (high 0, medium 1, low 6)
- defer: 5: (high 0, medium 3, low 2)
- reject: 5: (high 0, medium 1, low 4)
- addressed_findings:
  - `[medium]` `[patch]` A systemic failure quarantined innocent rows across passes. Each degraded row is charged a ledger attempt at launch, but the pass persists nothing and never advances the checkpoint — so the next start re-fetched exactly the same oldest-first rows and charged them again. Three restarts against an unfixed key retired three good properties, while the banner promised they were still candidates. Tripping the breaker now rolls back the attempts of the consecutive run that proved the backend (not the row) was at fault; degradation below the threshold keeps its charge so a genuinely unusable row still marches to quarantine. Three new unit tests, including the across-passes regression.
  - `[low]` `[patch]` `census.is_complete` was evaluated before the breaker branch, so a trip landing on the last candidates could print `BACKFILL COMPLETE` and exit 0/4 — discarding the banner, the WARNING and exit 9. Guarded with `and not result.ai_circuit_open`, which preserves every existing branch order (the stop branch still serves and clears its request first). CLI test added.
  - `[low]` `[patch]` The DW-17 ledger entry closed with `status: closed`, a value neither half of the sweep's `open` / `done <date>` partition recognises. Now `status: done 2026-08-12`, matching DW-1…DW-7.
  - `[low]` `[patch]` The banner's one actionable line pointed at `--status`, which makes no AI call at all and so cannot diagnose a key or a model id. Reworded to name `GEMINI_API_KEY`, the model id, egress and the journal, and to state that the attempts were rolled back.
  - `[low]` `[patch]` The `degraded` field's six-line contract comment sat above `class VisualResult`, reading as the class's preamble while the field it documents was ten lines below and the two sibling models carried none. Moved onto the field, with a pointer from each sibling.
  - `[low]` `[patch]` The in-flight-drain test asserted `1 <= len(started) <= 3` and `ai_fallbacks == len(started)` — both satisfied by a run that launched exactly one row, which proves nothing about draining. It now pins peak concurrent in-flight `> 1`, that fewer rows launched than the queue held, and that no row repeated.
  - `[low]` `[patch]` `<= 0` was documented as "disables the breaker only", which is true of the persist gate but hid that a disabled breaker never reaches the new rollback either — so a broken backend quarantines the whole queue `max_attempts` passes later. Stated in `config.py`, `app_config.yaml` and the feature doc.

Deferred (5, ledger): an undegraded fabricated 0.5 still reachable when a 200 response's JSON merely omits the score key (`data.get("condition_score", 0.5)` — a model-quality failure, outside this contract's "on every exception" scope); no repair path for rows poisoned before this fix, which is the missing half of the Epic 3 → Epic 2 gate; the live `ai_enrich` path has the refusal but no breaker, so a sustained outage costs ~6 attempts/property; a tripped breaker is invisible on the Operações card (`idle` + `runner_present: true`); the live verdict-only task writes a degraded template verdict with a fresh `enriched_at`.

Rejected (5): a pass that hits **both** quota and the breaker publishes `backing-off` — not a misreport, the provider genuinely refused, and excluding exit 9 from that check would erase a true signal; `meta.visual.degraded`/`meta.sentiment.degraded` are always `false` by construction (cosmetic — the gate raises before they are written); the sentiment call still runs after a degraded visual (bounded to threshold rows); `enriched_at` stamped on a degraded verdict (pre-existing, unchanged by this diff); the one-byte `end-of-file-fixer` edit to `.bmad-loop/operator/3-5-runner-env-contract.json` (the lint gate's own fix — never reverted).

## Design Notes

**Why a marker plus a raise, not a raise from the client.** Making `analyze_visuals` raise on any failure is the smaller diff but it deletes the local resilience contract story 1.3 deliberately fenced (`spec-1-3:29`). The marker keeps the client's behaviour identical and moves the decision to the consumer, which is what AC-2 asks for: *"this story changes what happens to the result, not the local resilience contract."*

**Why the gate lives in `run_enrichment` and not in the backfill driver.** `run_enrichment` is the single write authority (AD-10) and it commits before returning, so a check in `_enrich_one` would be too late. Gating there means the live Celery path stops fabricating too — a deliberate consequence, not scope creep: it is the same corruption, one mechanism rather than two divergent policies, and Epic 2's percentiles compute over the whole corpus, not just backfilled rows. The live blast radius is bounded to `ai_enrich`'s existing retry policy.

**Why degraded rows are charged an error while quota rows are rolled back.** A quota refusal is an account-level condition and blaming the row would quarantine a good property (`backfill_runner.py:1658-1661`). A degraded result is ambiguous — a dead key (systemic) or one property's unparseable response (per-row) — and the per-row case is exactly what `AttemptLedger`'s quarantine exists for (`configs/app_config.yaml:351-355`). The breaker, not the ledger, handles the systemic case: it stops the pass after `max_consecutive_ai_failures` rows, so a systemic outage charges at most that many rows one attempt each per pass.

**Why no new `BackfillState`.** `BACKING_OFF` is defined as a quota refusal and would send an operator to the Gemini dashboard for a revoked key; a new value would need a pt-BR label and a frontend change this epic forbids. The tripped run therefore publishes what it publishes today and speaks through `BackfillResult.ai_circuit_open`, a distinct WARNING log line, and exit code 9.

**Consecutive under concurrency** means consecutive *completions* with no success between them; with `concurrency > 1` up to `concurrency - 1` extra rows may already be in flight when the trip happens. They drain (never cancelled mid-enrichment) and, being degraded, persist nothing.

```python
# src/core/backfill_runner.py — _worker, third branch
elif is_degraded_error is not None and is_degraded_error(exc):
    result.errors += 1
    result.error_ids.append(pid)
    result.ai_fallbacks += 1
    consecutive[0] += 1
    if ledger is not None:
        ledger.record_error(pid, str(exc))
    _log_ai_fallback(prop, consecutive[0], max_consecutive_ai_failures)
    if 0 < max_consecutive_ai_failures <= consecutive[0]:
        result.ai_circuit_open = True
        _log_ai_circuit_open(consecutive[0], max_consecutive_ai_failures)
```

The raised message must not contain any `_QUOTA_MARKERS` substring (`backfill_runner.py:973-979`), or the quota predicate's text safety net would misclassify it as a quota refusal.

## Verification

**Commands:**
- `bash scripts/agent/validate.sh fast` -- expected: lint + unit green, including the new breaker/persist-gate tests.
- `bash scripts/agent/validate-ai.sh` -- expected: green (AI client surface changed); if Ollama is unreachable it exits 0 as a visible skip — record that in the run result rather than claiming a pass.
- `bash scripts/agent/validate.sh all` -- expected: full gate green (also run by `finish-feature.sh`).
- `git grep -n "from adapters" src/core/backfill_runner.py` -- expected: no matches (AD-1).

**Manual checks (if no CLI):**
- The regression test must fail on the pre-fix tree: confirm `test_run_enrichment_degraded.py` fails when the `degraded` gate is removed, not merely that it passes after.

## Auto Run Result

**Status:** `awaiting-operator` — every part an agent can do is implemented, reviewed, patched, committed (`64ee0fb`) and verified as far as this host allows. What remains is a host-level action outside the repo: the Docker daemon is down, so `validate.sh all` could not run (frontmatter `operator_actions`).

**Implemented change.** A non-quota AI-client failure can no longer fabricate a persisted score (DW-17). The three result models carry a typed `degraded` marker set only on the seven non-quota exception fallbacks; `run_enrichment` — the single write authority (AD-10) — raises `AIResultDegradedError` before it opens a session, so nothing is written, nothing is committed, the checkpoint does not advance and the row stays a `mode=missing` candidate; and `run_backfill` counts *consecutive* degraded completions into a circuit breaker that stops launching and rolls back the ledger attempts of the rows that proved the failure systemic. The client's own behaviour is byte-identical — `template_deal_verdict()`'s text and `confidence=0.0` are unchanged and nothing new raises — so the local resilience contract story 1.3 fenced is intact, and the quota path is untouched. `src/core` still imports nothing from `adapters`/`api`; the marker crosses the boundary duck-typed, exactly like `is_quota_exhausted`. No new `BackfillState` value: a tripped run speaks through `BackfillResult.ai_circuit_open`, a WARNING log line and CLI exit code 9.

**Files changed**
- `src/adapters/ai/client.py` — `AIResultDegradedError` (`is_degraded_result = True`); `degraded: bool = False` on `VisualResult` / `SentimentResult` / `DealVerdictResult`; `degraded=True` on the seven non-quota fallbacks.
- `src/adapters/queue/tasks.py` — `run_enrichment` raises before `SessionLocal()`; `_write_deal_verdict` records `meta["deal_verdict"]["degraded"]`.
- `src/core/backfill_runner.py` — `is_degraded_result()`; `BackfillResult.ai_fallbacks` / `.ai_circuit_open` (+ `to_dict`); `run_backfill(is_degraded_error=, max_consecutive_ai_failures=)`; third `_worker` branch with reset-on-success and attempt rollback on trip; two launch-loop breaks beside the quota ones; two log helpers.
- `src/infra/config.py` + `configs/app_config.yaml` — `backfill.max_consecutive_ai_failures: 3` with its documented meaning and the `<= 0` trade-off.
- `scripts/dev/backfill_gemma.py` — `EXIT_AI_CIRCUIT_OPEN = 9`; threshold threaded from config; terminal branch + operator banner in `_run_continuous` (ahead of the budget-sleep and stall branches, and no longer maskable by `census.is_complete`) and in `main`'s one-shot exit.
- `src/tests/unit/test_backfill_circuit_breaker.py` (NEW, 21 tests), `src/tests/unit/test_run_enrichment_degraded.py` (NEW, 9 tests), plus extended `test_ai_quota_propagation.py`, `test_ai_client.py`, `test_backfill_gemma_cli.py`.
- `docs/features/v0.13-s3.2-non-quota-failure-circuit-breaker.md` (NEW) and `deferred-work.md` — DW-17 closed, five entries opened.
- `.bmad-loop/operator/3-5-runner-env-contract.json` — one byte, added by the lint gate's `end-of-file-fixer`; kept, never reverted.

**Review findings.** One pass, two reviewers. 0 intent_gap, 0 bad_spec, **7 patched** (1 medium, 6 low), **5 deferred** (3 medium, 2 low), 5 rejected. The medium patch was a real cross-pass defect: degraded rows were charged a ledger attempt that outlived a pass whose checkpoint did not, so three restarts against an unfixed key would have quarantined three innocent properties while the banner promised they were still candidates. Full breakdown in the Review Triage Log.

**Verification**
- `bash scripts/agent/validate.sh fast` — lint (pre-commit, all files) and eslint **green**; **2041 passed**, 2 failed. Both failures are `test_no_data_destroying_scripts.py::test_volumes_flag_is_refused_not_silently_ignored[stop.sh|clean.sh]`, which shell out to `stop.sh --volumes` and fail on `"docker is not running"` before reaching the refusal they assert. Confirmed independent of this change (the diff touches neither script nor that test) and reproduced on the untouched baseline.
- `bash scripts/agent/validate-ai.sh` — **PASSED** (2 passed) against live Ollama, reached with the documented WSL override `OLLAMA_HOST=http://$(ip route show default | awk '/default/{print $3}'):11434`. The merge-blocking AI domain gate for this change is green.
- `git grep -n "from adapters" src/core/backfill_runner.py` — no matches (AD-1 holds).
- The regression test was confirmed to fail pre-fix for the right reason: with the gate absent it reports *"run_enrichment opened a DB session for a degraded result"*, because the injected session factory raises if it is called at all — which is what makes "nothing persisted, nothing committed" provable rather than argued.
- `bash scripts/agent/validate.sh all` — **not run.** The Docker daemon is down on this host, so the ephemeral test stack cannot start. Not claimed as green.
- `bash scripts/agent/finish-feature.sh` — refused, as designed, on the branch-name prefix (`bmad-loop/<run>/<story>` carries no conventional type). The merge belongs to the bmad-loop orchestrator; this workflow ends at the commit.

**Residual risks**
- The full gate is unverified on this host (integration, contract and e2e stages never ran). Everything this change touches is unit-covered and the AI domain gate is green, but `validate.sh all` remains the merge gate and only the operator can bring Docker up for it.
- The persist gate is in the shared write authority, so the **live** `ai_enrich` path also stops fabricating. That is the intended one-mechanism design, but it is the widest behavioural surface here: a sustained local-backend outage now costs ~6 retry attempts per property where it previously wrote one fabricated score. Deferred to the ledger with its options.
- A fabricated 0.5 is still reachable by a different door — a 200 response whose JSON merely *omits* the score key takes the `data.get("condition_score", 0.5)` default and is **not** marked degraded. Outside this story's intent contract (which is scoped to exception fallbacks) and deferred; the story's named causes (401, 404, DNS/proxy) all raise and are covered.
- Rows poisoned before this fix stay unreachable — `mode_is_missing_ai` is `not score` — and Epic 2 computes percentiles over them. Deferred as the missing half of the Epic 3 → Epic 2 gate.

## Operator Confirmation

Confirmed 2026-08-13: the external actions this story owed were carried out.

- Start Docker Desktop on the Windows host and enable WSL integration for this distro. The daemon is down (`docker.exe info` reports the `dockerDesktopLinuxEngine` pipe missing, and `docker` is not a usable binary in this distro), which is the only reason the full gate could not run.
- With Docker up, re-run `bash scripts/agent/validate.sh all` from this worktree and confirm it is green — this is the one acceptance criterion this run could not verify. Expect the two `test_no_data_destroying_scripts.py::test_volumes_flag_is_refused_not_silently_ignored[stop.sh|clean.sh]` failures to disappear: they shell out to `stop.sh --volumes`, which aborts with "docker is not running" before printing the refusal they assert, and they fail identically on the untouched baseline.
- Let the bmad-loop orchestrator merge this branch. `finish-feature.sh` refuses it ("branch does not have a valid conventional type prefix"), as it does every `bmad-loop/<run>/<story>` branch — do not merge by hand.
- After the merge lands on `main` and is pushed, set `3-2-non-quota-failure-circuit-breaker: done` in `_bmad-output/implementation-artifacts/sprint-status.yaml`.
- Optionally prove the breaker end to end, which no agent can do: point `GEMINI_API_KEY` at a revoked value, run one `scripts/dev/backfill_gemma.py` pass, and confirm it exits 9 with the "AI backend kept returning fabricated results" banner, that no `ai_score` was written for those rows, and that they are still counted as candidates by `--status`.

_Appended by the bmad-loop orchestrator (`bmad-loop confirm`, #335): a human confirmed these external actions out of band, and the story was advanced from `awaiting-operator` to `done`._
