---
title: 'Finish native Windows development migration'
type: 'bugfix'
created: '2026-10-01'
status: 'done'
baseline_commit: 'ff69e260f30c41ce38a83969c2decf1f3efd6490'
review_loop_iteration: 0
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/docs/adr/0006-backfill-runner-hosting.md'
authorization: 'User requested implementation and verification of the full Windows migration; confirmed automatic backfill startup at Windows sign-in.'
---

<frozen-after-approval reason="human-owned migration intent">

## Intent

**Problem:** The Windows checkout is current but native gates, dependencies,
runtime data, and backfill supervision have not been made operational. WSL
path assumptions and the Linux dependency lock prevent reliable native use.

**Approach:** Complete the migration in the Windows checkout, preserve existing
corpus and Redis state, provide sign-in Task Scheduler supervision, and prove
the result through the project's full gate plus live application checks.

## Boundaries & Constraints

**Always:** Native Windows Python and Git Bash execute host code and gates.
Preserve Linux support, secret confidentiality, existing backfill lease/drain,
quota, checkpoint and migration-exclusion contracts. Retain source data until
the Windows copy is verified. Keep the primary Docker stack and DB protected.
Ship through finish-feature.sh and push main. Sign-in startup is explicitly
accepted by the user; pre-login service operation is not required.

**Ask First:** Any primary-stack action prohibited by project rules; replacing
existing data, changing business behavior, or expanding beyond migration fixes.

**Never:** Skip/weaken gates, expose credentials, use WSL tests as Windows
acceptance, delete source data, hard-kill a draining runner, start concurrent
supervisors, or mark the unrelated feature/dependency backlog complete.

## I/O & Edge-Case Matrix

| Scenario | Input / state | Expected behavior | Error handling |
| --- | --- | --- | --- |
| Native checkout | Git drive paths and MSYS paths denote same root | Primary remains primary | Genuine linked worktree remains isolated |
| Native tooling | Project venv and WindowsApps aliases coexist | Use project interpreter/tools | Missing runnable Python fails clearly |
| Path inheritance | Spaces and existing native PYTHONPATH | App imports use correct path separator | Never fall back silently to WSL |
| Platform dependencies | Python 3.11 on Windows | Install pinned compatible packages | Linux-only uvloop is not requested |
| Supervisor start | Valid private env, no old owner | One user task runs existing serve loop | Invalid config fails without values in output |
| Supervisor stop | Idle or active, matching stop nonce | Existing handlers drain then exit | Timeout retains process and reports failure |
| Duplicate / stale state | Second launch or old stop file | Exclusive lock; stale nonce ignored | No second Redis/cloud owner |
| Data transfer | Existing images and Docker state | Copy/reuse with counts and verification | No destructive sync or volume removal |

</frozen-after-approval>

## Code Map

- `scripts/agent/lib.sh` and gate scripts — root identity, Python/tool discovery,
  environment isolation, test-stack and finish lifecycle.
- `requirements.in`, `requirements.txt` — dependency sources and Linux pins.
- `scripts/dev/backfill_gemma.py` — existing supervisor and cooperative handlers.
- `deploy/systemd/`, `scripts/install-backfill-runner.sh` — Linux hosting contract.
- `docs/windows-migration.md` — checklist and final operational evidence.

## Tasks & Acceptance

**Execution:**
- [x] `requirements-windows.txt` — generate with native Python 3.11 from
  requirements.in, constraining shared versions to requirements.txt; install
  runtime, gate tooling, Node packages and Playwright without editing Linux pins.
- [x] `.gitattributes`, `scripts/agent/lib.sh` — stable shell newlines, canonical
  roots, native/POSIX Python activation and platform-correct module paths.
- [x] `scripts/agent/{validate,setup-tools,ensure-test-db,audit-deps,migrate-primary}.sh`
  — consume shared helpers, quote interpreter paths, preserve gate strength.
- [x] `src/tests/unit/` shell-harness tests — first characterize native failures,
  then cover identity, interpreter precedence, spaces, environment paths and
  compatible fixtures without reducing invariant coverage.
- [x] `scripts/windows/backfill_host.py`, `scripts/install-backfill-runner.ps1`
  — literal private env loading, exclusive process ownership, cooperative stop,
  crash restart, safe check/status/install/uninstall, sign-in task under the user.
- [x] `src/tests/unit/test_windows_backfill_host.py` — process lifecycle,
  failed preflight, duplicate/stale state, stop/drain and secret confinement.
- [x] `docs/adr/0006-backfill-runner-hosting.md`, `docs/setup.md`,
  `docs/windows-migration.md`, `docs/features/windows-native-migration.md` —
  document supported Windows setup and actual evidence; mirror durable harness
  guidance in CLAUDE.md, AGENTS.md, docs/ai and Cursor rules as applicable.
- [x] Private host state — copy and verify images; identify/preserve Docker
  corpus, Redis and image volumes; validate local configuration and Ollama;
  drain/disable WSL supervisor before enabling its native replacement.
- [x] Native acceptance — execute full native test/build/E2E stages and inspect
  API/frontend and supervisor health. Independent review and finish/push are the
  following workflow steps; completion is recorded only after they succeed.

**Acceptance Criteria:**
- Given the Windows checkout, when the documented gate runs, then native host
  tests/build/E2E pass against the ephemeral stack with primary data preserved.
- Given the accepted sign-in policy, when Windows supervision starts/stops,
  then it uses the Windows checkout and existing state with one safe owner.
- Given the migration checklist, when handoff is completed, then every migration
  item has concrete verification or a clearly identified external blocker;
  unrelated backlog remains accurately tracked.

## Spec Change Log

- 2026-10-01: The user approved the one-time primary app-container mount
  cutover: API, both workers and beat only, existing images, up to 900 seconds
  to drain. PostgreSQL, Redis and all data volumes remain in place. This is
  a scoped operational exception, not a change to the frozen safety boundary.

## Verification

- `bash scripts/agent/validate.sh fast` — focused implementation feedback via
  the sanctioned gate, including regression tests before and after fixes.
- `bash scripts/agent/validate.sh all` — full native Windows acceptance.
- `bash scripts/agent/finish-feature.sh` — validated merge, push and cleanup.
- Read-only corpus/Redis/image checks, copy reconciliation, native supervisor
  lifecycle, Ollama connectivity, and browser/API smoke evidence.

### Observed native acceptance (2026-10-01)

- Final finish gate: 2,146 unit tests passed (2 skipped, 1 slow deselected),
  119 integration, 51 contract and 110 Chromium E2E passed; lint/build passed.
  Advisory dependency stage runs afterward and does not suppress test failures.
- Native Task Scheduler install, idle stop, heartbeat removal and reinstall
  succeeded; active drain and crash recovery passed in real child-process tests.
- App-only Windows bind cutover completed under the explicit exception. Primary
  database/Redis containers and data volumes stayed in place. Scraper exceeded
  its approved 900-second drain and was terminated by Docker before recreation.
- All 387,859 host images SHA256 verified; live API/service health and local
  Ollama inference succeeded. Private evidence is outside Git.
- Independent review completed: one medium `patch` finding (Windows preflight
  omitted Linux's default-database advisory) was fixed with three output/secret
  regressions. Its red gate had one expected failure and 2,145 passes.
  Edge Case Hunter found no actionable issues. No intent or spec loopback required.
- The mandatory native finish gate validated the final code, squash-merged it
  as `09b20093`, pushed it to origin/main and cleaned the disposable stack and
  implementation branch. Spec closure is recorded after that successful push.
- BMad preflight has no blocking problems. Its older-relay advisory was checked
  with an isolated Windows event smoke: SessionStart and Stop were both received
  exactly once. The historical paused run remains unchanged.

## Suggested Review Order

**Host lifecycle**

- Enter the existing runner through one native owner and cooperative stop channel.
  [backfill_host.py:271](../../scripts/windows/backfill_host.py#L271)

- Register a sign-in task with safe lifetime and restart settings.
  [install-backfill-runner.ps1:109](../../scripts/install-backfill-runner.ps1#L109)


**Configuration boundary**

- Load literal private settings before imports; report only vetted preflight warnings.
  [backfill_host.py:194](../../scripts/windows/backfill_host.py#L194)


**Gate portability**

- Select native Python and construct platform-correct import paths.
  [lib.sh:74](../../scripts/agent/lib.sh#L74)

- Keep ephemeral validation and native tools under the existing gate.
  [validate.sh:28](../../scripts/agent/validate.sh#L28)


**Evidence and support**

- Exercise native drain, ownership, retries and safe configuration output.
  [test_windows_backfill_host.py:112](../../src/tests/unit/test_windows_backfill_host.py#L112)

- Pin native root identity, interpreter precedence and path handling.
  [test_windows_agent_gate.py:34](../../src/tests/unit/test_windows_agent_gate.py#L34)

- Review transferred state, live cutover evidence and remaining unrelated work.
  [windows-migration.md:109](../../docs/windows-migration.md#L109)
