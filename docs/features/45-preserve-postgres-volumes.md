# preserve-postgres-volumes — Keep local DB durable; stop false-zero property counts

> Feature branch: `feat/bin-60-preserve-postgres-volumes` · Linear: `BIN-60` · Status: implemented

## Problem

Operators saw **Total properties in database** jump or flash to `0` during development.
Two causes stacked:

1. Dev scripts (`clean.sh`, and primary-risk `teardown.sh`) ran `docker compose down -v`,
   wiping the named `postgres_data` volume even for routine cleanup.
2. `GET /system/status` returned `total_properties: 0` whenever the DB health check
   threw — a transient connectivity blip looked like an empty database.

## Approach

- Make volume deletion **opt-in** on `clean.sh` (`--volumes` / nuclear `--all`), matching
  `stop.sh` defaults.
- On primary Compose project (`imoveis`), `teardown.sh` preserves volumes unless
  `--volumes`; worktree projects still wipe their private volumes for isolation.
- On DB errors, return `null` counts (not `0`); Dashboard shows `—` and
  "database unavailable" instead of a false empty count.
- Document that scraped data should live on the primary stack (ADR 0004).

## Changes

Files touched:

```
 scripts/clean.sh                              | Default keeps volumes; --volumes / --all wipe
 scripts/agent/teardown.sh                     | Primary project keeps volumes unless --volumes
 src/api/system.py                             | _check_db_and_counts returns None on error
 frontend/src/pages/Dashboard.jsx              | Em dash when DB unhealthy / counts null
 src/tests/unit/test_system_status_counts.py   | NEW — regression for false-zero
 frontend/tests/e2e/dashboard.spec.js          | E2E regression for unhealthy DB counts
 docs/setup.md / README.md                     | clean.sh docs
 docs/adr/0004-parallel-agent-workspaces.md    | Postgres persistence note
 docs/features/45-preserve-postgres-volumes.md | NEW — this doc
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
```

Manual:

1. Confirm `./scripts/clean.sh` (no flags) leaves `docker volume ls | grep postgres` intact.
2. Stop Postgres briefly and open Dashboard — Total Properties should show `—`, not `0`.

## Notes / Follow-ups

- Pipeline chart history remains client-only until BIN-61 (persistent snapshots).
- Optional later: bind-mount Postgres to `./data/` if named volumes still feel fragile.
