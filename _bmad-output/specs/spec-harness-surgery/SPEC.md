---
id: SPEC-harness-surgery
companions:
  - brownfield.md
  - skill-dispositions.md
  - ../../project-context.md
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Wave 4 Harness Surgery — Primary-Stack-Safe Validation + BMad-Only Harness

## Why

A pain and a mandate combined. **Pain:** the agent validation/finishing scripts recreate the primary Docker Postgres and migrate the primary `realestate` DB (see `brownfield.md`), repeatedly resetting Felipe's only copy of the scraped data — isolation exists at the database level but not the container level. **Mandate:** PRD `prd-imoveis-2026-08-05` §6.2 makes the harness track a gate that completes **before any v0.13 story execution**: CLAUDE.md still mandates the retired feature-pipeline regime and forbids the BMad dev skills that ADR 0005's BMad-SoR + bmad-loop pivot now requires. This spec is the contract for that gate.

## Capabilities

- **CAP-1**
  - **intent:** Operator or agent can run `validate.sh` (`fast`, `backend`, `all`) at any time — including during a live backfill — without the primary stack being touched.
  - **success:** `validate.sh all` completes with zero container create/recreate/restart/stop events on compose project `imoveis`, and a pre/post dump of `realestate` schema + rowcounts is identical.
- **CAP-2**
  - **intent:** Finishing, teardown, and docker cleanup cannot destroy primary state even under environment drift.
  - **success:** Drift-simulation test: teardown invoked with `COMPOSE_PROJECT_NAME` unset, and again set to the primary project, refuses destructive action both times.
- **CAP-3**
  - **intent:** The harness skill surface reduces to BMad + bmad-loop: the 7 non-BMad `.claude/skills/` are deleted with still-needed behavior absorbed.
  - **success:** None of the 7 remain in `.claude/skills/`; every "absorb" row in `skill-dispositions.md` is reachable via its named target.
- **CAP-4**
  - **intent:** CLAUDE.md (project **and** global `~/.claude/`) and the Cursor mirror (`.cursor/rules`, `.cursor/skills`) are rewritten around BMad-SoR + bmad-loop + `scripts/agent` gates, PR-less and CI-less.
  - **success:** No feature-pipeline mandate, no BMad-dev-skill prohibition, no PR/CI/Linear instruction remains in any of the three surfaces; all gates (validate, local finish, docker-cleanup, domain hooks, epic-completion fresh-re-read discipline) are still mandatory; zero references to deleted skills.
- **CAP-5**
  - **intent:** Living guidance docs no longer instruct the retired regime.
  - **success:** `docs/harness-troubleshooting.md`, `development-guide.md`, `deployment-guide.md`, ADR living references, and `source-tree-analysis.md` are consistent with the new regime; legacy `BIN-*` feature docs and `chats_history/` are untouched.
- **CAP-6**
  - **intent:** BMad dev skills are constrained via `_bmad/custom/` overrides so every dev loop calls the `scripts/agent` gates.
  - **success:** Overrides exist for `bmad-dev-story`, `bmad-quick-dev`, `bmad-dev-auto` requiring `validate.sh`, forbidding raw pytest and any compose action against the primary project.
- **CAP-7**
  - **intent:** `project-context.md` is regenerated to reflect the post-surgery regime.
  - **success:** `_bmad-output/project-context.md` replaces its two now-false rules — "validate recreates primary Postgres" and "BMad dev skills must not replace the pipeline" — with the new invariants.
- **CAP-8**
  - **intent:** Ticket delivery completes fully locally — no PR, no remote CI gate: finish gate = `validate.sh all` → local squash-merge to `main` → `git push origin main` → cleanup.
  - **success:** A story ships with zero GitHub PR/checks interaction; `origin/main` equals local `main` after finish; a red `validate.sh all` blocks the merge.
- **CAP-9**
  - **intent:** Still-valuable retired-CI checks are absorbed into the local gates.
  - **success:** `ci.yml` + `sonar-project.properties` removed; `validate.sh` runs pre-commit on **all** files; a CI-only lint violation (e.g. F401 outside `src/`) planted in a scratch file fails `validate.sh` locally.

## Constraints

- Primary compose project `imoveis` is inviolable: no validation/finishing/cleanup path may create, recreate, restart, stop, or down its containers, nor mutate `realestate` schema or data.
- Validation's DB/Redis needs are met by an ephemeral compose project `imoveis-test`: own derived (not hardcoded) ports, throwaway volume, image parity with primary (PostGIS 17-3.5 + pgvector).
- Primary `realestate` migration leaves `validate.sh` entirely and becomes an explicit operator step (mechanism: OQ-1).
- Destructive docker operations fail closed: refuse when compose project identity is ambiguous or resolves to the primary project.
- `scripts/agent/` remains the enforcement layer (ADR 0002): BMad skills call the gates, never reimplement or replace them; domain hooks (`validate-scrapers.sh --require-live`, `validate-ai.sh`, contract tests, `alembic check`) survive unweakened.
- The surgery's own delivery bootstraps on the new `imoveis-test` stack — it never runs the old primary-touching validate path, not even once.
- No named-volume deletion and no `docker system prune --volumes` anywhere in the reworked scripts.
- No gate weakening in the local move: any check that could block a merge pre-surgery (all-files lint, unit, integration, contract, frontend build, domain hooks) must still be able to block a merge locally post-surgery.
- Every local merge to `main` is squash-style and immediately pushed to origin — GitHub stops being a gate but remains the sole backup.

## Non-goals

- Product code (`src/`, `frontend/`) changes beyond what gate wiring requires.
- No replacement CI system (self-hosted runners, `act`, scheduled local cron suites) — the local gates are the only gate.
- Renaming or migrating legacy `BIN-*` feature docs and chat history.
- Wave 3 per-epic verification (separate effort feeding the deferred-work ledger).
- Building or altering bmad-loop internals.
- Pruning the WDS/CIS BMad modules.
- Any change to primary data.

## Success signal

During a live Gemma backfill, a full dev cycle — `validate.sh all`, local squash-merge to `main`, push to origin, teardown, cleanup — runs end-to-end with zero GitHub PR/checks interaction and the primary stack's containers, volumes, and `realestate` data bit-identical before and after; and a fresh agent session reading only the rewritten CLAUDE.md delivers a story exclusively through BMad + bmad-loop + `scripts/agent` gates without encountering a single reference to the 7 deleted skills, Linear, or a PR step.

## Assumptions

- `finish-feature.sh` (or a renamed successor) survives as the local finish gate — validate → squash-merge → push → cleanup — with its PR-creation and CI-watch paths removed. The *skill* feature-pipeline dies, the *script* gate does not.
- Ephemeral project name is `imoveis-test`; ports derived, never hardcoded.
- The surgery is documented under a `v0.13-fu<N>` key per feature-doc convention (PRD treats the harness track as process, not FR; sprint planning has not yet minted keys).
- **Primary migration (ex-OQ-1, confirmed):** a dedicated `scripts/agent/migrate-primary.sh` explicit operator step. Its backfill guard is a runtime check against a **TTL'd heartbeat** the backfill runner refreshes while alive — absent heartbeat ⇒ passes in milliseconds; self-clearing, never manually removed. The guard keys off the live heartbeat, not persistent pacer state (leftover `backfill:gemma` keys after completion must not block).
- `docs.yml` (MkDocs Pages deploy) is kept — publishing, not a gate.

## Resolved (traceability)

- **OQ-1** → Assumptions (migrate-primary.sh with self-clearing heartbeat guard; confirmed). **OQ-2** → dissolved: no PR/CI leaves nothing to babysit; `babysit-pr` deletes with no absorption. **OQ-3** → yes: Cursor mirror + global `~/.claude/CLAUDE.md` in scope; zero Linear references remain anywhere. **OQ-4** → per recommendation: `nightly.yml` keeps only the scraper drift-canary job; `dependabot.yml` stays advisory-only (bumps validated locally); nightly full-suite + dependency-audit deleted. No open questions remain.
