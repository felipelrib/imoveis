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
