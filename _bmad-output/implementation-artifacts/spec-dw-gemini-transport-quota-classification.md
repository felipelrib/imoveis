---
title: 'Classify a throttle-shaped transport storm as quota, not a row error (DW-7)'
type: 'bugfix'
created: '2026-08-11'
status: 'done'
baseline_revision: 'd885e499640f1b12e41864a9c621641aa1f1e228'
final_revision: 'ab6b7aade99fb298c01a32a2f248bef4bb7da81d'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/project-context.md'
warnings: ['oversized']
---

<intent-contract>

## Intent

**Problem:** `GeminiClient.chat_completions` classifies quota only on the HTTP-status path (`_is_quota_response`, `src/adapters/ai/client.py:979`). The `except (aiohttp.ClientError, asyncio.TimeoutError)` arm at `:996` re-raises the raw transport error untagged, so `is_quota_exhausted` (`src/core/backfill_runner.py:731`) does not match, `_worker` takes the hard-error branch (`:1407`), and the `AttemptLedger.record_attempt` charged before launch stands. A provider throttle that arrives as connection resets or timeouts rather than a 429 therefore burns `backfill.max_attempts` on perfectly good rows inside one throttle window, retiring them unenriched until an operator runs `--reset-quarantine` (DW-7).

**Approach:** Read *repeated identical* transport failure as quota only when the provider has demonstrably just throttled us: raise `AIQuotaExhaustedError` from the transport arm when every attempt of the call failed with the same exception shape **and** an observed 429/quota refusal was recorded within a configurable recency window. Everything else — a mixed failure sequence, a storm with no recent throttle, a single-attempt client — stays a hard error, so a genuine provider outage still counts against the row.

## Boundaries & Constraints

**Always:** the distinguished-error contract stays the only signal `src/core` reads — `AIQuotaExhaustedError.is_quota_exhausted` (AD-1: core never imports adapters), and the raised message keeps a `_QUOTA_MARKERS`-matching phrase so the runner's text net is still a backstop. The recency window is an `AIConfig` field with a `Field(...)` bound, threaded to the client at every construction site — never a magic number in the client body. Recency is measured on a monotonic clock. The inference is auditable: it bumps its own counter, writes a distinguishable `last_error`, and logs a WARNING naming the failure signature and the window, because masking a genuine outage is this change's only real risk. The heuristic is deliberately narrow — when in doubt, hard error.

**Block If:** closing DW-7 would require changing what `AttemptLedger.record_attempt` counts, when the launch loop charges an attempt, or the `run_backfill` quota-vs-error branch itself.

**Never:** do not treat every connection failure as quota. Do not make `rate_limit_hits` count inferred throttles — it means "the provider said 429/quota" and the A/B harness and CLI progress hook report it as observed evidence. Do not touch `_is_quota_response`, `_QUOTA_BODY_MARKERS`, the HTTP retry ladder, `_sleep_backoff`, or `src/core/backfill_runner.py`. Do not add a second quota consumer or change backfill pacing. Do not edit `_bmad-output/implementation-artifacts/deferred-work.md` (the orchestrator records resolution).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Throttle-shaped storm | every attempt raises the same `aiohttp.ClientError`; a 429 was observed inside the window | `AIQuotaExhaustedError`, `is_quota_exhausted` true; inference counter +1; WARNING logged; `rate_limit_hits` unchanged | Runner rolls the attempt back — row not charged |
| Same, as timeouts | every attempt raises `asyncio.TimeoutError`; recent throttle | identical to the row above | Same |
| Genuine outage | every attempt raises the same `ClientError`; no throttle ever observed | the raw transport error propagates unchanged; `last_error` still starts `connection:` | Runner counts a hard error and the attempt stands |
| Stale throttle | identical storm, last observed 429 older than the window | raw transport error (hard error) | Same as outage |
| Mixed failure shapes | attempts raise different messages/types; recent throttle | raw transport error (hard error) | Same as outage |
| Storm after an HTTP retry | attempt 0 gets a retryable 503, later attempts are transport failures; recent throttle | raw transport error — not *every* attempt was a transport failure | Same as outage |
| Single-attempt client | `max_retries=1`, one transport failure, recent throttle | raw transport error — one failure is not "repeated" | Same as outage |
| Window disabled | window configured `0`, identical storm, recent throttle | raw transport error — inference is off | Same as outage |
| Real 429 (unchanged) | provider answers 429 / quota body | unchanged: `rate_limit_hits` +1 and `AIQuotaExhaustedError` from the HTTP path; the hit also stamps the recency clock | Unchanged |

</intent-contract>

## Code Map

- `src/adapters/ai/client.py:996-1004` (`GeminiClient.chat_completions`, transport arm) -- CHANGE: collect a per-call signature (`type(exc).__name__` + truncated message) per transport failure; on the final attempt raise `AIQuotaExhaustedError(...) from exc` when the storm test passes, else the existing bare `raise`.
- `src/adapters/ai/client.py:899-934` (`GeminiClient.__init__` / helpers) -- NEW ctor param `transport_quota_window_seconds` (clamped to `[0, _MAX_TRANSPORT_QUOTA_WINDOW_SECONDS]` with non-finite values resolving to `0`, every correction logged; default mirrors the config default via a class constant), NEW state `last_rate_limit_at: float | None`, `transport_quota_inferences: int`, NEW `_note_rate_limit_hit()` (counter + monotonic stamp, called at both existing `rate_limit_hits += 1` sites `:967` and `:983`), `_clear_rate_limit_recency()` (called on a 200) and `_is_transport_throttle(signatures, *, saw_http_response, first_failure_at)`; NEW class constants `_MIN_TRANSPORT_FAILURES_FOR_QUOTA = 2` and `_MAX_TRANSPORT_QUOTA_WINDOW_SECONDS = 3600.0`. `import time` and `import math` at the module head.
- `src/infra/config.py:245-253` (`AIConfig` gemini cluster) -- NEW `gemini_transport_quota_window_seconds: float = Field(default=300.0, ge=0.0)` with the house-style rationale comment (`0` disables inference).
- `configs/app_config.yaml` (`ai:` block, gemini cluster) -- NEW matching key + comment.
- `src/adapters/ai/client.py:1304` (`create_ai_client`), `scripts/dev/backfill_gemma.py:438` (`_build_client`), `scripts/dev/ab_gemini_vs_ollama.py:491` -- CHANGE: pass `transport_quota_window_seconds=cfg.ai.gemini_transport_quota_window_seconds` alongside `timeout=`.
- `src/tests/unit/test_ai_quota_propagation.py` -- NEW transport-inference section (module conventions: `MagicMock` session + `_ctx`, `AsyncMock` `_sleep_backoff`, `asyncio.run`, `is_quota_exhausted` already imported).
- `src/tests/unit/test_ai_client.py:330-365` (`test_gemini_backend` / `test_gemma_backend`), `src/tests/unit/test_backfill_gemma_cli.py:88` (`_wire`) -- CHANGE: their `MagicMock` cfg must carry a real float for the new field — not because a `MagicMock` raises (`float(MagicMock())` is `1.0`) but because it does not: a missing field silently builds a 1-second window. `test_gemini_backend` and the `_build_client` test both assert the value reached the client, against an expected value that is deliberately not the client's own default.
- `src/tests/unit/test_config.py:507` (`test_ai_stack_from_default_app_config_yaml`) -- CHANGE: assert the new default; NEW bounds test for a negative value (template: `test_backfill_rejects_out_of_range_pacing_values`, `:641`).
- `docs/features/v0.13-fu8-gemini-transport-quota-classification.md` -- NEW feature doc from `docs/features/_template.md` (all sections mandatory).
- `_bmad-output/implementation-artifacts/sprint-status.yaml` -- NEW key `v0.13-fu8-gemini-transport-quota-classification`.

## Tasks & Acceptance

**Execution:**
- [x] `src/tests/unit/test_ai_quota_propagation.py` -- add failing tests for every row of the I/O matrix (both directions: inferred quota, and outage/stale/mixed/post-HTTP-retry/single-attempt/disabled staying hard errors), asserting through `is_quota_exhausted` -- TDD on a classifier branch per the project testing rules
- [x] `src/infra/config.py`, `configs/app_config.yaml`, `src/tests/unit/test_config.py` -- add the bounded `ai.gemini_transport_quota_window_seconds` knob, its YAML entry, the default assertion and the negative-value bounds test -- the window must be config, not a magic number
- [x] `src/adapters/ai/client.py` -- add the recency stamp, the storm test, the tagged raise, the inference counter/log, and the ctor parameter; extend the `chat_completions` docstring with what is and is not read as quota -- the DW-7 fix
- [x] `src/adapters/ai/client.py` (`create_ai_client`), `scripts/dev/backfill_gemma.py`, `scripts/dev/ab_gemini_vs_ollama.py`, `src/tests/unit/test_ai_client.py`, `src/tests/unit/test_backfill_gemma_cli.py` -- thread the config value through all three construction sites and repair the `MagicMock` cfg doubles -- an unwired knob is a decorative one
- [x] `docs/features/v0.13-fu8-gemini-transport-quota-classification.md`, `_bmad-output/implementation-artifacts/sprint-status.yaml` -- feature doc + minted follow-up story key -- harness-required for every completed change

**Acceptance Criteria:**
- Given a `GeminiClient` whose every attempt fails with the same transport exception within the window of an observed 429, when `chat_completions` is called, then it raises an error for which `core.backfill_runner.is_quota_exhausted` is `True`, so `run_backfill` rolls the attempt back instead of charging the ledger.
- Given the same storm with no observed throttle inside the window, when `chat_completions` is called, then the original `aiohttp`/`asyncio` exception propagates unchanged and `is_quota_exhausted` is `False`, so the row still counts as a hard error.
- Given `src/core/backfill_runner.py` and `src/adapters/ai/client.py` after the change, when the diff is inspected, then `backfill_runner.py` is untouched, the adapter's only new cross-layer signal is `AIQuotaExhaustedError`, and the recency window is read from `AIConfig` at every construction site.
- Given an operator inspecting a run that inferred quota from transport, when they read the log and the client counters, then a WARNING names the repeated failure signature and the window, `transport_quota_inferences` is non-zero, and `rate_limit_hits` still counts only provider-stated throttles.

## Spec Change Log

### 2026-08-11 — Sections outside `<intent-contract>` restated to match shipped code

- **Triggering finding:** the follow-up review found the Code Map and the Design Notes sketch still describing the pre-review design — the one-argument `_is_transport_throttle(signatures)` measuring recency as `time.monotonic() - last_rate_limit_at` at call end — which is exactly the behaviour the first review pass replaced. A future session reading this spec as authoritative would have re-derived the known-bad shape.
- **Amended:** the Code Map entry for `GeminiClient.__init__` / helpers (now names `_clear_rate_limit_recency`, the keyword-only `saw_http_response` / `first_failure_at` parameters, the `[0, 3600]` clamp, `_MAX_TRANSPORT_QUOTA_WINDOW_SECONDS` and `import math`) and the Design Notes sketch (now the shipped four-guard form, with a dated note that the earlier sketch was pre-review). No content inside `<intent-contract>` was touched.
- **Known-bad state avoided:** re-deriving a classifier that judges recency at call end (a timeout storm could then never qualify — half of what DW-7 describes) and that lets a failed body read on an answered request masquerade as a dead socket.
- **Recorded deviation from the contract's `Never`:** the contract fences off "the HTTP retry ladder". The two `rate_limit_hits += 1` sites inside it became `_note_rate_limit_hit()` — sanctioned explicitly by the Code Map — and the first review pass additionally added `_clear_rate_limit_recency()` to the ladder's **200 branch**. That third touch is new behaviour on the fenced loop's success path. It is bookkeeping only (no status, retry decision or backoff changed) and it can only move a borderline case toward a hard row error, but it was previously recorded only as a review patch, so the boundary read as respected when it was not. Logged here as the deviation it is.
- **KEEP (must survive any re-derivation):** the four guards and their rationale — `saw_http_response` as the real "no attempt reached the endpoint" test, recency judged at the *first* transport failure, the stamp cleared by a 200, and signatures compared in full with truncation for display only; `rate_limit_hits` counting stated throttles only, with inferences on their own counter; and the narrow-when-in-doubt direction (a missed throttle costs one attempt, a false positive halts a whole pass).

## Review Triage Log

### 2026-08-11 — Review pass (follow-up #2)

- intent_gap: 0
- bad_spec: 0
- patch: 6: (high 0, medium 0, low 6)
- defer: 1: (high 0, medium 0, low 1)
- reject: 16
- addressed_findings:
  - `[low]` `[patch]` The constructor's clamp log said `gemini_transport_quota_window_floored` for all three corrections it now covers, but the previous pass had widened it beyond flooring: an over-wide window is *capped* and `inf`/`NaN` is *resolved to off*. An operator grepping for a disabled window would have matched a client that was silently capped or un-disabled instead — the opposite condition. Renamed to `gemini_transport_quota_window_clamped`, with a comment saying why the name is generic; the four assertions follow.
  - `[low]` `[patch]` `heartbeat.beat()` ran inside the same `try` as the progress log, so a transient Redis failure on the very row that inferred a throttle took the counter down with it — and because an inference stops the pass immediately, no later row re-emits it. That is exactly the signal the previous pass added the tick for. The beat now has its own arm (the lease is renewed by `run_backfill`'s background timer regardless), pinned by a new CLI test that makes `beat()` raise and asserts the tick still fires; mutation-checked against the single-`try` form.
  - `[low]` `[patch]` The feature doc claimed "dropping `len(signatures) == max_retries` fails the post-HTTP-retry test" and that "each of those four review-added guards is isolated by exactly one test". Neither holds: `test_storm_that_followed_a_real_http_response_stays_a_hard_error` puts an HTTP response on attempt 0, so `saw_http_response` short-circuits first and deleting the length guard leaves the suite green. The doc now says the guard is defence-in-depth against a future retry loop and is not independently pinned — a maintainer must not trust a test that does not exist.
  - `[low]` `[patch]` The Approach section attributed the "saw a real HTTP response" exclusion to the signature list having a gap, which is the pre-review reading the `saw_http_response` flag replaced. Corrected to name the flag that actually enforces it.
  - `[low]` `[patch]` Three artifacts describe the recency licence as crossing *concurrent* rows, but the shipped default is `backfill.concurrency: 1`. The substance holds (the licence is per-client, not per-call) but the framing implies parallelism the default run does not have — and DW-15's reachability rests on that distinction. The feature doc now states the default and when rows are genuinely parallel.
  - `[low]` `[patch]` `test_recency_is_judged_at_the_first_failure_not_at_call_end` replaced the client module's entire `time` name with a one-method fake, so the first unrelated `time.time()` added to `client.py` would break it with an `AttributeError` far from the cause. The fake now delegates every other attribute to the real module.
  - `[low]` `[defer]` DW-16 — the inference counter reaches only the structured progress tick; `_terminal_summary`, the `backfill_terminal` event and the quarantine report carry nothing, so the banner an operator reads after an overnight run shows no sign that a throttle was inferred. Not a patch: `_finish` has no access to the client, and because the client is rebuilt per cycle (DW-14) a naively plumbed counter would report the last cycle's inferences as if they were the run's total.
- Rejected: DW-7's ledger entry being closed while the feature doc says the headline shape is still unfixed (the orchestrator owns ledger status and resolution — this run is explicitly forbidden to touch existing entries, and the limitation is already recorded in the doc and in DW-14); `last_rate_limit_at` being read at classification time while `first_failure_at` is snapshotted, and a concurrent 200 clearing the stamp mid-storm (the licence direction is DW-15 verbatim; the revoke direction moves a borderline case to a hard row error, which the design states is the safe side — opening a third entry on one mechanism is the duplication this pass also flagged); deleting the now-redundant `len(signatures) == max_retries` guard (harmless defence-in-depth if the retry loop ever changes — the false *documentation* about it is patched instead); the Spec Change Log's KEEP list enshrining that dead guard (it does not — its four guards are `saw_http_response`, first-failure recency, clear-on-200 and full-signature comparison); `test_config.py`'s lone `from src.adapters.ai.client import GeminiClient` holding a second module object (that file's top-level imports are `src.`-prefixed throughout — `:154` is a single outlier, not the convention — and the assertion compares floats); `transport_quota_inferences` resetting every `--continuous` cycle and `quota_backoff_seconds` not being coupled to the window (both are DW-14); four ledger entries tracing to one root cause (ledger structure is the orchestrator's); the absence of an end-to-end `run_backfill` test composing the real client error with the ledger rollback (rejected with reasons in the previous pass — both links are individually pinned); the ctor clamping numerics but raising on `None`/`str` (rejected in the previous pass); a retried 429 followed by a 500 leaving a live licence (the previous pass rejected clearing on any answered status — only a 200 proves the provider is serving us, and keeping the licence is the conservative reading); the clamp test bundling four behaviours (cosmetic); `sprint-status.yaml` saying `in-progress` while the spec says `in-review` (correct by house rule — a story key goes `done` only after the merge lands, and the orchestrator owns finishing); the request signature leaking an API key if auth ever moved to `?key=` (speculative — auth is a Bearer header and the URL is key-free); and a sub-second window being accepted as "never fires" (overstated — it fires when the first failure is that close to a 429, and it is a valid operator choice).

### 2026-08-11 — Review pass (follow-up)

- intent_gap: 0
- bad_spec: 0
- patch: 7: (high 0, medium 2, low 5)
- defer: 2: (high 0, medium 1, low 1)
- reject: 10
- addressed_findings:
  - `[medium]` `[patch]` The counter the *previous* pass added so an operator could see an inferred throttle still never reached one. `_on_progress` only logs when a 25-row milestone is crossed, and an inferred quota stops the pass immediately — so a pass that infers inside its first 25 rows (where `milestone` is `0` and never exceeds the stored `0`) emitted nothing at all, and neither the per-cycle console line nor `_terminal_summary` carries the field. A new inference is now its own reason to emit the progress tick, pinned by a new CLI test that drives the real `_on_progress` closure (captured through a stubbed `run_backfill`) and fails against the milestone-only condition.
  - `[medium]` `[patch]` The feature doc materially overstated the fix's reach. It admitted only "a backfill *restarted* mid-throttle" starts without a stamp, but `_build_client` runs inside `_run` and `--continuous` calls `_run` per cycle, so the licence is discarded every cycle; and `backfill.quota_backoff_seconds` (900 s) is three times the window (300 s), so no licence can cross a cycle boundary even in principle. The doc now states what sequence actually remains reachable and that the headline DW-7 shape is not one of them (filed as DW-14).
  - `[low]` `[patch]` The ctor floored the low end of the window but not the high end or non-finite values, while `AIConfig` bounds both (`le=3600.0`, `allow_inf_nan=False`). A hand-built client with `inf` therefore licensed the inference indefinitely — the exact failure the config ceiling exists to prevent — and `NaN` passed the `< 0.0` floor untouched and then failed every comparison, disabling the inference invisibly. Both ends are now clamped against a new `_MAX_TRANSPORT_QUOTA_WINDOW_SECONDS`, non-finite resolves to the documented "off" value, and every correction is logged.
  - `[low]` `[patch]` `logger.exception("Error calling Gemini API")` ran *before* the classification, so every inferred throttle emitted an ERROR traceback next to the WARNING reclassifying it — log-based triage saw the storm as precisely the row error this change denies it is. Classification now precedes the log; the hard-error path is unchanged.
  - `[low]` `[patch]` `test_recency_is_judged_at_the_first_failure_not_at_call_end` paired a 0.3 s window with a real `asyncio.sleep(0.5)`, so it needed under 300 ms between the fixture's stamp and the first mocked post — wall-clock racy on a loaded box, failing as a confusing "quota was not inferred", and the only new test costing real time. It now ages the stamp inside the injected backoff instead: deterministic, sleepless, and it still fails if the judgement moves to call end.
  - `[low]` `[patch]` Three comments (two tests + the feature doc's Changes table) claimed "a MagicMock cannot be floored". `float(MagicMock())` is in fact `1.0`, so the real hazard is the opposite of what was documented: a cfg double missing the field builds a silent 1-second window rather than raising. Corrected everywhere.
  - `[low]` `[patch]` Nothing asserted the knob reaching the client through `backfill_gemma._build_client` — the only production construction site per the feature doc's own last bullet. Combined with the `float(MagicMock())` behaviour above, dropping the kwarg there would have left the whole suite green. The existing `_build_client` test now asserts the window; `test_config.py` also pins the client ceiling against the schema bound. Mutation-checking this patch caught a defect in it: `_wire` supplied `300.0`, which is exactly `GeminiClient`'s own default, so the assertion passed with the kwarg deleted. `_wire` now supplies `120.0` and the test asserts the value differs from the default.
  - `[medium]` `[defer]` DW-14 — the recency licence is destroyed at every `--continuous` cycle boundary (client built inside `_run`), and `quota_backoff_seconds` outlasts the window, so across passes the inference is structurally unreachable and the headline DW-7 shape still burns attempts. Narrower and more concrete than DW-13 (a stamp going stale *within* a run). Fixing it means persisting quota state (contract-fenced), hoisting the client above the cycle loop (changes client lifetime for every run), or coupling the two knobs — each a design decision, not a patch.
  - `[low]` `[defer]` DW-15 — `(first_failure_at - last_rate_limit_at) <= window` has no lower bound, so a 429 stamped by a concurrent row *after* this call's first failure licenses the storm however much later it arrives. Found independently by both reviewers. Arguably the desirable reading (a mid-storm refusal is live evidence), but it is not what the YAML comment or the docstring describe and no test covers the negative delta; resolving it changes the heuristic's stated shape.
- Rejected: clearing the stamp on *any* answered status rather than only a 200 (a 5xx does not prove the throttle ended, and keeping the licence is the conservative reading — 200 is the only response that proves the provider is serving us); a 200 whose `.json()` raises still clearing the stamp first (clearing can only move a later case to a hard error, the safe direction); a standalone guard for `NaN` in the ctor (subsumed by the symmetric clamp above, and in isolation it errs safe); a `model_validator` requiring the window to exceed `ai.timeout` (moot — recency is judged at the *first* failure, which is exactly what the previous pass fixed, so a long retry ladder no longer matters); `last_error` being a single slot that a concurrent plain connection failure can overwrite (pre-existing — `last_error` has always been one slot, and the A/B harness's visibility argument is cosmetic); rehoming the knob to `backfill.*` next to `max_attempts`/`quota_backoff_seconds` (it is client classification behaviour, not pacing, and the Code Map specifies `AIConfig`); adding I/O-matrix rows for the four review-added guards (the matrix is inside `<intent-contract>`, which a review pass must not amend — the guards are pinned by tests and recorded here); `test_config.py` importing `src.adapters.ai.client` and so holding a second module object (that file's own convention is `src.`-prefixed throughout and the assertion compares floats, not identities); and `docs/features/BIN-248-gemma-backfill-runner.md` not documenting the new progress field (a legacy doc for a different story; the field is documented in this story's own doc).

### 2026-08-11 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 11: (high 0, medium 6, low 5)
- defer: 2: (high 0, medium 2, low 0)
- reject: 9
- addressed_findings:
  - `[medium]` `[patch]` `except (aiohttp.ClientError, asyncio.TimeoutError)` wraps the body reads too, and `ContentTypeError` / `ClientPayloadError` are `ClientError` subclasses — so a *fully answered* request (an HTML throttle page, a truncated body) landed in the transport arm and left no gap in the signature list, defeating the "no attempt reached the endpoint" invariant the length rule was supposed to enforce. Added an explicit `saw_http_response` flag set inside the `async with`, checked by `_is_transport_throttle`.
  - `[medium]` `[patch]` Recency was judged when the last attempt gave up. Five attempts at `ai.timeout` (120 s) each, plus backoff, outlive the 300 s window, so a *timeout* storm — half of what DW-7 describes — could never qualify however obviously throttled the account. Recency is now judged at the first transport failure of the call.
  - `[medium]` `[patch]` Nothing ever cleared `last_rate_limit_at`. A paced free-tier run collects retried 429s routinely and recovers from them, so every one licensed the inference for a full window afterwards — an unrelated local network drop inside that window would read as quota. A 200 now clears the stamp, tying the licence to a live refusal.
  - `[medium]` `[patch]` `Field(ge=0.0)` accepted `86400` or `inf`: one 429 would then license the inference for the rest of the day, so a dead key or a firewall change would stop producing row errors entirely — the opposite of the visibility the knob exists for. Capped at `le=3600.0` with `allow_inf_nan=False`, plus a parametrized bounds test.
  - `[medium]` `[patch]` `transport_quota_inferences` was written but read by nothing, so the operator's actual signal during a run was a pass backing off "on quota" with `rate_limit_hits` flat — precisely the confusing combination the counter exists to explain. The backfill CLI's progress hook now reports it.
  - `[medium]` `[patch]` The feature doc understated the cost of both accepted errors. On the visual/sentiment stages an untagged storm is swallowed by `analyze_visuals`/`analyze_text` into a persisted fabricated `0.5` (not merely a charged attempt), and a false positive halts the *whole pass* via `budget_exhausted`, which also takes it out of reach of the CLI's `processed == 0` stall detector. Both corrected, with what actually bounds the false positive (the stamp expiry).
  - `[low]` `[patch]` Signatures were truncated to 120 characters *before* comparison, so two `ClientConnectorError`s sharing a long prefix collapsed into one — widening the false-positive surface in the direction the design calls dangerous. Comparison now uses the full message; truncation is display-only (which also makes the previously dead `[:180]` live).
  - `[low]` `[patch]` A negative window was floored silently, disabling a safety feature with no signal. Now logged as `gemini_transport_quota_window_floored`.
  - `[low]` `[patch]` `_DEFAULT_TRANSPORT_QUOTA_WINDOW_SECONDS` claimed to mirror the config default but nothing pinned it, so the two could drift and a hand-built client would behave unlike every configured one. Added an equality test.
  - `[low]` `[patch]` `test_differing_messages_…` and `test_a_negative_window_…` asserted only the raised type, unlike their siblings; both now also assert `transport_quota_inferences == 0`.
  - `[low]` `[patch]` The `chat_completions` docstring and the feature doc described the pre-review conditions. Both restated for the four added guards.
  - `[medium]` `[defer]` DW-12 — the in-call transition shape (attempt 0 gets a 429, stamping the clock; attempts 1..n are identical resets) is declined, because the guard treats "saw an HTTP response" as evidence *against* quota even when that response is the quota refusal itself. Both reviewers found it independently. It is not a deviation: the intent contract specifies "every attempt of the call failed with the same exception shape", and widening it to disqualify only *non-quota* HTTP responses changes the heuristic's shape — the same class of judgement call DW-7 was carved out for. The sustained case, which is what actually quarantines rows, is already caught.
  - `[medium]` `[defer]` DW-13 — while the endpoint answers nothing at all, no 429 can be observed, so the stamp goes stale and a sustained silent throttle charges rows again exactly when it is worst. Refreshing the stamp from a successful inference would fix it but is self-reinforcing (one inference licensing the next indefinitely is precisely how a real outage gets masked), and persisting quota state is fenced off by the contract's "no second consumer of quota state".
- Rejected: `_MIN_TRANSPORT_FAILURES_FOR_QUOTA` being a roundabout spelling of `max_retries >= 2` (true, but the constant names the invariant and the Code Map specifies it); `float(None)` raising from the constructor (no call site passes `None`, and a silent fallback would hide a misconfiguration); stamping the clock on a retryable 5xx that carries a quota body (the terminal path already classifies quota on any status, and the spec's **Never** fences off the retry ladder — it would also widen the licence); the signature embedding volatile detail such as a rotating resolved IP (speculative, and it errs toward a hard error, the safe direction); "identical signatures select for the outage shape a uniform DNS failure produces" (true in isolation — condition (b), a stated refusal inside the window, is what excludes it, and clear-on-success tightens that further); the live Celery path now propagating quota where a storm used to degrade to a template (`create_ai_client`'s cloud branch is unreachable: `AIConfig._validate_backends` rejects a cloud scalar `ai.backend`); the A/B harness's `asyncio.gather` aborting an arm on an inferred error (identical to what an HTTP-path quota refusal has done since v0.13-s1.3, dev-only, and correct for an arm whose provider is refusing it); a `run_backfill`-level test composing the client's real error with the ledger rollback (both links are already locked — the classifier by the new tests, the rollback by `test_run_backfill_quota_error_writes_nothing_and_stops_launching`, and the real class against the real predicate by `test_quota_error_is_recognised_by_the_core_predicate`); and an exact `throttled_ago == window` boundary test (real elapsed time between the stamp and the first failure makes the equality inherently racy — the just-inside case is covered with slack instead).

## Design Notes

**Why "identical" and "every attempt", not "mostly".** The evidence that distinguishes a throttle from an outage is weak by construction — both look like a dead socket. Two independent conditions must hold, and each is deliberately over-strict: (a) *every* attempt of the call failed as a transport error with the same `(type, message)` signature, which excludes the common outage shape of a connect error decaying into a timeout as well as any call that saw a real HTTP response; (b) the provider itself said 429/quota within the window. A mixed sequence during a real throttle is thus misclassified as an outage — accepted, because that failure mode is the status quo (one wasted attempt), while the opposite error masks a real outage across every row of a multi-day run.

**Why ≥2 failures.** With `max_retries=1` "all attempts failed identically" is vacuously true for a single blip. Production builds the client with the default `max_retries=5`, so the floor costs nothing and keeps the word *repeated* honest.

**Recency is cross-task by design.** One long-lived client serves all concurrent backfill rows (`scripts/dev/backfill_gemma.py:639`), so a 429 seen by row A licenses the inference for row B's storm. That is the intended reading: the quota is per-project, not per-call.

**Sketch:**

```python
def _is_transport_throttle(
    self, signatures: list[str], *, saw_http_response: bool, first_failure_at: float
) -> bool:
    if len(signatures) < self._MIN_TRANSPORT_FAILURES_FOR_QUOTA:
        return False
    if saw_http_response:
        return False  # a body read can raise ClientError after a real answer
    if len(signatures) != self.max_retries or len(set(signatures)) != 1:
        return False  # a gap in the ladder, or mixed shapes → not a throttle
    window = self.transport_quota_window_seconds
    if window <= 0.0 or self.last_rate_limit_at is None:
        return False
    # Judged at the FIRST failure: a five-attempt ladder at ai.timeout each can
    # outlive the whole window, so a timeout storm would never qualify if this
    # were measured when the last attempt gave up.
    return (first_failure_at - self.last_rate_limit_at) <= window
```

(Sketch restated after the first review pass, which added the `saw_http_response`
guard, moved recency to the first failure, cleared the stamp on a 200, and made
signature comparison use the full message. The earlier sketch in this section
described the pre-review shape.)

## Verification

**Commands:**
- `bash scripts/agent/validate.sh backend` -- expected: green (pre-commit over all files + unit + integration + contract); each new test must fail with the heuristic removed
- `bash scripts/agent/validate-ai.sh` -- expected: green — the merge-blocking domain gate for an AI-client change
- `bash scripts/agent/validate.sh all` -- expected: green, run by `finish-feature.sh` before the merge (the orchestrator owns finishing)

**Manual checks (operator, against the primary stack — not runnable from an agent worktree):**
- During a live `python scripts/dev/backfill_gemma.py` pass that hits the free-tier ceiling, the log shows `gemini_transport_quota_inferred` (if the throttle surfaces as resets) and the affected properties do **not** appear in `--status`'s quarantine report afterwards.

## Auto Run Result

Status: done. Committed on `bmad-loop/20260810-193244-9de6/dw-gemini-transport-quota-classification`;
**not merged, not pushed** (the bmad-loop orchestrator owns finishing).

**This run was a second follow-up review pass** over an already-`done` spec. The DW-7 classifier
itself is untouched — no condition, threshold or guard changed, and no new behaviour reaches
`src/core`. What this pass fixed is one operator-facing failure mode (a Redis blip could swallow the
only report of an inferred throttle), one misleading log event name, one fragile test seam, and four
documentation claims that were false about the shipped code.

**Change (DW-7), unchanged since the first pass.** `GeminiClient.chat_completions` classifies quota
on the transport arm as well as the HTTP one: when *every* attempt of a call dies with the same
transport signature, *no* attempt reached the endpoint, and the provider stated a 429/quota refusal
within `ai.gemini_transport_quota_window_seconds` of the first failure, it raises
`AIQuotaExhaustedError` instead of re-raising the raw exception, so `run_backfill` rolls the row's
attempt back instead of charging it. `src/core/backfill_runner.py` remains untouched.

**Files changed in this pass**

- `scripts/dev/backfill_gemma.py` — `heartbeat.beat()` moved into its own `try` inside `_on_progress`,
  so a transient Redis failure can no longer suppress the `backfill_progress` tick carrying
  `transport_quota_inferences`. An inference stops the pass immediately, so that tick has exactly one
  chance to fire. The lease itself is renewed by `run_backfill`'s background timer regardless.
- `src/adapters/ai/client.py` — the constructor's clamp log is now
  `gemini_transport_quota_window_clamped` (it covers flooring, ceiling-capping *and* `inf`/`NaN`
  resolution; the old `…_floored` name matched only one of the three).
- `src/tests/unit/test_backfill_gemma_cli.py` — 1 new test: `beat()` raises and the inference tick
  still reaches the log.
- `src/tests/unit/test_ai_quota_propagation.py` — the fake clock delegates every non-`monotonic`
  attribute to the real `time` module, so an unrelated `time.*` call added to `client.py` no longer
  breaks the test with an `AttributeError` far from its cause; the four clamp assertions follow the
  renamed event.
- `docs/features/v0.13-fu8-…md` — four corrections: the false mutation claim about
  `len(signatures) == max_retries` (deleting that guard leaves the suite green — `saw_http_response`
  short-circuits first, so it is defence-in-depth, not a pinned guard); the "saw an HTTP response"
  exclusion attributed to a gap in the signature list rather than to the flag that enforces it; the
  cross-row licence described as crossing *concurrent* rows when the shipped default is
  `backfill.concurrency: 1`; and the test count (18 → 19) plus the new clamp-log wording.
- `_bmad-output/implementation-artifacts/spec-…md` — triage-log entry for this pass. Nothing inside
  `<intent-contract>` was touched.
- `_bmad-output/implementation-artifacts/deferred-work.md` — **appended** DW-16 only. No existing
  entry was read back, reopened or edited.

**Review findings.** 0 intent gaps, 0 spec defects, 6 patches applied (all low), 1 deferral (DW-16),
16 rejected — each with its reason in the Review Triage Log. Both reviewers re-raised several items
the previous passes had already triaged (the composed `run_backfill` test, the ctor's `None`
handling, clearing the stamp on any answered status); those were rejected again on the recorded
grounds rather than re-litigated.

**Verification.** `bash scripts/agent/validate.sh backend` **green** (exit 0): pre-commit over all
files + eslint, **1693 unit**, **90 integration**, **32 contract**, `alembic check` (the PostGIS
system-table output is the gate's known informational case; no schema change in this diff). The
first run failed on pre-commit's fixer hooks (`end-of-file-fixer` on the spec, `isort` on the test
file); the fixes were kept and the gate re-run clean, never skipped. `bash scripts/agent/validate-ai.sh`
**green** (exit 0, Ollama reachable at the WSL default route) — the merge-blocking domain gate for an
AI-client change. `validate.sh all` was **not** run; `finish-feature.sh` runs it before any merge.
The one behavioural patch was mutation-checked: restoring the single-`try` form fails exactly
`test_a_failed_lease_beat_does_not_swallow_the_inference_tick` and nothing else; the source was
restored and re-checked green. The operator check against the live primary stack was **not**
executed — the primary stack is off-limits from an agent worktree.

**Residual risks.** Unchanged from the previous pass, and none were introduced here.

- **DW-14 remains the significant one.** The recency licence is rebuilt from `None` on every
  `--continuous` cycle and `quota_backoff_seconds` (900 s) outlasts the window (300 s), so across
  passes the inference is structurally unreachable — and the headline DW-7 shape (an endpoint silent
  from the start of a pass) never establishes a licence at all and still burns attempts. With DW-12
  and DW-13, the classifier is correct and well pinned but fires far less often than it appears to.
- A genuine outage beginning within the window of a real 429 is still read as quota, still halts the
  whole pass via `budget_exhausted`, and still evades the CLI's `processed == 0` stall detector.
- **DW-16 (new):** the end-of-run banner still carries no sign of an inferred throttle, so an
  operator reading only the terminal summary of an overnight run sees quarantined rows with no
  explanation. The client's WARNING and the progress tick are the durable records until then.
- Every test drives a `MagicMock` session; the *shape* of real `aiohttp` messages under a Google
  throttle is assumed, not observed. If they vary per attempt the identical-signature rule declines
  and the fix silently does nothing.
