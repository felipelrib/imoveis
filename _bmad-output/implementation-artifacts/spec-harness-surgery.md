---
title: 'Wave 4 Harness Surgery — primary-safe validation + BMad-only, PR-less harness'
type: 'chore'
created: '2026-08-05'
status: 'done'
review_loop_iteration: 0
baseline_commit: '8265353789279e4466cb1c51e8699b2745d4cde9'
context:
  - '{project-root}/_bmad-output/specs/spec-harness-surgery/SPEC.md'
  - '{project-root}/_bmad-output/specs/spec-harness-surgery/brownfield.md'
  - '{project-root}/_bmad-output/specs/spec-harness-surgery/skill-dispositions.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `validate.sh`/`finish-feature.sh` recreate the primary Postgres and migrate the live `realestate` DB on every run, and CLAUDE.md still mandates the retired feature-pipeline/PR/CI regime that ADR 0005's BMad-SoR pivot replaced — blocking all v0.13 story execution.

**Approach:** Re-point validation at an ephemeral `imoveis-test` compose stack (primary becomes inviolable), make finishing fully local (validate → squash-merge → push, no PR/CI), delete the 7 non-BMad skills, and rewrite CLAUDE.md (project + global) + Cursor mirrors + living docs around BMad + bmad-loop + `scripts/agent` gates. The canonical contract is `SPEC.md` (CAP-1…CAP-9) + companions in `context:` — on any ambiguity, the SPEC wins.

## Boundaries & Constraints

**Always:** Primary compose project `imoveis` inviolable — zero create/recreate/restart/stop/down of its containers, zero `realestate` schema/data mutation from any validate/finish/cleanup path. Destructive docker ops fail closed on ambiguous or primary project identity. Every check that could block a merge pre-surgery (all-files pre-commit, unit, integration, contract, frontend build, E2E, domain hooks) can still block locally. Finish = `validate.sh all` → local squash-merge to `main` → immediate `git push origin main` → cleanup. Ephemeral stack ports derived, never hardcoded; image parity with primary Postgres (PostGIS 17-3.5 + pgvector). This surgery's own delivery bootstraps on the new stack and finishes via the new local flow — never the old path.

**Ask First:** Deleting any file not named in `skill-dispositions.md`; any `src/`|`frontend/` change beyond gate wiring; any operation that would stop/start primary containers.

**Never:** Named-volume deletion or `docker system prune --volumes` anywhere; replacement CI (runners/act/cron suites); renaming/editing `docs/features/BIN-*` or `docs/chats_history/`; bmad-loop internals; pruning WDS/CIS modules; weakening domain hooks (`validate-scrapers.sh --require-live`, `validate-ai.sh`, contract tests, `alembic check`).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Validate during live backfill | `validate.sh all` while Gemma backfill writes primary | Passes; zero docker events on project `imoveis`; `realestate` schema+rowcounts identical pre/post | N/A |
| Teardown, identity unset | `COMPOSE_PROJECT_NAME` unset in env+`.env.local` | Refuses destructive action, nonzero exit, names the ambiguity | Fail closed |
| Teardown, identity = primary | `COMPOSE_PROJECT_NAME=imoveis` | Refuses (no down/stop) unless explicit operator flag | Fail closed |
| Primary migration, backfill alive | `migrate-primary.sh` with `backfill:gemma:active` present in Redis | Refuses, tells operator to wait for TTL self-clear | Guard keys off live heartbeat only — stale `backfill:gemma:*` pacer keys never block |
| Primary migration, idle | heartbeat key absent | Guard passes in milliseconds; alembic upgrade runs on primary | N/A |
| Red validate before merge | any gate fails | finish aborts before squash-merge; `main` untouched | exit 1 |

</frozen-after-approval>

## Code Map

- `scripts/agent/validate.sh:48-50,147-149,162-167,186` — primary compose targeting to excise; lint stage gains pre-commit all-files (CAP-9)
- `scripts/agent/ensure-test-db.sh` — already migrates via host python given URL; re-point at ephemeral server
- `scripts/agent/teardown.sh:42-68` — fail-open default `imoveis` + single string-compare guard (CAP-2)
- `scripts/agent/finish-feature.sh:210-335` — PR/CI-watch machinery to remove; validate/cleanup skeleton survives (CAP-8)
- `scripts/agent/lib.sh`, `docker-cleanup.sh`, `docker-cleanup-lib.sh` — shared helpers; cleanup semantics to preserve
- `src/core/backfill_runner.py:170` — existing `Heartbeat`: key `{prefix}:active` = `backfill:gemma:active`, TTL 300s
- `docker-compose.yml` — postgres service image to mirror in test stack
- `.github/workflows/{ci,nightly,docs}.yml`, `sonar-project.properties`, `.github/dependabot.yml` — CAP-8/9 dispositions
- `.claude/skills/{feature-pipeline,babysit-pr,code-review,epic-completion,harness-retrospect,imoveis-planning-bridge,security-scan}` + same 7 under `.cursor/skills/` — delete (CAP-3)
- `CLAUDE.md`, `~/.claude/CLAUDE.md`, `.cursor/rules/imoveis-core.mdc`, `~/.cursor/rules/agent-hygiene.mdc` — rewrite per skill-dispositions inversions (CAP-4)
- `_bmad/custom/` — new per-skill overrides (CAP-6); `_bmad-output/project-context.md:82,87` — rules to flip (CAP-7)
- `docs/{harness-troubleshooting,development-guide,deployment-guide,source-tree-analysis}.md`, `docs/adr/0001–0004` — CAP-5 dispositions

## Tasks & Acceptance

**Execution:**
- [x] `docker-compose.test.yml` -- new: `postgres` (same image as primary compose) + `redis` only, docker-assigned host ports (`127.0.0.1::5432` style), throwaway anonymous volumes -- CAP-1 substrate
- [x] `scripts/agent/test-stack.sh` -- new: up/port-resolve/down the ephemeral project `${COMPOSE_PROJECT_NAME:-imoveis}-test`; exports derived `TEST_DATABASE_URL`/`REDIS_URL` -- single owner of test-stack lifecycle
- [x] `scripts/agent/validate.sh` -- replace primary `up`/`alembic run --rm api` with test-stack.sh + host-side `alembic upgrade head`/`check` against ephemeral DB; run `pre-commit run --all-files` in lint stage -- CAP-1, CAP-9
- [x] `scripts/agent/ensure-test-db.sh` -- accept ephemeral server URL; drop primary-server ADMIN_URL dependency -- CAP-1
- [x] `scripts/agent/migrate-primary.sh` -- new explicit operator migration: refuse while `backfill:gemma:active` exists in Redis, else alembic upgrade on primary -- ex-OQ-1
- [x] `scripts/agent/teardown.sh` + `docker-cleanup-lib.sh` -- fail-closed identity guard (refuse unset/ambiguous/primary; explicit flag for operator primary ops); keep never-volumes semantics -- CAP-2
- [x] `scripts/agent/finish-feature.sh` -- strip PR/CI paths; new flow: feature-doc gate → dirty-check → validate.sh all → fetch → local squash-merge to main → `git push origin main` → cleanup (doc gate replaced the old post-hoc gen-docs step so docs land in the squash commit) -- CAP-8
- [x] `.github/` -- delete `ci.yml` + `sonar-project.properties`; trim `nightly.yml` to scraper drift-canary job; keep `docs.yml`, `dependabot.yml` -- CAP-8/9
- [x] `.claude/skills/` + `.cursor/skills/` -- delete the 7 non-BMad skills in both mirrors -- CAP-3
- [x] `_bmad/custom/{bmad-dev-story,bmad-quick-dev,bmad-dev-auto}.toml` -- overrides mandating `scripts/agent` gates, forbidding raw pytest and primary-project compose actions -- CAP-6
- [x] `CLAUDE.md` -- rewrite per skill-dispositions inversions table (BMad+bmad-loop regime, inline discipline rules, no deleted-skill/PR/CI/Linear refs) -- CAP-4
- [x] `~/.claude/CLAUDE.md` + `.cursor/rules/imoveis-core.mdc` + `~/.cursor/rules/agent-hygiene.mdc` -- same pass: remove PR-babysitting/bmad-linear-bridge/Linear passages, mirror new regime -- CAP-4
- [x] `docs/` four living guides + ADR 0001–0004 superseded-by notes -- per skill-dispositions pruning table -- CAP-5
- [x] `_bmad-output/project-context.md` -- flip lines 82/87 to new invariants -- CAP-7
- [x] `_bmad-output/implementation-artifacts/sprint-status.yaml` + `docs/features/v0.13-fu1-harness-surgery.md` -- mint `v0.13-fu1` key; feature doc from template -- tracking convention

**Acceptance Criteria:**
- Given a live backfill heartbeat, when `validate.sh all` runs, then it exits green with zero `docker events` on project `imoveis` and identical pre/post `realestate` dump (CAP-1)
- Given a planted F401 violation in a scratch file outside `src/`, when `validate.sh fast` runs, then it fails (CAP-9)
- Given the rewritten surfaces, when grepping CLAUDE.md (both), Cursor rules, and living docs, then zero matches for feature-pipeline mandate, PR/CI gate instructions, Linear, or any of the 7 deleted skill names (CAP-4/5)
- Given `origin/main` after a finish run, then it equals local `main` (CAP-8)

## Spec Change Log

- 2026-08-05 (review pass, no loopback — patch-class fixes applied in place): Blind Hunter + Edge Case Hunter findings triaged to 18 patches / 2 defers (see deferred-work.md) / 2 human decisions (global `~/.claude/skills/` legacy copies; security-audit replacement). Task line for finish-feature.sh clarified: the built flow uses a pre-merge feature-doc existence gate instead of the originally-worded post-merge gen-docs step (docs must land inside the squash commit). KEEP: ephemeral-stack design, fail-closed identity-from-file parsing, heartbeat guard semantics — all held under adversarial review.

## Design Notes

Ephemeral project name: `${COMPOSE_PROJECT_NAME:-imoveis}-test` — `imoveis-test` on primary (per SPEC assumption), worktree-safe suffixing elsewhere. Alembic runs host-side against the ephemeral server (`.venv` python, `PYTHONPATH=src`), removing the `run --rm api` image dependency from validation entirely. Global-file edits (`~/.claude/`, `~/.cursor/`) are uncommittable — report their diffs in the wrap-up.

## Verification

**Commands:**
- `docker events --filter label=com.docker.compose.project=imoveis` captured across `bash scripts/agent/validate.sh all` -- expected: zero events; pre/post `pg_dump --schema-only` + rowcount query identical
- `env -u COMPOSE_PROJECT_NAME bash scripts/agent/teardown.sh; COMPOSE_PROJECT_NAME=imoveis bash scripts/agent/teardown.sh` -- expected: both refuse, nonzero exit
- `redis-cli -p $REDIS_PORT set backfill:gemma:active 1 ex 60 && bash scripts/agent/migrate-primary.sh` -- expected: refusal; after `del`, passes
- planted `scratch_f401.py` with unused import outside `src/` -- expected: `validate.sh fast` fails; remove after
- grep sweep: `grep -rniE 'feature-pipeline|babysit|linear|pull request|gh pr|sonar' CLAUDE.md .cursor/rules docs/*.md` (excluding history dirs) -- expected: no regime-instruction hits

## Suggested Review Order

**Primary-safe validation (CAP-1)**

- Entry point: the ephemeral-stack bring-up that replaced every primary compose call
  [`validate.sh:92`](../../scripts/agent/validate.sh#L92)
- Project name always suffixed `-test` and asserted ≠ primary — fail closed by construction
  [`test-stack.sh:47`](../../scripts/agent/test-stack.sh#L47)
- Derived env exports are `%q`-quoted so the eval in validate.sh is injection-safe
  [`test-stack.sh:68`](../../scripts/agent/test-stack.sh#L68)
- Docker-assigned ports, no named volumes, image parity with primary postgres
  [`docker-compose.test.yml:1`](../../docker-compose.test.yml#L1)
- Admin (CREATE DATABASE) follows the target server — never defaults to primary
  [`ensure-test-db.sh:36`](../../scripts/agent/ensure-test-db.sh#L36)

**Fail-closed destruction (CAP-2)**

- Identity parsed from `.env.local` only; inherited env never trusted for destruction
  [`teardown.sh:60`](../../scripts/agent/teardown.sh#L60)
- Primary refusal (operator `--primary` override; volumes never wiped)
  [`teardown.sh:77`](../../scripts/agent/teardown.sh#L77)

**Explicit primary migration (ex-OQ-1)**

- Heartbeat guard: alive → refuse; idle → proceed; unreachable Redis → fail closed
  [`migrate-primary.sh:67`](../../scripts/agent/migrate-primary.sh#L67)

**Local, PR-less finish (CAP-8)**

- No zero-gate path to main: `--skip-validate` restricted to docs-only + mkdocs gate
  [`finish-feature.sh:31`](../../scripts/agent/finish-feature.sh#L31)
- Main-moved-since-validation guard (exit 2) — never merge an unvalidated combination
  [`finish-feature.sh:253`](../../scripts/agent/finish-feature.sh#L253)
- Squash-merge → commit → mandatory push; failure paths restore the workspace branch
  [`finish-feature.sh:256`](../../scripts/agent/finish-feature.sh#L256)
- Feature-doc gate keyed off the branch story key (bare-key and dry-run safe)
  [`finish-feature.sh:129`](../../scripts/agent/finish-feature.sh#L129)

**CI absorption (CAP-9)**

- Vendored dirs excluded from style hooks only; secret/size hooks stay global
  [`.pre-commit-config.yaml:11`](../../.pre-commit-config.yaml#L11)
- Nightly trimmed to the external-surface drift canary
  [`nightly.yml:1`](../../.github/workflows/nightly.yml#L1)

**Regime rewrite (CAP-3/4/5/6/7) — peripherals**

- The new ticket→ship contract every session reads first
  [`CLAUDE.md:35`](../../CLAUDE.md#L35)
- Gate bindings that constrain the BMad dev skills
  [`bmad-dev-story.toml:1`](../../_bmad/custom/bmad-dev-story.toml#L1)
- Characterization test re-anchored to the pre-commit source of truth
  [`test_no_fstring_sql_lint.py:81`](../../src/tests/unit/test_no_fstring_sql_lint.py#L81)
- Full inventory of doc-surface changes + review-hardening notes
  [`v0.13-fu1-harness-surgery.md:1`](../../docs/features/v0.13-fu1-harness-surgery.md#L1)
