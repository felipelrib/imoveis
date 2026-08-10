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
status: open

### DW-4: A backfill sleeping out its budget window clears the heartbeat, so migrate-primary.sh can migrate the primary DB and still be running when the runner wakes and resumes writing
origin: migrated from legacy ledger (flat review-defer append, spec-1-3-backfill-runner-control-core.md), 2026-08-10
location: scripts/dev/backfill_gemma.py:786 (`_sleep_for_reset`) with scripts/agent/migrate-primary.sh
source_spec: `_bmad-output/implementation-artifacts/spec-1-3-backfill-runner-control-core.md`
reason: `_sleep_for_reset` deliberately keeps the lease alive but the heartbeat was cleared by `_go`'s `finally` — correct while nothing is being written, yet nothing stops the runner resuming mid-migration when the window resets. Story 1.3 added the Redis lease that makes a proper fix cheap (the runner could honor a migration-held key at wake-up), but the paired `migrate-primary.sh` change is outside that story's scope. Same root cause as DW-3; closing both together is the sensible unit of work.
status: open

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
status: open

### DW-7: A provider throttle that arrives as connection resets or timeouts (rather than an HTTP status) is still charged to the row, so a throttle window can permanently quarantine perfectly good properties
origin: migrated from legacy ledger (flat review-defer append, spec-1-3-backfill-runner-control-core.md), 2026-08-10
location: src/adapters/ai/client.py:979 (`GeminiClient.chat_completions` / `_is_quota_response`)
source_spec: `_bmad-output/implementation-artifacts/spec-1-3-backfill-runner-control-core.md`
reason: Quota is classified only on the HTTP-status path; the `except (aiohttp.ClientError, asyncio.TimeoutError)` arm re-raises the raw transport error untagged, so `is_quota_exhausted` does not match, `run_backfill` counts a hard error and `AttemptLedger.record_attempt` stands. After `max_attempts` cycles inside the same throttle window those rows are retired unenriched and only an operator `--reset-quarantine` brings them back. Pre-existing `AttemptLedger` behaviour from v0.13-fu2/fu3 (story 1.3 only changed the *status*-carrying path), and the fix is a judgement call about when repeated transport failure may be read as quota — treating every connection failure as quota would mask genuine outages; it wants its own change with a deliberate heuristic (e.g. all attempts failing identically while `rate_limit_hits` is recent), not a review patch.
status: open
