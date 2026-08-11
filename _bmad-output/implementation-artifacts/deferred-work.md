# Deferred Work

### DW-1: Follow-up review still recommended for 1-3-backfill-runner-control-core after the damping cap was spent
origin: review-budget-followup
location: n/a
source_spec: `spec-1-3-backfill-runner-control-core.md`
severity: low
reason: The follow-up-review damping cap (limits.max_followup_reviews = 1) was spent with the story finalized (status: done, verify green) while the review pass still recommended an independent follow-up. The work was committed by bmad-loop run 20260806-010958-6ecb; this entry preserves the lingering recommendation for a deliberate later review.
status: open
decision: 2026-08-10 Run one more independent review pass on the 1.3 delta and fix what it confirms — Run an independent adversarial + edge-case review of story 1.3's full delta (baseline 06653689 to final 7bb09136) against src/core/backfill_runner.py, scripts/dev/backfill_gemma.py and the quota path in src/adapters/ai/client.py. Verify every claim against the code before acting on it, and re-reject anything passes 1-3 already rejected for reasons that still hold (the eight rejections are listed in the spec's review section). Fix confirmed findings at patch level only — no spec or intent loopback, no new CLI contracts, no redesign of the injected-clock seam. Skip anything already captured by DW-3, DW-4, DW-6 or DW-7 so this pass does not duplicate scheduled bundles. Finish by clearing `followup_review_recommended` in the spec frontmatter and recording the pass in the story's feature doc.

### DW-2: No vulnerability scanning remains after CI retirement (Trivy fs scan + nightly pip-audit/npm-audit deleted; dependabot advisory-only)
origin: migrated from legacy ledger (flat review-defer append, spec-harness-surgery.md), 2026-08-10
location: scripts/agent/validate.sh (no audit stage; .github/workflows/ci.yml carried the deleted scans)
source_spec: `_bmad-output/implementation-artifacts/spec-harness-surgery.md`
reason: OQ-4 deleted the nightly dependency-audit as "redundant with local gates", but no local gate runs any audit; skill-dispositions assumed "CI security workflow unchanged" while ci.yml (which carried it) was deleted — a spec-internal inconsistency surfaced by review. Nothing in the repo now scans dependencies or the filesystem for known vulnerabilities, and Dependabot is advisory-only (no checks on bot PRs).
status: open
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
