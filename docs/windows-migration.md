# Windows checkout migration — 2026-10-01

This audit covers moving development from `/home/felipe/workfolder/imoveis` to
`C:\Workfolder\imoveis`. It records pending work and state that Git does not
carry. Native Windows runtime and validation remain unverified.

## Repository audit

At audit start, WSL `main` and freshly fetched `origin/main` both pointed to
`676757030d7edc29ab02b62f3a89c15f39013d35`, with no tracked edits or unpushed main
commits. The Windows checkout was at `74c109a`, 376 commits behind with no
divergent commits.

| Location | Finding and disposition |
| --- | --- |
| WSL working tree | Only `.codex/` was untracked: a Linear MCP entry and loop hooks using `CLAUDE_PROJECT_DIR`. Preserve privately; review before enabling on Windows. Local exclusion belongs in `.git/info/exclude`. |
| Story 2.1 branch | `bmad-loop/20260813-054802-28e6/2-1-cohort-price-m2-percentiles-pipeline` has one unique commit, `f41972f`, containing only a blocked-session report. No implementation was started. A dated [archive](migration/2026-08-13-story-2-1-blocked.md) accompanies this handoff. The original branch/worktree remains owned by the paused orchestrator. |
| Old stashes | Three pre-existing stashes: coverage output, old Cursor/scoring/UI work, and an obsolete Cline/PR workflow. The user requested removal. Private recovery copies precede removal; none is applied over current code. |
| Old remote feature branch | `origin/feat/v0-13-s1-3-followup-review` points to `9020659`. `git cherry -v main <branch>` reports `-`: its patch is already represented on main. |
| Windows local files | `src/tests/conftest.py` is an old untracked fixture that conflicts with the modern tracked file. Preserve it outside the checkout before updating. Preserve `.claude/` and `opencode.jsonc` privately too. |
| Other worktree entries | `/home/felipe/backfill-run` is a stale registration with a missing checkout. The four `.worktrees/` directories contain no files. Neither represents live implementation to merge. |

This migration's documentation change uses `scripts/agent/finish-feature.sh`.
Its docs-only path runs `mkdocs build --strict`, merges, and pushes. That result
does not establish application-test or native Windows acceptance.

## Existing pending development

The authoritative backlog remains
`_bmad-output/planning-artifacts/epics.md` and
`_bmad-output/implementation-artifacts/sprint-status.yaml`.
No completion status changes as part of this migration.

- **2-7-corpus-repair-fabricated-scores:** `awaiting-operator`. Code is merged;
  corpus-repair application and re-admission evidence remain unconfirmed. Follow
  the [operator procedure](features/v0.13-s2.7-corpus-repair-fabricated-scores.md).
- **DW-32 / epic-3-retro-item-3:** open. Automatic primary migration in
  `scripts/start.sh` remains a blocker before Story 2.1.
- **Stories 2-1 through 2-5:** backlog. Existing order: 2.7 operator completion +
  DW-32 → 2.1 → (2.2 and 2.3) → (2.4 and 2.5), subject to each story's explicit
  gates. Story 2.6 is done.
- **fu12 / fu13 / fu14:** dashboard plural agreement, toast/compare-bar overlap,
  and setup-worktree renaming orchestrator branches.
- **Open retrospective items:** epic-1 items 1 and 5; epic-3 items 1, 2, and 3.
- **Deferred ledger:** 34 numbered entries, 21 marked open: DW-8, 9, 10, 12–16,
  19–26, 28–30, 32, 34. The ledger also contains **36 unnumbered source-spec
  notes**. These may overlap numbered work and follow-ups; their count does not
  mean 36 distinct unresolved tasks.
- **Review flags:** eight specs retain `followup_review_recommended: true`:
  1.6, 2.7, 3.1–3.5, and dw-decision-dw-2. A flag is a review obligation, not
  proof of a new defect.

Run `20260813-054802-28e6` remains paused. Its local `ATTENTION` file records the
Story 2.7 operator checklist and Story 2.1 escalation. Old run worktrees contain
absolute WSL Git/workspace references; preserve them as evidence and use the
orchestrator's recovery path before resuming from Windows.

### Open dependency proposals

GitHub's open-PR API returned ten Dependabot PRs. They remain unvalidated and
pending. Their application gate requires a working Docker test stack.

| PR | Update |
| --- | --- |
| [219](https://github.com/felipelrib/imoveis/pull/219) | python-dotenv 1.2.3 |
| [218](https://github.com/felipelrib/imoveis/pull/218) | SQLAlchemy 2.0.52 |
| [217](https://github.com/felipelrib/imoveis/pull/217) | uvicorn 0.52.3 |
| [216](https://github.com/felipelrib/imoveis/pull/216) | Alembic 1.19.1 |
| [213](https://github.com/felipelrib/imoveis/pull/213) | FastAPI 0.141.1 |
| [212](https://github.com/felipelrib/imoveis/pull/212) | Playwright 1.62.1 |
| [211](https://github.com/felipelrib/imoveis/pull/211) | react-router-dom 7.18.2 |
| [210](https://github.com/felipelrib/imoveis/pull/210) | @vitejs/plugin-react 6.0.5 |
| [209](https://github.com/felipelrib/imoveis/pull/209) | @types/react 19.2.18 |
| [208](https://github.com/felipelrib/imoveis/pull/208) | @types/react-dom 19.2.4 |

## State Git will not move

Keep the private recovery directory outside the repository. It contains secrets
and local agent records and must not be committed or uploaded.

| Local state | Transfer treatment |
| --- | --- |
| `.env.local` | Copy privately. Review database host/port, routing, and host-specific settings. Contains API/cloud credentials and a WSL-only password entry; never print values. |
| `frontend/.env.development` | Copy privately; verify API URL and credential against the intended backend. |
| `AGENTS.md`, `docs/ai/` | Copy local project rules, gotchas, and prior project-memory export. WSL references need review as Windows support changes. |
| `.cursor/`, `.claude/` | Preserve rules, settings, and skill mirrors. Canonical `.agents/skills/` is already tracked. Review hooks before enabling; preserve Windows-only settings when combining directories. |
| `.codex/` | Archive for review. The old Linear entry conflicts with file-based tracking, and its hooks assume a Claude/Linux environment. Do not automatically activate it on Windows. |
| `_bmad/config.user.toml`, `_bmad/custom/config.user.toml` | Copy personal BMad preferences; team configuration is tracked. |
| `.bmad-loop/policy.toml`, `.bmad-loop/runs/` | Preserve policy and run evidence. Recreate or repair old run worktrees through the orchestrator before use on Windows. |
| Architecture `reviews/`, `data/bench/` | Optional historical evidence, included in the small local-state recovery copy. |
| `data/images/` | **387,859 files; 38,598,529,264 bytes (about 38.6 GB).** Separate bulk transfer required to preserve the host image cache; excluded from the small backup. |
| Docker PostgreSQL / Redis / image storage | Outside Git. Compose declares `postgres_data`, `redis_data`, and `image_store`. Actual daemon, volume names, contents, and backups still need verification. |
| `/etc/systemd/system/imoveis-backfill-serve.service` | Preserve as a reference. At audit time it was active and used the WSL checkout and Linux virtualenv. Native Windows needs an equivalent supervisor and deliberate single-runner cutover. |
| Git refs, stashes, worktree metadata | A private verified Git bundle preserves all refs and every original stash tip. A clone/pull alone does not. Old worktree `.git` pointers are not portable. |

Host `data/images/` and Docker's `image_store` volume are distinct configured
locations. Copying one does not prove the other is preserved. If Windows uses
the same Docker Desktop Linux engine, existing named volumes may be reusable;
confirm engine/context and exact volumes first. Otherwise export/restore the
database and Redis state and copy the image volume. Redis includes backfill
checkpoint, attempt, and budget state.

Recreate `.venv`, `node_modules`, `frontend/node_modules`, Playwright browser
installs, builds, coverage, caches, logs, and PID files. Linux executables do not
belong in a Windows environment. Recreate the workspace port registry too;
its old absolute paths are useful only as historical evidence.

## Native Windows readiness

The checkout can live on `C:\Workfolder\imoveis` independently of runtime
readiness. Before retiring WSL:

1. Make Docker Desktop available and identify the existing primary volumes.
   Its daemon was unreachable from Windows and its WSL integration unavailable
   during this audit. No primary container or database was changed.
2. Recreate Windows Python/frontend environments and validate the Bash agent
   gates under Git Bash. `lib.sh` states Git Bash support; `validate.sh` prefers
   `.venv/bin/python`, so Windows virtualenv discovery needs an actual run.
3. Replace the systemd-only backfill hosting path while preserving environment,
   checkpoint, quota, and migration-exclusion contracts. Stop the old supervisor
   during cutover before enabling another against the same corpus.
4. Transfer or reuse data stores and images, then verify counts, image reads,
   API/frontend connectivity, and Ollama access.
5. Run `bash scripts/agent/validate.sh all` against the ephemeral test stack.
   Primary DB repairs remain subject to their operator procedure; do not use
   startup scripts to bypass Story 2.7 or DW-32.
