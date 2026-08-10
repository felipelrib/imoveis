- source_spec: `_bmad-output/implementation-artifacts/spec-harness-surgery.md`
  summary: No vulnerability scanning remains after CI retirement (Trivy fs scan + nightly pip-audit/npm-audit deleted; dependabot advisory-only).
  evidence: OQ-4 deleted the nightly dependency-audit as "redundant with local gates", but no local gate runs any audit; skill-dispositions assumed "CI security workflow unchanged" while ci.yml (which carried it) was deleted — a spec-internal inconsistency surfaced by review.
- source_spec: `_bmad-output/implementation-artifacts/spec-harness-surgery.md`
  summary: migrate-primary.sh heartbeat guard is check-then-act — a backfill runner starting between the check and alembic upgrade is not excluded.
  evidence: Guard reads `backfill:gemma:active` once; closing the race needs a migration-side mutual-exclusion key the backfill runner honors (src/core/backfill_runner.py change — product code, excluded from the surgery's scope).
- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-backfill-runner-control-core.md`
  summary: A backfill sleeping out its budget window clears the heartbeat, so `migrate-primary.sh` can migrate the primary DB and still be running when the runner wakes and resumes writing.
  evidence: `_sleep_for_reset` (scripts/dev/backfill_gemma.py) deliberately keeps the lease alive but the heartbeat was cleared by `_go`'s `finally`, which is correct while nothing is being written — but nothing stops the runner resuming mid-migration when the window resets. Story 1.3 added the Redis lease that makes a proper fix cheap (the runner could honor a migration-held key at wake-up), but the paired `migrate-primary.sh` change is outside this story's scope. Same root cause as the check-then-act entry above; closing both together is the sensible unit of work.

# RESOLVED 2026-08-06 by story 1.3 (spec-1-3-backfill-runner-control-core):
# "Backfill-mode cloud EMBEDDING breaks read/write vector-space symmetry" —
# `resolve_enrichment_backend` now degrades EMBEDDING to the local scalar even
# with `for_backfill=True` and a key present (src/adapters/ai/client.py), locked
# by src/tests/unit/test_ai_routing.py.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-backfill-runner-control-core.md`
  summary: A single property whose enrichment outlives `backfill.lease_ttl_seconds` can still let the lease lapse under a live run, because renewal is driven by row completions rather than a background timer.
  evidence: `run_backfill` renews once per launch-loop iteration and (after this review pass) once per finished row, so the final `gather` drain is now covered — but nothing renews *during* a row. A row is ~3 cloud calls plus image downloads, each with client-side 429 retries, so exceeding the 900s default is unlikely yet reachable; the TTL floor was raised to 300s to keep the margin honest. The complete fix is an asyncio background renewer running for the whole `run_backfill` body, which changes the runner's task structure and deserves its own change rather than a review patch.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-backfill-runner-control-core.md`
  summary: A provider throttle that arrives as connection resets or timeouts (rather than an HTTP status) is still charged to the row, so a throttle window can permanently quarantine perfectly good properties.
  evidence: `GeminiClient.chat_completions` classifies quota only on the HTTP-status path (`_is_quota_response`); the `except (aiohttp.ClientError, asyncio.TimeoutError)` arm re-raises the raw transport error untagged, so `is_quota_exhausted` does not match, `run_backfill` counts a hard error and `AttemptLedger.record_attempt` stands. After `max_attempts` cycles inside the same throttle window those rows are retired unenriched and only an operator `--reset-quarantine` brings them back. Pre-existing `AttemptLedger` behaviour from v0.13-fu2/fu3 (this story only changed the *status*-carrying path), and the fix is a judgement call about when repeated transport failure may be read as quota — treating every connection failure as quota would mask genuine outages. Wants its own change with a deliberate heuristic (e.g. all attempts failing identically while `rate_limit_hits` is recent), not a review patch.

### DW-1: Follow-up review still recommended for 1-3-backfill-runner-control-core after the damping cap was spent
origin: review-budget-followup
location: n/a
source_spec: `spec-1-3-backfill-runner-control-core.md`
severity: low
reason: The follow-up-review damping cap (limits.max_followup_reviews = 1) was spent with the story finalized (status: done, verify green) while the review pass still recommended an independent follow-up. The work was committed by bmad-loop run 20260806-010958-6ecb; this entry preserves the lingering recommendation for a deliberate later review.
status: open
