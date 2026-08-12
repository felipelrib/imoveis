# ADR 0006: Backfill Runner Hosting

**Status:** Accepted
**Date:** 2026-08-12
**Related:** [ADR 0002 — Cursor Single-Agent Workflow](0002-cursor-single-agent-workflow.md) · story `v0.13-s3.1` · ledger `DW-27`

## Decision

The cloud backfill supervisor keeps running **host-side, as the operator's own
user, out of the repo `.venv`** — and gets a committed home:

- `deploy/systemd/imoveis-backfill-serve.service.in` — a **systemd system unit
  template** (placeholders for user, repo root, interpreter, env file and stop
  timeout).
- `scripts/install-backfill-runner.sh` — the one supported install path. It
  renders the template for this host, preflights the env contract, and
  installs / enables / uninstalls the unit (`--print`, `--check`, default
  install, `--uninstall`, `--status`).

The unit is `imoveis-backfill-serve.service` — the same name story 1.5's doc
example used — so re-running the installer **upgrades in place** instead of
leaving a second supervisor beating the same heartbeat.

`ExecStart` stays `<python> scripts/dev/backfill_gemma.py --serve`: the runner is
**not** promoted out of `scripts/dev`, and nothing about the runner, the
supervisor loop or the admin API changes.

Cloud credentials are **env-only**: the unit reads the git-ignored
`<repo>/.env.local` via `EnvironmentFile=`. No key value is written into a
committed file, into the rendered unit, or echoed by the installer — the
installer only ever prints variable *names*.

## Context

FR-28 asked for the backfill to become an operator-facing operation. Epic 1
shipped the control plane (`POST /admin/backfill/start`, the Operações card),
but `start` only *records a request*; the thing that consumes it is
`scripts/dev/backfill_gemma.py --serve`, and nothing kept that alive. No unit
was committed, no installer existed, and the only guidance was an example unit
pasted inside a feature doc whose env contract was incomplete: it supplied
neither `DATABASE_URL` (the config default database is `imoveis`, while the
primary stack's is `realestate`) nor `REDIS_URL`, `GEMINI_API_KEY` was absent
from `.env.local.example`, and the default stop timeout could `SIGKILL` a
draining run mid-property. A supervisor that is simply never started leaves a
permanently un-actionable button (DW-27).

Two invariants constrain where the runner may live:

- **Local-first / residential egress (NFR-1).** Scraping and enrichment must
  leave the operator's own residential connection. Hosting must not move the
  runner off-box; a datacenter ASN is not an option.
- **Cloud key placement (NFR-3).** `GEMINI_API_KEY` deliberately exists in **no**
  container today. Every service in `docker-compose.yml` runs without it.

Systemd satisfies both: it supervises a process already running in exactly the
place it runs today (repo `.venv`, host image cache, the primary stack's
*published* ports), and it feeds the key from a git-ignored file that never
enters an image or a compose environment.

## Consequences

- **A one-time operator step.** `bash scripts/install-backfill-runner.sh` needs
  `sudo` (it writes `/etc/systemd/system` and calls `systemctl`). No agent, gate
  or script runs it; `validate.sh` and `finish-feature.sh` are untouched.
- **Upgrades re-run the installer.** A repo move, a rebuilt `.venv` or a changed
  env-file path all change rendered content — re-running rewrites the same unit
  name and reloads systemd.
- **Reboot and crash recovery are unattended** (AD-13 / NFR-6): `Restart=always`,
  `RestartSec=10`, `StartLimitIntervalSec=0` (a restart limit must never strand
  the unit in `failed`), `WantedBy=multi-user.target`.
- **Stops are drain-safe.** `KillSignal=SIGTERM` with `TimeoutStopSec` ≥ the
  900 s lease TTL, so in-flight rows finish rather than being killed half-written.
- **Crash-loop is the symptom of local routing.** `--serve` validates scope, AI
  routing and the cloud key *before* its poll loop and exits when routing is not
  cloud or the key is unset, so an all-local host restarts every 10 s. The
  installer's preflight is what prevents that: it fails on a missing
  `GEMINI_API_KEY`/`DATABASE_URL` and warns when `ai.enrichment_routing` routes
  no task class to `gemma`/`gemini`.
- **`runner_present` is not the unit's state.** The admin API reports it from
  Redis (lease held **or** the `backfill:gemma:supervisor:active` heartbeat), so
  a wedged-but-`active` unit still reads as absent there. `--status` reports the
  *unit's* state only and prints that caveat as a reminder — it reads neither
  Redis nor the lease, and the installer deliberately has no Redis access.
  `--status` does fail (non-zero) when the unit was never installed, which is
  the DW-27 state itself.
- **Uninstall is first-class.** `--uninstall` disables, stops, removes and
  reloads; a missing unit is not an error. A run already in flight keeps its
  lease until it drains.
- **Install refuses from a linked git worktree.** Worktree paths are disposable
  (`teardown.sh --remove`); the refusal names the primary checkout.
- **No compose surface is added**, so `docker-cleanup.sh`'s image filter, the
  primary project's service list and the gates' primary-safety all stand
  unchanged.

## Alternatives considered

1. **A dedicated compose service in the primary project** — rejected. It would
   put `GEMINI_API_KEY` inside a container that deliberately has none, `scripts/`
   is not copied into `Dockerfile.worker` (so the image cannot even run the
   consumer), and starting/stopping it is a compose action against the primary
   project that agents and gates are forbidden to touch. It would also add a
   service, and with it image/cleanup surface, for a process that must stay on
   the residential host anyway.
2. **Promoting `scripts/dev/backfill_gemma.py` into `src/` as a supported
   entrypoint** — rejected for this story. It is a 2117-line surface with 85 CLI
   tests, and the move would supervise nothing by itself: an installed console
   script still needs something to keep it alive. What actually stops the path
   from silently drifting is the committed unit plus a test that pins the
   `ExecStart` target to a file that must exist. A promotion can happen later
   without invalidating this decision — it would change one rendered line.
3. **Hosting the backfill as a Celery task on the existing workers** — rejected.
   The runner is a second *driver* of the enrichment pipeline, not a second
   writer: it deliberately bypasses the `ai` queue and the GPU semaphore (AD-4 /
   AD-10), it holds a lease for hours across a multi-day pass, and it would drag
   the cloud key into the worker image.
4. **Leaving it to `tmux`/`nohup` and documentation** — rejected: that is the
   status quo DW-27 filed. It survives neither a reboot nor an OOM kill, and it
   makes the dashboard's Start button silently do nothing whenever someone
   forgets.
