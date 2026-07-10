#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# start.sh [service ...]
#
# Start the development stack. With no arguments, starts the full stack
# (postgres, redis, api, workers) and runs migrations. Pass specific service
# names to start only part of it (e.g. `./scripts/start.sh postgres redis`).
#
# Uses .env.local if present (for worktree-isolated ports), otherwise falls
# back to default ports (5432, 6379, 8000, 5173).
# ---------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"
require_docker

cd "$REPO_ROOT"

# Load .env.local if present
if [ -f "$REPO_ROOT/.env.local" ]; then
  set -a; source "$REPO_ROOT/.env.local"; set +a
fi

API_PORT="${API_PORT:-8000}"

log "Starting stack (project '$COMPOSE_PROJECT_NAME')"

if [ $# -eq 0 ]; then
  compose_cmd up -d --build
else
  compose_cmd up -d --build "$@"
fi

# Wait for postgres health
log "Waiting for PostgreSQL to be healthy..."
for i in $(seq 1 30); do
  if compose_cmd ps postgres 2>/dev/null | grep -qi healthy; then
    ok "PostgreSQL healthy"
    break
  fi
  sleep 3
  [ "$i" -eq 30 ] && warn "PostgreSQL not healthy after 90s — continuing anyway"
done

# Run migrations if API service is present
if compose_cmd ps --services 2>/dev/null | grep -qx api; then
  log "Applying Alembic migrations..."
  MIGRATION_OUTPUT="$(compose_cmd run --rm api python -m alembic upgrade head 2>&1)" && rc=0 || rc=$?
  if [ "$rc" -eq 0 ]; then
    ok "migrations applied"
  elif echo "$MIGRATION_OUTPUT" | grep -q "DuplicateTable"; then
    warn "alembic: table already exists — the database schema is ahead of alembic's version tracker."
    warn "  This happens when migrations were applied outside alembic or on a previous setup."
    warn "  Fix: docker compose --env-file .env.local -p $COMPOSE_PROJECT_NAME run --rm api python -m alembic stamp head"
  else
    warn "alembic failed (exit $rc):"
    echo "$MIGRATION_OUTPUT" | tail -5 | while read -r line; do warn "  $line"; done
  fi

  log "Waiting for API health on :$API_PORT ..."
  for i in $(seq 1 20); do
    if curl -fsS "http://localhost:$API_PORT/health" >/dev/null 2>&1; then
      ok "API healthy at http://localhost:$API_PORT"
      break
    fi
    sleep 3
    [ "$i" -eq 20 ] && warn "API /health not responding after 60s"
  done
fi

ok "Stack is up. API: http://localhost:$API_PORT | Frontend: http://localhost:${FRONTEND_PORT:-5173}"
