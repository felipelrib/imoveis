- source_spec: `_bmad-output/implementation-artifacts/spec-harness-surgery.md`
  summary: No vulnerability scanning remains after CI retirement (Trivy fs scan + nightly pip-audit/npm-audit deleted; dependabot advisory-only).
  evidence: OQ-4 deleted the nightly dependency-audit as "redundant with local gates", but no local gate runs any audit; skill-dispositions assumed "CI security workflow unchanged" while ci.yml (which carried it) was deleted — a spec-internal inconsistency surfaced by review.
- source_spec: `_bmad-output/implementation-artifacts/spec-harness-surgery.md`
  summary: migrate-primary.sh heartbeat guard is check-then-act — a backfill runner starting between the check and alembic upgrade is not excluded.
  evidence: Guard reads `backfill:gemma:active` once; closing the race needs a migration-side mutual-exclusion key the backfill runner honors (src/core/backfill_runner.py change — product code, excluded from the surgery's scope).
