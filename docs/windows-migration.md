# Windows checkout migration — 2026-10-01

This audit covers moving development from `/home/felipe/workfolder/imoveis` to
`C:\Workfolder\imoveis`. It records pending work and state that Git does not
carry. Native dependencies, data transfer, runtime cutover and the full native
finish gate are complete. The migration code is pushed to `origin/main`.

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

The initial audit shipped as `ff69e26` through the docs-only finish gate. The
runtime migration shipped as `09b20093` through the full native
`finish-feature.sh` gate of the time, including merge, push and disposable-stack
cleanup. (That script was retired on 2026-10-07 — see
[ADR 0007](adr/0007-tiered-gate-and-hook-enforced-push.md); the current gate is
`python scripts/agent/validate.py` and shipping is `python scripts/agent/ship.py`.)

## Existing pending development

The authoritative backlog remains
`_bmad-output/planning-artifacts/epics.md` and
`_bmad-output/implementation-artifacts/sprint-status.yaml`.
No completion status changes as part of this migration.

- **2-7-corpus-repair-fabricated-scores:** `awaiting-operator`. Code is merged;
  corpus-repair application and re-admission evidence remain unconfirmed. Follow
  the [operator procedure](features/v0.13-s2.7-corpus-repair-fabricated-scores.md).
- **DW-32 / epic-3-retro-item-3:** closed on 2026-10-08 by story `v0.14-s1.4`
  ([feature doc](features/v0.14-s1.4-primary-migration-cannot-bypass-the-backfill-guard.md)):
  `scripts/start.sh` no longer migrates the primary compose project. It was open,
  and a blocker before Story 2.1, when this record was written.
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
| `.env.local` | Copy privately. Review database host/port, routing, and host-specific settings. API/cloud credentials remain private; the unused WSL-only password entry was removed from the native copy. |
| `frontend/.env.development` | Copy privately; verify API URL and credential against the intended backend. |
| `AGENTS.md`, `docs/ai/` | Copy local project rules, gotchas, and prior project-memory export. WSL references need review as Windows support changes. |
| `.cursor/`, `.claude/` | Preserve rules, settings, and skill mirrors. Canonical `.agents/skills/` is already tracked. Review hooks before enabling; preserve Windows-only settings when combining directories. |
| `.codex/` | Archive for review. The old Linear entry conflicts with file-based tracking, and its hooks assume a Claude/Linux environment. Do not automatically activate it on Windows. |
| `_bmad/config.user.toml`, `_bmad/custom/config.user.toml` | Copy personal BMad preferences; team configuration is tracked. |
| `.bmad-loop/policy.toml`, `.bmad-loop/runs/` | Preserve policy and run evidence. Recreate or repair old run worktrees through the orchestrator before use on Windows. |
| Architecture `reviews/`, `data/bench/` | Optional historical evidence, included in the small local-state recovery copy. |
| `data/images/` | **387,859 files; 38,598,529,264 bytes (about 38.6 GB).** Copied to native `data/images/`; every file SHA256 matched the source, with zero missing, extra or mismatched files. Source retained. |
| Docker PostgreSQL / Redis / image storage | Outside Git. Compose declares `postgres_data`, `redis_data`, and `image_store`. The same `desktop-linux` engine retains `imoveis_postgres_data`, `imoveis_redis_data` and `imoveis_image_store`; no data volume was replaced. |
| `/etc/systemd/system/imoveis-backfill-serve.service` | Preserved privately. The WSL unit is now disabled/inactive with PID 0. The native sign-in task replaces it; stop/restart and Redis heartbeat were verified. |
| Git refs, stashes, worktree metadata | A private verified Git bundle preserves all refs and every original stash tip. A clone/pull alone does not. Old worktree `.git` pointers are not portable. |

Host `data/images/` and Docker's `image_store` volume are distinct configured
locations. Copying one does not prove the other is preserved. If Windows uses
the same Docker Desktop Linux engine, existing named volumes may be reusable;
confirm engine/context and exact volumes first. Otherwise export/restore the
database and Redis state and copy the image volume. Redis includes backfill
checkpoint, attempt, and budget state.

Recreate `.venv`, `node_modules`, `frontend/node_modules`, Playwright browser
installs, builds, coverage, caches, logs, and PID files. Linux executables do not
belong in a Windows environment. The old workspace port registry
(`.agent-workspaces/`) is retired with the worktree tooling; its absolute paths
are useful only as historical evidence.

## Native Windows readiness

Private evidence and recovery files live outside Git at
`C:\Workfolder\imoveis-migration-20261001-010057`. They include credentials and
agent records; do not upload or commit this directory. New verification receipts
supplement the original transfer receipt.

- **Dependencies:** native Python 3.11.15, regenerated Windows dependency lock,
  gate tooling, `npm ci` and Playwright Chromium installed. The previous native
  virtualenv is preserved privately. Linux lock and Docker dependency pins stay intact.
- **Images:** complete host-cache transfer verified with SHA256 for all 387,859
  files; receipts `images-verification.json` and `images-source-sha256.jsonl`.
  This is separate from the retained Docker `image_store` volume.
- **Database recovery:** `postgres-before-windows-cutover.dump` is a 372,210,414-byte
  custom-format archive, SHA256
  `529795063c72fb1352a37772549f33f33e262ddb1e313c546584d0601d7c7946`.
  `pg_restore --list` parsed its 121 table-of-contents lines. A restore rehearsal
  was not performed; the live database and Redis volumes are reused in place.
- **Docker:** Desktop's stale runtime sockets were isolated without resetting
  data; Engine 29.6.1 became available. The operator separately approved replacing
  only API, workers and beat to bind native configuration. Existing images were
  verified against the checkout's 101 production Python files per image.
- **Local AI:** native Ollama produced an actual 1024-dimensional `bge-m3`
  embedding and a successful `qwen2.5vl:7b` response. No cloud run was requested.
- **Application smoke:** native Vite served the property grid with live records
  and images. Authenticated host HTTP checks returned successful health, system
  status and backfill status responses before container cutover.
- **Harness:** native BMad CLI and psmux are available; canonical skills are
  mirrored locally and the verification command of the time explicitly used Git
  Bash (the current `validate.py` gate runs from any shell). The
  historical paused orchestrator run remains paused and preserved. Its unrelated
  operator gates are not bypassed by this migration.
  Final preflight reports 13 OK, zero problems and one advisory about the older
  committed hook relay. An isolated native smoke confirmed the current runtime
  receives both SessionStart and Stop exactly once through its legacy channel.
  Updating the orchestrator relay is separate version maintenance.

### Completed runtime cutover

The four app containers now bind `C:\Workfolder\imoveis\configs`, using the same
verified image IDs. All seven config files match the WSL source after newline
normalization. PostgreSQL retains its August 13 container and Redis its August 4
container, with their original named volumes. The scraper exceeded the approved
900-second drain window and exited 137 at Docker's cutoff; its replacement started
and resumed processing queued jobs. Redis queue/unacknowledged state remains in
place. This was not a clean completion of every in-flight scrape.

Post-cutover native HTTP checks returned `/health` OK and authenticated
`/system/status` HTTP 200 with database, Redis, Ollama and workers all OK.
`/admin/backfill/status` returned HTTP 200, `runner_present=true`, state `idle`.
The live snapshot contained 178,085 properties, 251,112 listings and 275,720 price
history rows; these counts continue to change while workers run.

The WSL systemd supervisor is disabled/inactive (PID 0). The installed
`Imoveis-Backfill-Supervisor` task has native `pythonw.exe`, Windows working
directory, interactive sign-in and recovery triggers, `IgnoreNew`, no time limit,
no hard termination and no battery stop. Its actual interpreter process was
verified against the Windows command line. A real Stop disabled the task and
cleared the Redis heartbeat; reinstall restarted it and restored the heartbeat.
No cloud start request or active backfill lease was present. Sign-out/reboot was
not forced during this session; sign-in behavior is supported by the registered
trigger and exercised task action, not a claim of an observed login cycle.

### Validation and remaining development scope

The native full gate uses only `imoveis-test` for disposable PostgreSQL/Redis.
Its first pass confirmed 119 integration and 51 contract tests. Corrections to
Windows process identity fixtures and a Vite-held native module lock precede the
final gate result, recorded below. Native `pip check` is clean and installed
versions exactly match the regenerated Windows lock. Strict MkDocs build passes.

External scrape results remain source-dependent: the replacement worker logged
OLX's missing FlareSolverr hostname and Zap HTTP 403. No FlareSolverr sidecar was
running before this cutover; all mounted config matches the source. These are
existing operational/source-access issues, not data-transfer failures. Dependency
advisories and the feature/operator backlog above remain separate work. No
migration procedure authorizes primary schema repair or closes those items.

The final browser smoke loaded live grid records and images. An additional map
check exposed an existing API-contract mismatch: `Properties.tsx` requests
`page_size=200`, while `src/api/properties.py` accepts at most 100. A direct native
HTTP request reproduced 422 with that validation error; both files are unchanged
from the migration baseline. Vite also logged a missing optimized
`maplibre-gl-worker.mjs` asset. Map behavior needs application follow-up; the
passing browser suite does not establish that the live map works. An unsigned
browser session also needs the existing API credential for administrative views;
separate authenticated HTTP probes verified those endpoints without exposing it.

The final finish gate passed **2,146 unit tests** (2 skips and 1 slow test
deselected), **119 integration tests**, **51 contract tests**, and **110 Chromium
E2E tests**, plus lint and the frontend build. The dependency audit is advisory;
its findings do not erase the separate dependency-update backlog.

### Continue development

Use `C:\Workfolder\imoveis` as the project folder and the native commands in
[setup](setup.md) (`.venv/Scripts/python.exe scripts/agent/validate.py`, no Git
Bash required). Stop the Vite development server before running the `frontend`
or `full` tier: Windows can lock its native modules while `npm ci` replaces
dependencies.

This existing Codex chat still declares the historical WSL UNC folder as its
default workspace. All migration commands explicitly targeted the Windows
checkout. Open the native folder for future Codex work; completing the code and
runtime migration does not rebind an existing chat's workspace setting.
