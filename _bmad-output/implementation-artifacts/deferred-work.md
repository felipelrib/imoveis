# Deferred Work

### DW-1: Follow-up review still recommended for 1-3-backfill-runner-control-core after the damping cap was spent
origin: review-budget-followup
location: n/a
source_spec: `spec-1-3-backfill-runner-control-core.md`
severity: low
reason: The follow-up-review damping cap (limits.max_followup_reviews = 1) was spent with the story finalized (status: done, verify green) while the review pass still recommended an independent follow-up. The work was committed by bmad-loop run 20260806-010958-6ecb; this entry preserves the lingering recommendation for a deliberate later review.
status: done 2026-08-11
resolution: resolved by sweep bundle dw-decision-dw-1
resolution-undo: b478016663e5e35e61234bfd9c9bc1c85edc67d37a060a9228a0c6e0dadac7e0 2026-08-11 7374617475733a206f70656e
decision: 2026-08-10 Run one more independent review pass on the 1.3 delta and fix what it confirms — Run an independent adversarial + edge-case review of story 1.3's full delta (baseline 06653689 to final 7bb09136) against src/core/backfill_runner.py, scripts/dev/backfill_gemma.py and the quota path in src/adapters/ai/client.py. Verify every claim against the code before acting on it, and re-reject anything passes 1-3 already rejected for reasons that still hold (the eight rejections are listed in the spec's review section). Fix confirmed findings at patch level only — no spec or intent loopback, no new CLI contracts, no redesign of the injected-clock seam. Skip anything already captured by DW-3, DW-4, DW-6 or DW-7 so this pass does not duplicate scheduled bundles. Finish by clearing `followup_review_recommended` in the spec frontmatter and recording the pass in the story's feature doc.

### DW-2: No vulnerability scanning remains after CI retirement (Trivy fs scan + nightly pip-audit/npm-audit deleted; dependabot advisory-only)
origin: migrated from legacy ledger (flat review-defer append, spec-harness-surgery.md), 2026-08-10
location: scripts/agent/validate.sh (no audit stage; .github/workflows/ci.yml carried the deleted scans)
source_spec: `_bmad-output/implementation-artifacts/spec-harness-surgery.md`
reason: OQ-4 deleted the nightly dependency-audit as "redundant with local gates", but no local gate runs any audit; skill-dispositions assumed "CI security workflow unchanged" while ci.yml (which carried it) was deleted — a spec-internal inconsistency surfaced by review. Nothing in the repo now scans dependencies or the filesystem for known vulnerabilities, and Dependabot is advisory-only (no checks on bot PRs).
status: done 2026-08-11
resolution: resolved by sweep bundle dw-decision-dw-2
resolution-undo: 07de55da1004249dce793d8cebf2c9c0c21c6b18ae1f80d3c6827a91ad46b7d3 2026-08-11 7374617475733a206f70656e
decision: 2026-08-10 Advisory local audit: new scripts/agent/audit-deps.sh, wired into validate.sh all as warn-only — Add `scripts/agent/audit-deps.sh` running `pip-audit` against requirements.txt and `npm audit` against frontend/, following the existing scripts/agent/lib.sh conventions (log/ok/die, REPO_ROOT, .venv python). Wire it into `validate.sh all` as a non-blocking stage: it prints findings and a summary count but never fails the gate, and it degrades to a clear skip when the network or the tools are unavailable so an offline merge is still possible. Keep it out of `validate.sh fast` and `validate.sh backend` so the common inner-loop stays fast. Add pip-audit to the dev requirements, and document the stage plus the escalation path (a critical finding is handled by a deliberate bump, not by muting the tool) in docs/ alongside the other gate descriptions.

### DW-3: migrate-primary.sh heartbeat guard is check-then-act — a backfill runner starting between the check and alembic upgrade is not excluded
origin: migrated from legacy ledger (flat review-defer append, spec-harness-surgery.md), 2026-08-10
location: scripts/agent/migrate-primary.sh (heartbeat guard on `backfill:gemma:active`)
source_spec: `_bmad-output/implementation-artifacts/spec-harness-surgery.md`
reason: The guard reads `backfill:gemma:active` once and then runs `alembic upgrade`, so a runner that starts inside that window migrates against a live writer. Closing the race needs a migration-side mutual-exclusion key that the backfill runner honors (src/core/backfill_runner.py change — product code, excluded from the surgery's scope).
status: done 2026-08-11
resolution: resolved by sweep bundle dw-migration-backfill-mutual-exclusion
resolution-undo: 8512a41fd8f3b937d753a466b562e4e2b44c1c0962f4dfe5c41efd475338d489 2026-08-11 7374617475733a206f70656e

### DW-4: A backfill sleeping out its budget window clears the heartbeat, so migrate-primary.sh can migrate the primary DB and still be running when the runner wakes and resumes writing
origin: migrated from legacy ledger (flat review-defer append, spec-1-3-backfill-runner-control-core.md), 2026-08-10
location: scripts/dev/backfill_gemma.py:786 (`_sleep_for_reset`) with scripts/agent/migrate-primary.sh
source_spec: `_bmad-output/implementation-artifacts/spec-1-3-backfill-runner-control-core.md`
reason: `_sleep_for_reset` deliberately keeps the lease alive but the heartbeat was cleared by `_go`'s `finally` — correct while nothing is being written, yet nothing stops the runner resuming mid-migration when the window resets. Story 1.3 added the Redis lease that makes a proper fix cheap (the runner could honor a migration-held key at wake-up), but the paired `migrate-primary.sh` change is outside that story's scope. Same root cause as DW-3; closing both together is the sensible unit of work.
status: done 2026-08-11
resolution: resolved by sweep bundle dw-migration-backfill-mutual-exclusion
resolution-undo: 8512a41fd8f3b937d753a466b562e4e2b44c1c0962f4dfe5c41efd475338d489 2026-08-11 7374617475733a206f70656e

### DW-5: Backfill-mode cloud EMBEDDING breaks read/write vector-space symmetry
origin: migrated from legacy ledger (resolved-note block, spec-1-3-backfill-runner-control-core.md), 2026-08-10
location: src/adapters/ai/client.py (`resolve_enrichment_backend`)
source_spec: `_bmad-output/implementation-artifacts/spec-1-3-backfill-runner-control-core.md`
reason: Cloud routing for the EMBEDDING task class during backfill would have written vectors from a different model than reads use, breaking vector-space symmetry.
status: done 2026-08-06
resolution: Story 1.3 — `resolve_enrichment_backend` degrades EMBEDDING to the local scalar even with `for_backfill=True` and a key present (src/adapters/ai/client.py), locked by src/tests/unit/test_ai_routing.py.

### DW-6: A single property whose enrichment outlives backfill.lease_ttl_seconds can still let the lease lapse under a live run, because renewal is driven by row completions rather than a background timer
origin: migrated from legacy ledger (flat review-defer append, spec-1-3-backfill-runner-control-core.md), 2026-08-10
location: src/core/backfill_runner.py:1094 (`run_backfill` lease renewal)
source_spec: `_bmad-output/implementation-artifacts/spec-1-3-backfill-runner-control-core.md`
reason: `run_backfill` renews once per launch-loop iteration and (after the 1.3 review pass) once per finished row, so the final `gather` drain is covered — but nothing renews *during* a row. A row is ~3 cloud calls plus image downloads, each with client-side 429 retries, so exceeding the 900s default is unlikely yet reachable; the TTL floor was raised to 300s to keep the margin honest. The complete fix is an asyncio background renewer running for the whole `run_backfill` body, which changes the runner's task structure and deserves its own change rather than a review patch.
status: done 2026-08-11
resolution: resolved by sweep bundle dw-backfill-lease-background-renewer
resolution-undo: baddba93aa2ab5e3d643660f120354e4951031daf3cf7bcd0b773a8aead0d603 2026-08-11 7374617475733a206f70656e

### DW-7: A provider throttle that arrives as connection resets or timeouts (rather than an HTTP status) is still charged to the row, so a throttle window can permanently quarantine perfectly good properties
origin: migrated from legacy ledger (flat review-defer append, spec-1-3-backfill-runner-control-core.md), 2026-08-10
location: src/adapters/ai/client.py:979 (`GeminiClient.chat_completions` / `_is_quota_response`)
source_spec: `_bmad-output/implementation-artifacts/spec-1-3-backfill-runner-control-core.md`
reason: Quota is classified only on the HTTP-status path; the `except (aiohttp.ClientError, asyncio.TimeoutError)` arm re-raises the raw transport error untagged, so `is_quota_exhausted` does not match, `run_backfill` counts a hard error and `AttemptLedger.record_attempt` stands. After `max_attempts` cycles inside the same throttle window those rows are retired unenriched and only an operator `--reset-quarantine` brings them back. Pre-existing `AttemptLedger` behaviour from v0.13-fu2/fu3 (story 1.3 only changed the *status*-carrying path), and the fix is a judgement call about when repeated transport failure may be read as quota — treating every connection failure as quota would mask genuine outages; it wants its own change with a deliberate heuristic (e.g. all attempts failing identically while `rate_limit_hits` is recent), not a review patch.
status: done 2026-08-11
resolution: resolved by sweep bundle dw-gemini-transport-quota-classification
resolution-undo: ae9077cc7d7a6df39a743b065776dcacc668214aef712a5ca6bfb689c94c4740 2026-08-11 7374617475733a206f70656e

### DW-8: migrate-primary.sh addresses Redis by hardcoded host/db and literal key names, so any REDIS_URL or redis_prefix change silently disables both halves of the migration↔backfill exclusion
origin: review-defer (bmad-dev-auto follow-up review pass, spec-dw-migration-backfill-mutual-exclusion.md), 2026-08-11
location: scripts/agent/migrate-primary.sh:64-67 (`REDIS_HOST`, `db=0`, `HEARTBEAT_KEY`, `MIGRATE_LOCK_KEY`) vs src/infra/config.py (`redis.url`, `backfill.redis_prefix`)
source_spec: `_bmad-output/implementation-artifacts/spec-dw-migration-backfill-mutual-exclusion.md`
reason: The script talks to `localhost:${REDIS_PORT}` db 0 with the literal keys `backfill:gemma:active` / `backfill:gemma:migrating`; the runner resolves its client from `REDIS_URL` and its keys from `backfill.redis_prefix`. Point `REDIS_URL` at another host or a non-zero db — or change the prefix — and the two write into different keyspaces: neither side ever sees the other's key, both proceed, and every test stays green (the parity test added in v0.13-fu6 pins only the *prefix default*, not the endpoint). Pre-existing for `:active` since the guard was written; the new `:migrating` key inherits it. Fixing it means giving the shell script the same config resolution the runner uses (or having it refuse when the two disagree), which is a change to how agent scripts read app config — deliberately outside the fu6 patch scope.
status: open

### DW-9: The `:active` heartbeat is beaten only per completed row, so a single slow enrichment lets it lapse under a live writer and migrate-primary.sh reads "idle"
origin: review-defer (bmad-dev-auto follow-up review pass, spec-dw-migration-backfill-mutual-exclusion.md), 2026-08-11
location: scripts/dev/backfill_gemma.py (`_on_progress` → `heartbeat.beat()`), src/core/backfill_runner.py (`_worker`'s `finally`)
source_spec: `_bmad-output/implementation-artifacts/spec-dw-migration-backfill-mutual-exclusion.md`
reason: The runner-first half of the v0.13-fu6 exclusion proof assumes `:active` is visible when the script probes it, but the heartbeat has a 300s TTL and is refreshed only when a row *finishes* — nothing ticks it while a row is in flight. One enrichment slower than the TTL (three cloud calls, each with client-side 429 retries) lets `:active` expire under a live writer, so `migrate-primary.sh` sees an idle guard and migrates alongside it. This caps what the fu6 mutual exclusion can guarantee ("no *new* writer starts, provided the runner completed a row within the heartbeat TTL"). Same missing-background-timer root cause as DW-6 but a different key and a different consequence — DW-6 is the lease (two writers), this is the heartbeat (migration exclusion); a background ticker would close both. Not introduced by fu6.
status: open

### DW-10: A Redis outage lasting longer than the lease TTL is swallowed by the background renewer, so a run can keep writing on a lapsed lease while a successor takes the queue
origin: review-defer (bmad-dev-auto follow-up review pass, spec-dw-backfill-lease-background-renewer.md), 2026-08-11
location: src/core/backfill_runner.py (`_renew_lease_periodically`'s `except Exception` arm), src/infra/redis_client.py:26 (client built with no socket timeout)
source_spec: `_bmad-output/implementation-artifacts/spec-dw-backfill-lease-background-renewer.md`
reason: The renewer logs a failing `renew()` and keeps ticking — deliberate, and required by the v0.13-fu7 intent contract ("a Redis blip is logged, never propagated"). But nothing distinguishes a blip from an outage: after `ttl_seconds` of consecutive failures the lease has really expired, a successor can acquire it, and this run neither knows nor stops. The launch loop's own `_lease_held()` raises and ends the run at its next iteration, so the exposure needs the loop to be parked — a long row, a long drain, a TPM wait — which is exactly the window this change exists to cover. Same swallow pre-exists in `_tick_lease`'s `_log_lease_tick_failed`. The fix (track consecutive failure duration and flag `lease_lost` past the TTL) contradicts the fu7 contract's "never propagates, lease_lost is not set", so it needs its own deliberate decision about when repeated failure may be read as loss. A bounded socket timeout on the shared Redis client is the other half and is a multi-surface change.
status: open

### DW-11: After the lease is lost mid-run, still-draining rows advance the shared checkpoint hash, rewinding the successor runner's position and inflating processed_total
origin: review-defer (bmad-dev-auto follow-up review pass, spec-dw-backfill-lease-background-renewer.md), 2026-08-11
location: src/core/backfill_runner.py (`_worker`'s `else` branch → `checkpoint.advance`), `BackfillCheckpoint.advance` (hset `last_property_id` + hincrby `processed_total`)
source_spec: `_bmad-output/implementation-artifacts/spec-dw-backfill-lease-background-renewer.md`
reason: `advance()` is an unconditional `hset` on a key shared by every runner, and in-flight rows always drain (a deliberate constraint — cancelling mid-enrichment leaves half-written properties). So a runner that lost its lease still writes `last_property_id` for each row it finishes; if the successor has already moved past that id, the next resume rewinds to the older one and re-enriches the gap, while `processed_total` counts both runners' work. v0.13-fu7 guarded `_publish` against exactly this class of overwrite but left the checkpoint alone: the same call also records real completed work, so suppressing it loses progress that was genuinely made. Deciding between a monotonic `advance` (compare-and-set on the id's ordering) and a lease-gated one is a checkpoint-semantics change, not a review patch. Pre-existing — the drain-after-loss path is older than the background renewer, which only widened the window by making the loss observable mid-row.
status: open

### DW-12: A throttle that turns silent *mid-call* is still charged, because the 429 that proves it disqualifies the storm it caused
origin: review-defer (bmad-dev-auto review pass, spec-dw-gemini-transport-quota-classification.md), 2026-08-11
location: src/adapters/ai/client.py (`GeminiClient._is_transport_throttle` — the `saw_http_response` / `len(signatures) != self.max_retries` guards)
source_spec: `_bmad-output/implementation-artifacts/spec-dw-gemini-transport-quota-classification.md`
reason: The v0.13-fu8 inference requires that *no* attempt of the call reached the endpoint. So the transition shape — attempt 0 gets a 429 (stamping the recency clock), attempts 1..n are identical connection resets because the provider then went silent — is declined, and the row is charged, even though the strongest possible evidence (a stated refusal *in this very call*) is present. The guard treats "saw an HTTP response" as evidence against quota when the response in question is the quota refusal itself. Both review agents reached this independently. It is not a defect against the fu8 intent contract, which specifies "every attempt of the call failed with the same exception shape"; widening it — track *non-quota* HTTP responses as the disqualifier instead of any HTTP response, so an in-call 429 reinforces rather than vetoes — changes the heuristic's shape and is the same class of judgement call DW-7 itself was carved out for. Bounded today: the sustained case (the provider silent for the whole call) is what actually quarantines rows and is already caught; this costs one attempt per throttle onset.
status: open

### DW-13: Once the provider goes fully silent no new 429 is ever observed, so after the recency window expires a sustained throttle charges every row again
origin: review-defer (bmad-dev-auto review pass, spec-dw-gemini-transport-quota-classification.md), 2026-08-11
location: src/adapters/ai/client.py (`GeminiClient.last_rate_limit_at`, stamped only by `_note_rate_limit_hit`), scripts/dev/backfill_gemma.py (quota back-off cycle → new `run_backfill` pass)
source_spec: `_bmad-output/implementation-artifacts/spec-dw-gemini-transport-quota-classification.md`
reason: The DW-7 inference is licensed only by a throttle the provider *stated*. While the endpoint answers nothing at all, no 429 can be observed, so the stamp goes stale after `ai.gemini_transport_quota_window_seconds` and every later storm is a hard row error again — the DW-7 symptom, returning exactly when the throttle is at its worst. In practice the first inference halts the pass (`budget_exhausted`), the CLI sleeps `backfill.quota_backoff_seconds`, and the resumed pass starts with a stale stamp; if the provider is still silent it charges rows until it answers a 429 again. Refreshing the stamp from a successful *inference* would fix it but is self-reinforcing — one inference would license the next indefinitely, which is precisely how a genuine outage gets masked for a whole run — and persisting quota state across passes is fenced off by the fu8 contract ("do not add a second consumer of quota state"). Needs its own decision about a decaying or bounded self-licence.
status: open

### DW-14: The recency licence is destroyed at every `--continuous` cycle boundary, so across passes the DW-7 inference is structurally unreachable
origin: review-defer (bmad-dev-auto follow-up review pass, spec-dw-gemini-transport-quota-classification.md), 2026-08-11
location: scripts/dev/backfill_gemma.py (`_build_client` called inside `_run`; `_run_continuous` calls `_run` per cycle), configs/app_config.yaml (`backfill.quota_backoff_seconds: 900` vs `ai.gemini_transport_quota_window_seconds: 300`)
source_spec: `_bmad-output/implementation-artifacts/spec-dw-gemini-transport-quota-classification.md`
reason: Narrower and more concrete than DW-13, which describes a stamp going *stale* within a run. Here no stamp survives at all: the client is constructed inside `_run`, and `--continuous` builds a fresh one every cycle, so `last_rate_limit_at` starts `None` on each pass rather than only after an operator restart (the only case the v0.13-fu8 feature doc originally admitted). Compounding it, `quota_backoff_seconds` (900 s) is three times the default window (300 s), so even a persisted stamp would already be stale when the post-back-off pass begins — the two knobs are ordered such that a licence can never cross a cycle boundary. What remains reachable is a single in-pass sequence: a *retried* 429 (a terminal one ends the pass), no subsequent 200 (which clears the stamp), then a full identical storm inside the window. The headline DW-7 shape — the endpoint silent from the start of a pass — yields no 429 at all and still burns `max_attempts` exactly as before. Fixing it means either persisting the stamp across passes (fenced off by the fu8 contract's "no second consumer of quota state"), hoisting the client above the cycle loop (changes client lifetime and connection pooling for every run, not just throttled ones), or coupling `quota_backoff_seconds` to the window. Each is a deliberate design decision, not a review patch.
status: open

### DW-15: The transport-quota recency test is one-sided, so a 429 observed *after* a storm began licenses it regardless of how much later
origin: review-defer (bmad-dev-auto follow-up review pass, spec-dw-gemini-transport-quota-classification.md), 2026-08-11
location: src/adapters/ai/client.py (`GeminiClient._is_transport_throttle`, the `(first_failure_at - self.last_rate_limit_at) <= window` return)
source_spec: `_bmad-output/implementation-artifacts/spec-dw-gemini-transport-quota-classification.md`
reason: The comparison has no lower bound, so an arbitrarily negative difference passes. One long-lived client serves every concurrent backfill row (deliberate — "recency is cross-task by design"), so a 429 stamped by row A *after* row B's first transport failure licenses row B's storm no matter how much later it arrives, bounded only by that call's own duration (~10 min at `max_retries=5` × `ai.timeout=120` plus backoff, i.e. twice the configured 300 s). Both reviewers found it independently. It is arguably the *desirable* reading — a stated refusal arriving mid-storm is live evidence the account is throttled, which is stronger than a stamp from minutes earlier — but it is not what the YAML comment ("the provider actually refused on quota within this many seconds") or the `_is_transport_throttle` docstring ("within `transport_quota_window_seconds` of the first failure") describe, and nothing tests the negative-delta direction. Resolving it means deciding whether the window is symmetric (clamp with `abs()`, narrowing the inference) or deliberately one-sided (say so in the docstring and pin it with a test) — a change to the heuristic's stated shape, which the fu8 contract reserves for its own decision.
status: open

### DW-16: The transport-quota inference reaches only the structured progress log — the end-of-run banner a multi-day operator actually reads carries no sign of it
origin: review-defer (bmad-dev-auto follow-up review pass #2, spec-dw-gemini-transport-quota-classification.md), 2026-08-11
location: scripts/dev/backfill_gemma.py (`_terminal_summary`, `_finish`'s `backfill_terminal` event, `_print_quarantine`) vs `_on_progress`, which is the only surface reporting `transport_quota_inferences`
source_spec: `_bmad-output/implementation-artifacts/spec-dw-gemini-transport-quota-classification.md`
reason: v0.13-fu8 added `transport_quota_inferences` precisely so a pass that backs off "on quota" with `rate_limit_hits` flat explains itself. A previous review pass identified three surfaces missing the counter and patched exactly one — the structured `backfill_progress` tick. The loud terminal banner (`_print_banner` / `_terminal_summary`), the `backfill_terminal` log event and the quarantine report still carry nothing, so the artifact an operator inspects after an overnight or multi-day `--continuous` run shows a healthy-looking pass with quarantined rows and no indication that any throttle was inferred. This is not a patch for two reasons: `_terminal_summary` and `_finish` have no access to the client (it is constructed inside `_run`, below them), so surfacing the counter means threading it up through `_run`'s return path; and because the client is rebuilt per cycle (DW-14), a naively plumbed counter would report only the *final* cycle's inferences in a whole-run banner — a number that reads as a total but is not one. Resolving it properly means accumulating the counter across cycles, which is the same client-lifetime decision DW-14 already frames.
status: open

### DW-17: Every non-quota AI-client failure still persists a fabricated 0.5 score and retires the row from the candidate set
origin: review-defer (bmad-dev-auto follow-up review pass, spec-1-3-backfill-runner-control-core.md), 2026-08-11
location: src/adapters/ai/client.py:639,667,823,858 (`analyze_visuals` / `analyze_text` fallbacks) and :386-405 (`summarize_deal`), with src/adapters/queue/tasks.py:741-764 (`run_enrichment` persists + commits) and src/core/enrichment_rerun.py:91 (`mode_is_missing_ai` is `not score`)
source_spec: `_bmad-output/implementation-artifacts/spec-1-3-backfill-runner-control-core.md`
reason: Story 1.3 closed the fabricated-0.5 corruption for **quota** only: `_reraise_if_quota` re-raises when `exc.is_quota_exhausted` is set and every other exception still returns `VisualResult(condition_score=0.5, analysis="Error")` / `SentimentResult(sentiment_score=0.5, ...)`. `run_enrichment` then computes `a_score = 0.5`, persists it, commits, and `_worker` counts the row processed and advances the checkpoint; because `mode=missing` keys on `not score`, `0.5` is truthy and the property leaves the candidate set permanently. A revoked or expired `GEMINI_API_KEY` (401), a retired model id (404) or a DNS/proxy outage all take that path — none is in `_RETRY_STATUS` or `_QUOTA_BODY_MARKERS` — so an unattended `--continuous` run stamps ~4,600 properties a day with a fake score behind a healthy-looking progress banner. Not a review patch and explicitly fenced by story 1.3's intent contract ("Do NOT change `analyze_visuals`/`analyze_text` fallback behaviour for anything except a quota error — local Ollama failures keep their template fallback"): the local backend depends on that fallback, so closing it needs a deliberate decision about how a systemic-failure signal reaches the runner (a typed marker on the fallback result plus a consecutive-fallback circuit breaker in `run_backfill`, rather than the `analysis == "Error"` string).
status: open

### DW-18: The daily request budget counts properties, not requests, so client-side retries can overshoot the provider's RPD by an order of magnitude
origin: review-defer (bmad-dev-auto follow-up review pass, spec-1-3-backfill-runner-control-core.md), 2026-08-11
location: src/core/backfill_runner.py (`budget.try_consume(requests_per_property)` in the launch loop), src/adapters/ai/client.py:1122-1145 (`request_count += 1` per HTTP attempt) and :490-499 (`_run_json_retry_loop`, 3 attempts), src/infra/config.py:136,150
source_spec: `_bmad-output/implementation-artifacts/spec-1-3-backfill-runner-control-core.md`
reason: `DailyBudget` is charged a flat `requests_per_property` (3) at launch and never reconciled, but one property is 3 stages × up to 3 JSON attempts × up to 5 HTTP retries — up to 45 real requests, and 429s are in `_RETRY_STATUS`, so the overshoot is worst exactly when the account is already throttled. Story 1.3 made the counter atomic (Lua reserve + rollback, locked by `src/tests/integration/test_backfill_lua_scripts.py` under real contention), so AC-1's never-exceed guarantee holds for the counter — the counter is simply measuring the wrong quantity, and the integration test asserts the guarantee against that same quantity. Pre-existing: the flat charge is unchanged from the v0.13-fu2/fu3 runner (`06653689:src/core/backfill_runner.py:655`), so story 1.3 neither introduced nor widened it. The client already tracks `request_count`/`retry_count` and the progress hook already logs them; reconciling the delta after each row (a `settle(n)` on top of the existing Lua) is the cheap fix, but it changes what the budget means and how `--continuous` decides "RPD spent", so it wants its own change.
status: open

### DW-19: `--continuous` never exits when the provider refuses permanently — it alternates two sleep lengths forever with no signal to a supervisor
origin: review-defer (bmad-dev-auto follow-up review pass, spec-1-3-backfill-runner-control-core.md), 2026-08-11
location: scripts/dev/backfill_gemma.py (`_run_continuous`'s `_MAX_QUOTA_BACKOFF_CYCLES` / `throttle_ruled_out` branch, and the stall detector guarded by `if not result.budget_exhausted`)
source_spec: `_bmad-output/implementation-artifacts/spec-1-3-backfill-runner-control-core.md`
reason: A quota refusal sets `budget_exhausted`, which puts the pass permanently out of reach of the zero-progress stall detector. The escalation added by story 1.3's third review pass only *lengthens* the wait (`wait = max(wait, quota_backoff_seconds)`); it never returns a non-zero code. So the one condition an unattended multi-day run most needs surfaced — this account is not going to serve you (billing disabled, key revoked, project deleted, all of which can arrive as `403 RESOURCE_EXHAUSTED` and are classified as quota) — is the only terminal condition that produces no exit at all: 4 back-off cycles, then one zero-progress pass per RPD window indefinitely, holding the lease (every other start refused with exit 5) and re-beating `:active` each pass. Not a patch: choosing when an unattended run may give up, and which code it exits with, is a deliberate policy decision about the CLI's contract — the escalation ladder was itself the last review pass's considered answer.
status: open

### DW-20: The published control state still decays to `idle` during a single in-flight row, because the background lease renewer deliberately never refreshes it
origin: review-defer (bmad-dev-auto follow-up review pass, spec-1-3-backfill-runner-control-core.md), 2026-08-11
location: src/core/backfill_runner.py (`_tick_lease` — driven only from the worker's `finally`; `_renew_lease_periodically` — "It never calls `clock()` or `_refresh_state()`"), `_STATE_TTL_SECONDS = 120` vs `BackfillControl.refresh_interval_seconds` (30s)
source_spec: `_bmad-output/implementation-artifacts/spec-1-3-backfill-runner-control-core.md`
reason: `_tick_lease` exists because "a single row slower than the state TTL let a live run read back as `idle`", but it only runs *after* the row completes, so it cannot cover the window it names; and the DW-6 renewer — the only thing that ticks during an in-flight row — declines to refresh the state on purpose, because the injected clocks the unit tests use are finite sequences a timer would exhaust. With `concurrency: 1` one property is 3 sequential cloud calls at `ai.timeout=120` plus image downloads, so any row past 120s makes `--status` (and story 1.5's admin API) report `idle` for a runner that is alive, holding the lease and mid-write — whose natural operator response is to start a second runner and get exit 5 with a "held by …" message contradicting the `idle` line above it. Story 1.3's own residual-risk note called this the "state-key twin" of DW-6 and expected the background renewer to close both; fu7 closed only the lease half. Same missing-background-ticker root cause as DW-9 (`:active` heartbeat), different key and different consumer. Fixing it means giving the renewer a wall-clock cadence of its own — a change to the injected-clock seam that story 1.3's review passes were explicitly barred from redesigning.
status: open

### DW-21: Nothing renews the lease outside `run_backfill`, so the candidate fetch, the census and the inter-pass window run unrenewed — the exact stretches a migration can block for half an hour
origin: review-defer (bmad-dev-auto follow-up review pass, spec-1-3-backfill-runner-control-core.md), 2026-08-11
location: src/core/backfill_runner.py (the renewer is created inside `run_backfill` and cancelled on exit) vs scripts/dev/backfill_gemma.py (`fetch_candidate_rows` + `partition_candidates` in `_run`, `_census` in `_run_continuous`), configs/app_config.yaml (`migration_wait_seconds: 1800` and `MIGRATE_LOCK_TTL_SECONDS: 1800` vs `lease_ttl_seconds: 900`)
source_spec: `_bmad-output/implementation-artifacts/spec-1-3-backfill-runner-control-core.md`
reason: Every renewal site — the background timer, the launch-loop head, the pause poll, the worker's `finally` — lives inside `run_backfill`. The candidate SELECT over ~26k rows with per-row photo gating, and the post-pass `_census`, run with nobody renewing. `migrate-primary.sh` can take `:migrating` in the gap after `_go`'s `finally` cleared the `:active` heartbeat; the early gate in `_run` is explicitly a check-then-act optimization, so the next pass can pass it a moment before the lock is taken and then block inside Postgres for the whole `ALTER TABLE` — a wait whose two governing timeouts are both **double** the lease TTL. The lease lapses, a successor acquires it, and this process wakes up still believing it owns the run. (The v0.13-fu6 census guard covers only the `migration_blocked` branch; a pass that ended on quota, budget, stall or completion still censuses unguarded.) The fix — hoisting the renewer around the whole `_run_continuous` call, or statement-timeouts on the census — changes the renewer's lifetime and ownership model rather than patching a line.
status: open

### DW-22: The SIGINT/SIGTERM handler performs blocking Redis I/O and can deadlock the process on redis-py's non-reentrant connection-pool lock
origin: review-defer (bmad-dev-auto follow-up review pass, spec-1-3-backfill-runner-control-core.md), 2026-08-11
location: scripts/dev/backfill_gemma.py (`_install_stop_signals`'s `_handler` → `control.request_stop()` → `redis.set`), redis-py 6.4.0 `ConnectionPool.get_connection` (`with self._lock:`)
source_spec: `_bmad-output/implementation-artifacts/spec-1-3-backfill-runner-control-core.md`
reason: Python runs signal handlers on the main thread between bytecodes, and `ConnectionPool.get_connection`/`release` hold a plain `threading.Lock` while checking a connection in or out. A signal landing inside that window makes the handler block on a lock only the interrupted frame can release — a permanent deadlock with the lease still held; the handler's `print()` is not async-signal-safe either. Story 1.3's third review pass rejected this on the grounds that "redis-py checks a *different* pooled connection out for the nested call", which is true of connection *state* but says nothing about the pool lock that guards the checkout itself, so the rejection reason does not fully hold. Bounded in practice: the lock is held for microseconds per call against seconds-long rows, SIGINT recovers on the operator's second Ctrl-C (the handler restores `SIG_DFL` first) and a wedged process is SIGKILLed by any supervisor, after which the lease self-heals on its TTL. Kept out of this pass because the fix is real plumbing — the handler must set only a `threading.Event`, and both sync wait loops **and** `run_backfill`'s `_may_launch` (which reads Redis through the injected control) have to translate that flag into the stop request — not a review patch.
status: open

### DW-23: A pause request self-expires after 7 days and the runner silently resumes spending cloud quota
origin: review-defer (bmad-dev-auto follow-up review pass, spec-1-3-backfill-runner-control-core.md), 2026-08-11
location: src/core/backfill_runner.py (`_CONTROL_REQUEST_TTL_SECONDS = 7 * 24 * 3600`, `BackfillControl.request_pause` sets it with `ex=`, `run_backfill`'s `while control.is_paused()` loop)
source_spec: `_bmad-output/implementation-artifacts/spec-1-3-backfill-runner-control-core.md`
reason: Pause is a *level* with a TTL, and nothing refreshes it — not the CLI, not the paused loop that is holding the lease and polling the key. An operator who pauses a `--continuous` run for maintenance, a stalled migration or a holiday longer than the TTL gets a run that resumes launching quota-spending rows with no log line, no acknowledgement and no re-request, against a system they believe is held. Resolving it means deciding who owns the request key once it has been observed — refreshing it from the paused loop makes the runner a writer of operator requests, and treating expiry as a stop changes what `--status` reports — so it is a control-semantics decision rather than a review patch.
status: open

### DW-24: DW-2 restored dependency scanning only — the deleted Trivy filesystem/base-image scan has no replacement, and `.trivyignore` is now an accepted-risk register no scanner reads
origin: review-defer (bmad-dev-auto follow-up review pass, spec-dw-decision-dw-2.md), 2026-08-11
location: scripts/agent/audit-deps.sh (manifest scanning only), .trivyignore (orphaned), docs/harness-troubleshooting.md § Dependency audit (scope caveat)
source_spec: `_bmad-output/implementation-artifacts/spec-dw-decision-dw-2.md`
reason: DW-2's problem statement names the deleted Trivy *filesystem* scan as well as the nightly dependency audits, but the human-chosen option ("advisory local audit: pip-audit + npm audit") only restores dependency-manifest scanning. Container and OS-package CVEs in the API image remain unscanned by anything in the repo. Compounding it, `.trivyignore` survives as the only written record of an accepted risk (CVE-2024-23342 / ecdsa) and `audit-deps.sh` cannot consult it — so that advisory is reported as a finding on every single run, with suppression explicitly forbidden by the chosen design, leaving the summary permanently amber and a genuinely new critical indistinguishable from standing noise. Deciding between a restored image scan, a baseline/ratchet artifact, and a sanctioned accepted-risk mechanism is a scope decision, not a review patch.
status: open

### DW-25: The dependency audit's first run found real fixable advisories — including a high-severity direct runtime dependency — and no bump story exists for them
origin: review-defer (bmad-dev-auto follow-up review pass, spec-dw-decision-dw-2.md), 2026-08-11
location: frontend/package.json (`react-router-dom`), requirements.in / requirements.txt (`cryptography`)
source_spec: `_bmad-output/implementation-artifacts/spec-dw-decision-dw-2.md`
reason: The detector shipped; the vulnerabilities it found did not get a work item. `npm audit --json` reports `react-router-dom` as high severity with `isDirect: true` and a fix available — a direct runtime dependency that ships in the browser bundle — and `pip-audit` reports `cryptography 49.0.0` / PYSEC-2026-3552 with fix 50.0.0 published. The spec's own boundary ("no dependency bumps here") correctly kept them out of that change, and the feature doc records them as a `BUG (Medium)` bullet, but a doc bullet is not tracked work: `grep -i "bump\|cryptography\|react-router" sprint-status.yaml` returns nothing. Each bump needs its own validation (a `react-router-dom` major touches routing behaviour and the E2E suite), so this is a bump story, not a review patch.
status: open

### DW-26: Follow-up review still recommended for dw-decision-dw-2 after the damping cap was spent
origin: review-budget-followup
location: n/a
source_spec: `spec-dw-decision-dw-2.md`
severity: low
reason: The follow-up-review damping cap (limits.max_followup_reviews = 1) was spent with the story finalized (status: done, verify green) while the review pass still recommended an independent follow-up. The work was committed by bmad-loop run 20260810-193244-9de6; this entry preserves the lingering recommendation for a deliberate later review.
status: open

### DW-27: FR-28's "graduates from scripts/dev" is unmet at the consumer — the dashboard's Start button works only while a hand-started dev script stays alive
origin: review-defer (bmad-dev-auto review pass, spec-1-5-admin-backfill-control-api.md), 2026-08-11
location: scripts/dev/backfill_gemma.py (`--serve`), docs/features/v0.13-s1.5-admin-backfill-control-api.md (operating instructions)
source_spec: `_bmad-output/implementation-artifacts/spec-1-5-admin-backfill-control-api.md`
reason: Story 1.5 ships the control plane FR-28 asked for, but the thing that executes a requested run is still `scripts/dev/backfill_gemma.py`, now required to run *continuously* rather than on demand: `POST /admin/backfill/start` only records a request, and nothing consumes it unless a `--serve` supervisor is alive on the host. The story hardened that consumer as far as review patches go (it survives failing runs, validates its backend before claiming readiness, clears its heartbeat on SIGTERM, and the API reports `runner_present: false` honestly), and the feature doc now carries an example systemd unit with `Restart=always` — but installing and supervising it is an operator act, no unit is committed or wired into the stack, and a supervisor that is simply never started leaves a permanently un-actionable button. Deciding where the runner should actually live (a committed systemd unit, a dedicated compose service with the cloud key, or promoting the runner out of `scripts/dev` into a supported entrypoint) is a topology decision — cloud key placement and the residential-IP/local-first invariants are in play — not a review patch.
status: resolved
resolution: Story 3.1 (`v0.13-s3.1`) commits the home — `deploy/systemd/imoveis-backfill-serve.service.in` + `scripts/install-backfill-runner.sh` (render/preflight/install/uninstall/status) — and records the topology choice, the cloud-key placement and the rejected compose-service / promote-to-`src` alternatives in ADR 0006; the runner stays host-side and unchanged.

### DW-28: An API-requested run reports no outcome — once the request is consumed, a refusal or crash is visible only on the host's stderr
origin: review-defer (bmad-dev-auto follow-up review pass, spec-1-5-admin-backfill-control-api.md), 2026-08-11
location: scripts/dev/backfill_gemma.py (`_serve` / `_run_supervised`), src/api/admin.py (`GET /admin/backfill/status`), src/api/schemas.py (`BackfillStatusResponse`)
source_spec: `_bmad-output/implementation-artifacts/spec-1-5-admin-backfill-control-api.md`
reason: `consume_start()` is destructive, so the moment the supervisor takes a request `start_requested_at` goes null. If the run it launched is then refused or dies (budget exhausted, a rotated cloud key, a lost lease race, an unexpected exception), `_run_supervised` prints and logs it host-side and the loop goes back to waiting — but nothing the API can read records that it happened. Story 1.6 therefore sees: request accepted (202) → request vanishes → `active` never becomes true → no error anywhere, which is the "button that silently does nothing" shape one indirection removed from DW-27. This follow-up pass closed the cases where the request would be *burned* (a held lease and a live primary migration now defer instead of consuming, and an expired deferred request is announced), so what remains is the genuinely-attempted-and-failed case. The fix is a new published surface — a `<prefix>:last_run` key carrying exit code, timestamp and reason, written by the supervisor and surfaced as a status field — which adds wire contract beyond this story's frozen I/O matrix and needs to be designed together with story 1.6's rendering of it.
status: open

### DW-29: The admin audit trail records what happened but never who did it
origin: review-defer (bmad-dev-auto follow-up review pass, spec-1-5-admin-backfill-control-api.md), 2026-08-11
location: src/api/admin.py (`log_audit_action`), adapters/db/models.py (`AdminAudit`)
source_spec: `_bmad-output/implementation-artifacts/spec-1-5-admin-backfill-control-api.md`
reason: `log_audit_action(action, payload)` takes no actor: no API-key identity, no source IP, no principal of any kind, and `AdminAudit` has no column for one. Story 1.5's payloads (`backfill_start`, `backfill_start_refused`, `backfill_pause`, `backfill_resume`) inherit that gap and hardcode `source="admin-api"`, so for a surface whose stated justification is AD-6 auditing of a multi-day cloud spend, the trail cannot answer "who started this run" — it answers only "something behind the admin key did". Pre-existing and shared by every admin mutation in the file (GPU scaling, scoring weights, worker pause), so fixing it is a change to the audit helper, its schema (a migration, nullable `actor` per the single-user convention) and every call site — not a story-1.5 patch. Related: the existing `BUG (Low)` note that the helper swallows its own failure, so a mutation can be applied with no audit row at all.
status: open

- source_spec: `_bmad-output/implementation-artifacts/spec-1-6-operacoes-backfill-card-coverage-visibility.md`
  summary: The backfill candidate count double-counts a property that carries several unscored `metrics_scoring` rows, in the coverage endpoint AND in the runner's own census.
  evidence: `_CANDIDATES_SUBQUERY` LEFT JOINs `metrics_scoring` without DISTINCT, so a property with two unscored metrics rows contributes twice to `remaining` (and to the runner's queue view). The expression is identical in `src/adapters/db/enrichment_coverage_queries.py` and `scripts/dev/backfill_gemma.py::_census`, and story 1.6 added a drift-lock test pinning them together — so the fix must change both at once, which is outside a review patch.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-6-operacoes-backfill-card-coverage-visibility.md`
  summary: The coverage endpoint's `remaining` never subtracts quarantined candidates, so a run whose tail is permanently failing shows an ETA that cannot converge.
  evidence: `scripts/dev/backfill_gemma.py::_census` subtracts `_count_quarantined_candidates`, and `BackfillStatusResponse` already carries a `quarantined` field the new endpoint leaves null. The count comes from the Redis attempt ledger, whose scan is O(rows ever attempted) — story 1.5 deliberately kept it off polled routes — so honouring it needs a cheap published counter, not a per-request scan. Same shape as the v0.13-fu3 dead-completion-branch bug, one layer up.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-6-operacoes-backfill-card-coverage-visibility.md`
  summary: A Redis outage 500s `GET /admin/enrichment/coverage` even though every figure it serves is DB-derived.
  evidence: The route reads the backfill lease for the `active` bit and for the throughput-window clamp inside the same guarded block as the queries, so an unrelated Redis blip blanks the whole coverage card and both Painel chips. Degrading to "liveness unknown" (null `active`, unclamped window) instead of failing is a deliberate wire-contract choice — `active` would need to become nullable — rather than a patch.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-6-operacoes-backfill-card-coverage-visibility.md`
  summary: The shared ToastProvider is anchored top-right while DESIGN.md's toast spec is bottom-anchored, max two stacked.
  evidence: Story 1.6's lease-conflict toast is specified by UX-DR5 to use that spec, but `frontend/src/components/ToastProvider.tsx` is a surface every page inherits; re-anchoring it restyles unrelated flows and needs its own e2e sweep.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-6-operacoes-backfill-card-coverage-visibility.md`
  summary: The Operações nav label and the page heading disagree — nav reads "Operações", the `<h1>` still reads "Controle de Scrapers".
  evidence: UX-DR2 renames the admin surface to Operações; story 1.6 changed `nav.scraper` only, leaving the `scraper.*` catalog namespace, the `/scraper` route and the page title as they were. Aligning them touches copy, route and the specs asserting the old heading.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-6-operacoes-backfill-card-coverage-visibility.md`
  summary: The lease-conflict toast splices English server prose into the pt-BR card, and the remedy that prose recommends is CLI-only advice the card itself contradicts.
  evidence: `_start_refusal_detail` in `src/api/admin.py` returns full English sentences ("A backfill run already holds the lease (…). Pause it, or stop it from the host CLI (scripts/dev/backfill_gemma.py --stop), before starting another."), and `BackfillCard` interpolates that `detail` verbatim into `operations.toastStartConflict`. Fixing it properly means adding a machine-readable `owner` to story 1.5's 409 body so the UI can build the sentence from its own catalogs — a wire-contract change to a route this story's intent contract puts out of scope, not a copy edit.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-6-operacoes-backfill-card-coverage-visibility.md`
  summary: `projected_completion_date` is computed from the UTC date, so between 21:00 and 24:00 America/Sao_Paulo it names a day later than the operator's own.
  evidence: The route passes `today=datetime.now(timezone.utc).date()` into `build_coverage_report`, and `_projected_completion` adds whole days to it; for the last three hours of every local day the UTC date has already rolled over. No consumer renders the field yet (the card shows `eta_days` only), so nothing is visibly wrong today. The honest fix is a first-class operator timezone in `AppConfig` — the only `timezone` key in the config belongs to `CeleryConfig`, and borrowing the beat scheduler's setting for an operator-facing projection is the kind of coupling that outlives the reason for it.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-6-operacoes-backfill-card-coverage-visibility.md`
  summary: The remaining-candidate query casts `image_urls` to `jsonb`, which raises on a NUL unicode escape and would 500 the whole coverage route -- the exact hazard the same module's signal predicates deliberately avoid a cast to dodge.
  evidence: `_CANDIDATES_SUBQUERY` in `src/adapters/db/enrichment_coverage_queries.py` runs `p.image_urls::jsonb` (the column is SQLAlchemy `JSON`, i.e. Postgres `json`), and Postgres rejects a `\u0000` escape on conversion to `jsonb`. Two comment blocks above, the `meta` predicates document that exact reasoning as the reason they stay on `json`. The cast is deliberate mirroring of the runner's own predicate and is drift-locked to it by `test_coverage_sql_drift.py`, so diverging here alone would break the lock and stop the count matching the runner's queue -- the fix has to change both and re-derive the lock.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-6-operacoes-backfill-card-coverage-visibility.md`
  summary: Pre-existing pt-BR plural-agreement defects became every user's default when this story flipped the locale, and its e2e repairs pinned them as expected strings.
  evidence: `pt-BR.json` carries single-form keys where the catalog elsewhere models the split (`modal.listingCountOne`/`listingCountMany`): `compareSelected` renders "1 selecionados", and `properties.countProperties` / `properties.countFavourited` / `common.bedsShort` render "1 imóveis" / "1 favoritos" / "1 quartos". Review pass 1 fixed exactly this class for the story's own new keys (`etaOneDay`, `throughputOne`). The strings pre-date this story, but the locale flip promoted them from an opt-in preference to the default, and `compare-select.spec.js`, `compare-map-select.spec.js` and `compare-view.spec.js` now assert "1 selecionados" verbatim -- so the fix is a catalog sweep plus the specs that lock it, not a single-key patch.

### DW-30: Follow-up review still recommended for 1-6-operacoes-backfill-card-coverage-visibility after the damping cap was spent
origin: review-budget-followup
location: n/a
source_spec: `spec-1-6-operacoes-backfill-card-coverage-visibility.md`
severity: low
reason: The follow-up-review damping cap (limits.max_followup_reviews = 1) was spent with the story finalized (status: done, verify green) while the review pass still recommended an independent follow-up. The work was committed by bmad-loop run 20260806-010958-6ecb; this entry preserves the lingering recommendation for a deliberate later review.
status: open

- source_spec: `_bmad-output/implementation-artifacts/spec-3-1-backfill-runner-hosting.md`
  summary: A misconfigured supervisor crash-loops every 10s forever with no backoff and nothing that surfaces it to the operator — the honest-but-silent successor to DW-27's un-actionable button.
  evidence: The committed unit pairs `Restart=always` + `RestartSec=10` with `StartLimitIntervalSec=0`, deliberately, so a restart limit can never park the unit in `failed` (which would silently disarm the Start button again). The cost is that an all-local `ai.enrichment_routing`, a revoked key or a wrong `DATABASE_URL` makes `--serve` exit before its poll loop and restart every 10s indefinitely, spamming journald, while `runner_present` stays honestly false and no product surface says why. The installer's post-restart liveness check catches it at install time only; a later config edit re-opens it. Closing it properly needs either systemd `RestartSteps`/`RestartMaxDelaySec` backoff (systemd ≥254) or a published last-run/last-error surface — which is exactly DW-28's `<prefix>:last_run` key and should be designed with it, not bolted onto the unit.

- source_spec: `_bmad-output/implementation-artifacts/spec-3-1-backfill-runner-hosting.md`
  summary: Nothing detects that an *installed* unit has drifted from the committed template or the current config — the rendered values are frozen at install time.
  evidence: `TimeoutStopSec` is derived from `backfill.lease_ttl_seconds` and the paths from the checkout location, both at render time. Raising the lease TTL, moving the repo or rebuilding `.venv` leaves `/etc/systemd/system/imoveis-backfill-serve.service` stale until someone remembers to re-run the installer; the unit tests only ever inspect freshly rendered output, so drift is invisible to the gate too. A `--check` that diffs the installed unit against a fresh render (and warns) would close it, but it needs a decision about whether a drifted unit is a warning or a failure — and reading `/etc` in a unit test needs care.
