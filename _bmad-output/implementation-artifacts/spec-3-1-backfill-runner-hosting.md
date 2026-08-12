---
title: 'Backfill runner hosting — a committed, supervised home for the consumer'
type: 'feature'
created: '2026-08-12'
status: done
baseline_revision: 'd1fd2e5f5e578d6cb52bbb9c775d7d86f9f73801'
final_revision: 'cb690fbad3476330702313bf4754f5d756f793d9'
review_loop_iteration: 1
followup_review_recommended: true
operator_actions:
  - 'Add GEMINI_API_KEY and DATABASE_URL to .env.local in the primary checkout (/home/felipe/workfolder/imoveis), plus REDIS_URL whenever REDIS_PORT is not 6379; point DATABASE_URL at the primary realestate database on the published POSTGRES_PORT, use plain KEY=value lines with no export prefix and LF endings, and never commit the file.'
  - 'Set the backfill task classes in configs/app_config.yaml ai.enrichment_routing (visual, sentiment, deal_verdict) to gemma before installing — with the shipped all-ollama default the supervisor exits at startup and the unit restarts every 10 seconds.'
  - 'Stop any hand-started `scripts/dev/backfill_gemma.py --serve` process (tmux/nohup) and remove any previously hand-installed imoveis-backfill-serve.service, so exactly one supervisor beats backfill:gemma:supervisor:active.'
  - 'From the primary checkout (never a linked worktree) run `bash scripts/install-backfill-runner.sh --check`, resolve anything it reports, then run `bash scripts/install-backfill-runner.sh` and approve the sudo prompt — it writes /etc/systemd/system/imoveis-backfill-serve.service, enables it and restarts it.'
  - 'Verify the supervisor is alive with `systemctl status imoveis-backfill-serve` and `journalctl -u imoveis-backfill-serve -n 50`, then press Start on the Operações backfill card and confirm a run begins and the status endpoint reports runner_present true.'
  - 'Verify unattended recovery: reboot the host (or run `sudo systemctl restart imoveis-backfill-serve`) and confirm the unit returns active with no manual step and without starting a second run under the shared lease.'
  - 'Re-run `bash scripts/install-backfill-runner.sh` after moving the repo, rebuilding .venv, or raising backfill.lease_ttl_seconds — the installed unit is rendered once and does not track those changes.'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-3-context.md'
  - '{project-root}/docs/features/v0.13-s1.5-admin-backfill-control-api.md'
warnings: ['oversized']
---

<intent-contract>

## Intent

**Problem:** `POST /admin/backfill/start` only records a request; nothing consumes it unless someone has hand-started `scripts/dev/backfill_gemma.py --serve` on the host, and no unit, installer or supervised home is committed anywhere (DW-27). The only guidance is an example systemd unit inside story 1.5's feature doc whose env contract is incomplete — it supplies neither `DATABASE_URL` (the runner's config default is `imoveis`, not the primary `realestate`) nor `REDIS_URL`, `GEMINI_API_KEY` is absent from `.env.local.example`, and its default stop timeout can `SIGKILL` a draining run mid-property.

**Approach:** Commit the runner's home as a **systemd system unit template** plus an operator installer (`scripts/install-backfill-runner.sh`) that renders it for this host, preflights the env contract, and installs/enables/uninstalls it; record the topology choice and the two rejected alternatives (dedicated compose service, promotion of the 2117-line script out of `scripts/dev`) in an ADR. The runner keeps running host-side, out of the repo `.venv`, against the primary stack's published ports — the placement it already has in production — and no runner, admin or domain code changes.

## Boundaries & Constraints

**Always:**
- The runner stays **on-box, host-side, as the operator's own user**; nothing about this change routes scraping or enrichment through a container or a datacenter ASN.
- Secrets are env-only (NFR-3): the unit reads them via `EnvironmentFile=<repo>/.env.local` (git-ignored). No key value is ever written into a committed file, into the rendered unit, or echoed by the installer — only variable **names** appear.
- The unit is named **`imoveis-backfill-serve.service`** — the same name story 1.5's doc example used — so re-installing upgrades in place instead of leaving a second supervisor running.
- Recovery is unattended (AD-13 / NFR-6): `Restart=always`, `RestartSec=10`, `StartLimitIntervalSec=0` (a restart limit must never be able to strand the unit in `failed`), `WantedBy=multi-user.target` for reboot.
- Stopping is drain-safe: `KillSignal=SIGTERM` with `TimeoutStopSec` ≥ the 900s lease TTL, so a live run's in-flight rows finish instead of being `SIGKILL`ed half-written.
- No double-start: `--serve` never acquires the lease, request consumption stays the existing atomic `GETDEL`, and exactly one unit beats `backfill:gemma:supervisor:active`.
- The installer performs **no docker/compose action of any kind**, and no gate or script gains one.
- The agent does not run `sudo`, `systemctl`, or any privileged install step; everything requiring privilege is enumerated for the operator.

**Block If:**
- Delivering this would require editing `src/core/backfill_runner.py`, `src/api/admin.py`, or the backfill wire contract (hosting must not leak into runner internals — stories 3.2/3.4 own that file).

**Never:**
- No dedicated compose service, and no `GEMINI_API_KEY` in any container's environment.
- No promotion/refactor of `scripts/dev/backfill_gemma.py` into `src/` and no new package/console-script entrypoint (85 CLI tests and a 2117-line surface; the ADR records why).
- No Celery task hosting of the backfill.
- No new service, port, image, or volume in `docker-compose.yml`.
- No behavioural change to the runner, the supervisor loop, or the admin API.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Render for inspection | `install-backfill-runner.sh --print` with `--user/--python/--env-file` overrides | Unit text on stdout: `ExecStart=<python> <repo>/scripts/dev/backfill_gemma.py --serve`, `User=`, `EnvironmentFile=`, `Restart=always`, `RestartSec=10`, `StartLimitIntervalSec=0`, `KillSignal=SIGTERM`, `TimeoutStopSec=900`, `WantedBy=multi-user.target`; no `@@…@@` placeholder survives | No privilege needed; exit 0 |
| Install from a linked worktree | install mode, repo root's `.git` is a **file** | Refuses before touching the system | exit ≠ 0, message names the primary checkout |
| Env contract incomplete | env file lacks (or blanks) `GEMINI_API_KEY` or `DATABASE_URL` | Preflight fails naming the missing variable | exit ≠ 0; the value is never read back or printed |
| Redis port drift | env file sets a non-default `REDIS_PORT` but no `REDIS_URL` | Warning: the runner would talk to the wrong Redis | Warning only, install continues |
| No systemd | `systemctl` absent or PID 1 is not systemd | Refuses with the WSL `/etc/wsl.conf` `systemd=true` hint | exit ≠ 0 |
| Interpreter missing | `<repo>/.venv/bin/python` absent and no `--python` | Refuses, pointing at `scripts/setup.sh` | exit ≠ 0 |
| All-local routing | `ai.enrichment_routing` has no cloud task class | Warning that `--serve` will exit at startup until routing is cloud | Warning only (scope varies), install continues |
| Uninstall | `--uninstall` | Disables + stops the unit, removes it, reloads systemd | Missing unit is not an error |

</intent-contract>

## Code Map

- `scripts/dev/backfill_gemma.py` -- the consumer being hosted (`--serve` supervisor at `:1482`; validates scope + routing **before** the poll loop, so a misconfigured host exits at startup); unchanged by this story.
- `src/core/backfill_runner.py` -- `supervisor_prefix()`/`Heartbeat` (`:359-393`) behind `runner_present`, `BackfillLease` TTL 900s; unchanged.
- `src/api/admin.py:886-968` -- `POST /admin/backfill/start`, `runner_present = lease held OR supervisor heartbeat`; unchanged.
- `docs/features/v0.13-s1.5-admin-backfill-control-api.md:113-172` -- the example unit this story supersedes.
- `.env.local.example` -- env template; today has no `GEMINI_API_KEY`/`DATABASE_URL`/`REDIS_URL`.
- `configs/app_config.yaml:275-378` -- `ai.enrichment_routing` (all-`ollama` by default) and `backfill.*` (`redis_prefix: backfill:gemma`, `lease_ttl_seconds: 900`).
- `src/infra/config.py:61-100,780-868` -- `DatabaseConfig` defaults to db `imoveis` (**not** the primary `realestate`) → `DATABASE_URL` is mandatory for a host-side run.
- `mkdocs.yml:73-78` -- explicit ADR nav; a new ADR must be listed.
- `scripts/agent/docker-cleanup-lib.sh:44-48` -- compose image filter; untouched because no compose service is added.

## Tasks & Acceptance

**Execution:**
- [x] `deploy/systemd/imoveis-backfill-serve.service.in` -- new committed unit template with `@@USER@@`/`@@REPO_ROOT@@`/`@@PYTHON@@`/`@@ENV_FILE@@`/`@@TIMEOUT_STOP@@` placeholders -- the committed home DW-27 asks for.
- [x] `scripts/install-backfill-runner.sh` -- new operator script: `--print`, `--check`, install (default), `--uninstall`, `--status`; overrides `--user/--python/--env-file/--repo-root/--unit-name`; preflight per the I/O matrix; privileged steps via `sudo` only in install/uninstall mode -- one supported install path instead of copy-pasting a doc snippet.
- [x] `.env.local.example` -- document `GEMINI_API_KEY`, `DATABASE_URL`, `REDIS_URL` (names + placeholder shape only) -- the host-side runner's env contract, today undocumented.
- [x] `src/tests/unit/test_backfill_runner_hosting.py` -- unit-test the I/O matrix by invoking the script (`--print`/`--check`) with overrides and temp fixtures; assert the `ExecStart` target file exists, that no `@@` placeholder survives, that no secret value is echoed, and that the installer contains no `docker` invocation.
- [x] `docs/adr/0006-backfill-runner-hosting.md` -- record the systemd decision, the rejected compose-service and promote-to-`src` alternatives, cloud-key placement, and the local-first/residential-IP rationale.
- [x] `mkdocs.yml` -- add ADR 0006 to the explicit ADR nav.
- [x] `docs/setup.md` (Production Deployment) + `docs/deployment-guide.md` -- the operator install/upgrade step and where the runner lives.
- [x] `docs/features/v0.13-s3.1-backfill-runner-hosting.md` -- feature doc from `_template.md`, including the operator-visible install/upgrade step and the env contract.
- [x] `docs/features/v0.13-s1.5-admin-backfill-control-api.md` -- one-line pointer marking its inline unit example superseded by ADR 0006 + the installer (drift prevention only; leave the rest untouched).
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` -- close DW-27 with the resolution.

**Acceptance Criteria:**
- Given a checkout with the unit installed and enabled, when the operator presses Start with no run in flight, then a run begins with no manual host-side step and `runner_present` is true because the supervisor is beating its heartbeat — not because someone remembered to start a script.
- Given the unit is installed, when the host reboots or `systemctl restart imoveis-backfill-serve` runs, then the supervisor returns unattended, takes no lease, and cannot double-start a run that another holder owns.
- Given `bash scripts/agent/validate.sh all`, when it runs during a live backfill, then it still touches no primary compose project — this story adds no compose service and no `docker` call to any gate or script.
- Given the delivered docs, when an operator follows them, then the install/upgrade step, the `.env.local` contract (`GEMINI_API_KEY`, `DATABASE_URL`, `REDIS_URL`), the cloud-routing precondition and the uninstall path are all stated, and the choice is justified in ADR 0006 (listed in the docs nav).

## Spec Change Log

_No `bad_spec` loopback occurred. The single spec deviation the review found — the template rendered a relative `ExecStart` script path where the frozen I/O matrix specifies an absolute one — was patched in the code toward the matrix (the Design Notes' abridged example was corrected to match), not by amending the spec._

## Review Triage Log

### 2026-08-12 — Review pass (iteration 1)

- intent_gap: 0
- bad_spec: 0
- patch: 17: (high 1, medium 9, low 7)
- defer: 2: (medium 1, low 1)
- reject: 6: (medium 1, low 5)
- addressed_findings:
  - `[high]` `[patch]` A re-install silently did not take effect — `systemctl enable --now` no-ops on an already-active unit, so the documented upgrade path left the old `ExecStart`/env running. Split into `enable` + `restart`, with a source-level test.
  - `[medium]` `[patch]` `render_unit` interpolated raw values into `sed s|…|…|`: a `&`, `|` or backslash in a path/user silently corrupted the unit (`--user 'a&b'` → `User=a@@USER@@b`) and it was installed unchecked. Values are escaped and a surviving `@@…@@` now aborts the render.
  - `[medium]` `[patch]` `--unit-name` was unvalidated and became a root-written path (`../../tmp/evil` → `/tmp/evil.service`); now charset-restricted.
  - `[medium]` `[patch]` `--python`/`--env-file` accepted relative paths that systemd rejects; now absolutised.
  - `[medium]` `[patch]` A missing option value exited 1 silently under `set -e`, and `--user --check` swallowed the next flag; option values are now validated.
  - `[medium]` `[patch]` `--check` green-lit an install that install mode refuses from a linked worktree, while `--uninstall` was blocked by that guard for no reason (the unit lives in `/etc`). Guard moved into preflight; dropped from uninstall.
  - `[medium]` `[patch]` `export KEY=value` and CRLF env files passed preflight but leave systemd's `EnvironmentFile=` variables unset/`\r`-suffixed — a certified-OK install that crash-loops. Both are now preflight failures; inline comments are stripped so `REDIS_PORT=6379 # default` stops warning falsely.
  - `[medium]` `[patch]` No escape hatch existed for hosts configuring the key/DB through `IMOVEIS_<SECTION>__<KEY>` overrides; added `--force` (preflight failures degrade to warnings).
  - `[medium]` `[patch]` The installer reported "installed and started" for a permanently crash-looping unit, and `--status` exited 0 when the unit was never installed — the exact DW-27 state reading as benign. Added a post-restart liveness check with a journal tail, and a non-zero `--status`.
  - `[medium]` `[patch]` A unit test invoked real install mode, with only the worktree guard between pytest and `sudo install` + `systemctl`; stub `sudo`/`systemctl` with marker assertions now make a guard regression fail the test instead of mutating the host.
  - `[low]` `[patch]` `resolve_timeout_stop` grepped the first `lease_ttl_seconds:` anywhere in the config while its test read the scoped `backfill.` key; the extraction is now scoped to the `backfill:` block.
  - `[low]` `[patch]` `ExecStart` rendered a relative script path against the spec's absolute one; now absolute, with the path pin asserting it.
  - `[low]` `[patch]` `--help` printed source code (hardcoded `sed -n '2,30p'` past the header); now delimiter-derived.
  - `[low]` `[patch]` ANSI colour was emitted even when stderr is not a TTY.
  - `[low]` `[patch]` Added `Environment=PYTHONUNBUFFERED=1` so the supervisor's progress reaches journald promptly.
  - `[low]` `[patch]` Preflight asserted `DATABASE_URL` presence but not the failure it exists to prevent; it now warns when the URL's database component is the config default `imoveis` (never echoing the value).
  - `[low]` `[patch]` ADR 0006 and the feature doc claimed `--status` reports a wedged-but-active supervisor; it reads neither Redis nor the lease. Wording corrected in both, plus section-aware directive assertions, hermetic `--env-file` in every test, coverage for `--help`/`--status`/invalid `--unit-name`/`--force`, and `deploy/` added to the repository map in `CLAUDE.md` and its Cursor mirror.

## Design Notes

Systemd over a compose service: the runner needs a cloud key that deliberately exists in **no** container today (`scripts/dev/backfill_gemma.py:50-52`), `scripts/` is not copied into `Dockerfile.worker`, and starting a compose service is a compose action against the inviolable primary project. Systemd also keeps the proven host-side placement (repo `.venv`, `data/images` cache, published ports) unchanged. Promotion out of `scripts/dev` is a separate refactor (2117 lines, 85 CLI tests) that would not by itself supervise anything — the committed unit plus a test pinning the `ExecStart` target is what actually stops the path from silently moving.

Rendered unit shape (abridged):

```ini
[Service]
User=felipe
WorkingDirectory=/home/felipe/workfolder/imoveis
EnvironmentFile=/home/felipe/workfolder/imoveis/.env.local
ExecStart=/home/felipe/workfolder/imoveis/.venv/bin/python /home/felipe/workfolder/imoveis/scripts/dev/backfill_gemma.py --serve
Restart=always
RestartSec=10
StartLimitIntervalSec=0
KillSignal=SIGTERM
TimeoutStopSec=900
```

`After=network-online.target docker.service` orders boot behind the stack without `Requires=` (Docker Desktop hosts have no `docker.service`, and the supervisor's own poll loop already retries Redis failures).

## Verification

**Commands:**
- `bash scripts/install-backfill-runner.sh --print --user u --python /tmp/py --env-file /tmp/env` -- expected: a complete unit on stdout, exit 0, no `@@` placeholders.
- `bash scripts/agent/validate.sh fast` -- expected: lint + unit green, including the new hosting tests.
- `bash scripts/agent/validate.sh all` -- expected: full gate green (run by `finish-feature.sh`).

**Manual checks (if no CLI):**
- The privileged path (`sudo systemctl enable --now imoveis-backfill-serve`) is an operator action; the agent verifies only the rendered artifact and the preflight branches.

## Auto Run Result

**Status:** `awaiting-operator` — every part an agent can do is implemented, reviewed, patched, validated and committed. What remains is privileged and off-repo (see frontmatter `operator_actions`).

**Implemented change.** The cloud backfill supervisor gets a committed, supervised home (DW-27 / FR-28's unmet outcome): a systemd unit template plus an operator installer that renders it for the host, preflights the runner's env contract, and installs/enables/restarts/uninstalls it. The runner itself — `scripts/dev/backfill_gemma.py --serve`, `src/core/backfill_runner.py`, `src/api/admin.py` — is untouched: no behaviour, wire contract or domain change. The topology choice is recorded in ADR 0006 with the two rejected alternatives.

**Files changed**
- `deploy/systemd/imoveis-backfill-serve.service.in` — new committed unit template (drain-safe `TimeoutStopSec` ≥ lease TTL, `StartLimitIntervalSec=0`, `After=` without `Requires=`, `EnvironmentFile` for env-only secrets).
- `scripts/install-backfill-runner.sh` — new operator installer: `--print` / `--check` / install / `--uninstall` / `--status` / `--force`, with preflight, a linked-worktree refusal, and no container-stack action of any kind.
- `src/tests/unit/test_backfill_runner_hosting.py` — new; 35 hermetic tests over the rendered unit, the preflight branches and the install guards (stubbed `sudo`/`systemctl`, no privileged side effects).
- `.env.local.example` — documents the runner's env contract (`GEMINI_API_KEY`, `DATABASE_URL`, `REDIS_URL`) — names and placeholder shapes only.
- `docs/adr/0006-backfill-runner-hosting.md` + `mkdocs.yml` — the decision and its nav entry.
- `docs/features/v0.13-s3.1-backfill-runner-hosting.md`, `docs/setup.md`, `docs/deployment-guide.md`, `docs/features/v0.13-s1.5-admin-backfill-control-api.md` — operator install/upgrade/uninstall step, env contract, cloud-routing precondition, and a supersession pointer on story 1.5's inline example.
- `CLAUDE.md` (+ the git-ignored `.cursor/rules/imoveis-core.mdc` mirror in the primary checkout) — `deploy/systemd/` added to the repository map.
- `_bmad-output/implementation-artifacts/deferred-work.md` — DW-27 closed; two new entries opened.

**Review findings.** One pass, two independent reviewers: 0 intent gaps, 0 spec defects, **17 patches applied** (1 high, 9 medium, 7 low), **2 deferred**, 6 rejected. The high one mattered: `systemctl enable --now` no-ops on a running unit, so the documented "re-run the installer to upgrade" path silently kept the old `ExecStart` alive.

**Verification.** `bash scripts/agent/validate.sh fast` green (lint + 1936 passed, 1 skipped). The installer was exercised directly: `--print` renders a complete unit with no surviving placeholder and no echoed secret; `--check` correctly refuses from this linked worktree and passes under `--force`; `--help` no longer leaks source; a `&`-bearing value renders literally. `validate.sh all` runs at the finish gate.

**Residual risks.**
- The privileged half is unexecuted by construction: the actual install, `runner_present` going true from a real Start press, and reboot recovery are operator-verified, not agent-verified.
- A stock `configs/app_config.yaml` still routes everything to Ollama, so an install before the routing change yields a 10s crash loop — warned at install time, stated in the ADR and the feature doc, and tracked as a deferred item together with DW-28.
- The installed unit is rendered once and does not track later config or path changes.

## Operator Confirmation

Confirmed 2026-08-12: the external actions this story owed were carried out.

- Add GEMINI_API_KEY and DATABASE_URL to .env.local in the primary checkout (/home/felipe/workfolder/imoveis), plus REDIS_URL whenever REDIS_PORT is not 6379; point DATABASE_URL at the primary realestate database on the published POSTGRES_PORT, use plain KEY=value lines with no export prefix and LF endings, and never commit the file.
- Set the backfill task classes in configs/app_config.yaml ai.enrichment_routing (visual, sentiment, deal_verdict) to gemma before installing — with the shipped all-ollama default the supervisor exits at startup and the unit restarts every 10 seconds.
- Stop any hand-started `scripts/dev/backfill_gemma.py --serve` process (tmux/nohup) and remove any previously hand-installed imoveis-backfill-serve.service, so exactly one supervisor beats backfill:gemma:supervisor:active.
- From the primary checkout (never a linked worktree) run `bash scripts/install-backfill-runner.sh --check`, resolve anything it reports, then run `bash scripts/install-backfill-runner.sh` and approve the sudo prompt — it writes /etc/systemd/system/imoveis-backfill-serve.service, enables it and restarts it.
- Verify the supervisor is alive with `systemctl status imoveis-backfill-serve` and `journalctl -u imoveis-backfill-serve -n 50`, then press Start on the Operações backfill card and confirm a run begins and the status endpoint reports runner_present true.
- Verify unattended recovery: reboot the host (or run `sudo systemctl restart imoveis-backfill-serve`) and confirm the unit returns active with no manual step and without starting a second run under the shared lease.
- Re-run `bash scripts/install-backfill-runner.sh` after moving the repo, rebuilding .venv, or raising backfill.lease_ttl_seconds — the installed unit is rendered once and does not track those changes.

_Appended by the bmad-loop orchestrator (`bmad-loop confirm`, #335): a human confirmed these external actions out of band, and the story was advanced from `awaiting-operator` to `done`._
