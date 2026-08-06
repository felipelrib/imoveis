- source_spec: `_bmad-output/implementation-artifacts/spec-harness-surgery.md`
  summary: No vulnerability scanning remains after CI retirement (Trivy fs scan + nightly pip-audit/npm-audit deleted; dependabot advisory-only).
  evidence: OQ-4 deleted the nightly dependency-audit as "redundant with local gates", but no local gate runs any audit; skill-dispositions assumed "CI security workflow unchanged" while ci.yml (which carried it) was deleted — a spec-internal inconsistency surfaced by review.
- source_spec: `_bmad-output/implementation-artifacts/spec-harness-surgery.md`
  summary: migrate-primary.sh heartbeat guard is check-then-act — a backfill runner starting between the check and alembic upgrade is not excluded.
  evidence: Guard reads `backfill:gemma:active` once; closing the race needs a migration-side mutual-exclusion key the backfill runner honors (src/core/backfill_runner.py change — product code, excluded from the surgery's scope).
- source_spec: `_bmad-output/implementation-artifacts/spec-1-2-live-pipeline-routes-by-task-class-local-fallback.md`
  summary: Backfill-mode cloud EMBEDDING breaks read/write vector-space symmetry — story 1.3 must exclude EMBEDDING from cloud honor (or re-embed coherently).
  evidence: Follow-up code review 2026-08-06 — `resolve_enrichment_backend(…, for_backfill=True)` (src/adapters/ai/client.py:1027) has no task-class restriction: `enrichment_routing.embedding: gemma` + key present would let the story-1.3 runner store cloud-space vectors while the query side (`src/api/properties.py::_get_embedding_client`) always degrades to local — dimension mismatch or silently corrupted semantic-search similarity, the exact failure the s1.2 read/write-symmetry fix prevents for the live path. Dead branch until 1.3 wires the runner.
