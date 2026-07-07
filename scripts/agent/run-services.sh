#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run-services.sh [service ...]
#
# Brings up this worktree's stack on its private ports, isolated from every
# other worktree via COMPOSE_PROJECT_NAME. With no args, starts the full stack
# (postgres, redis, api, workers) and runs migrations. Pass specific service
# names to start only part of it (e.g. `run-services.sh postgres redis`).
#
# Must be run from INSIDE a worktree that has a .env.local.
# ---------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

[ -f "$REPO_ROOT/.env.local" ] || die "no .env.local here — run setup-worktree.sh first, then cd into the worktree"
set -a; source "$REPO_ROOT/.env.local"; set +a
[ -n "${COMPOSE_PROJECT_NAME:-}" ] || die ".env.local missing COMPOSE_PROJECT_NAME"

cd "$REPO_ROOT"
COMPOSE=(dc --env-file .env.local -p "$COMPOSE_PROJECT_NAME")

log "Starting stack for project '$COMPOSE_PROJECT_NAME' (api :$API_PORT, pg :$POSTGRES_PORT, redis :$REDIS_PORT)"

if [ $# -eq 0 ]; then
  "${COMPOSE[@]}" up -d --build
else
  "${COMPOSE[@]}" up -d --build "$@"
fi

# Wait for postgres health, then migrate (best-effort; a feature may add migrations).
log "Waiting for PostgreSQL to be healthy..."
for i in $(seq 1 30); do
  if "${COMPOSE[@]}" ps postgres 2>/dev/null | grep -qi healthy; then ok "PostgreSQL healthy"; break; fi
  sleep 3
  [ "$i" -eq 30 ] && warn "PostgreSQL not healthy after 90s — continuing anyway"
done

if "${COMPOSE[@]}" ps --services 2>/dev/null | grep -qx api; then
  log "Applying Alembic migrations..."
  "${COMPOSE[@]}" run --rm api python -m alembic upgrade head && ok "migrations applied" || warn "alembic failed (may be expected pre-feature)"

  log "Waiting for API health on :$API_PORT ..."
  for i in $(seq 1 20); do
    if curl -fsS "http://localhost:$API_PORT/health" >/dev/null 2>&1; then ok "API healthy at http://localhost:$API_PORT"; break; fi
    sleep 3
    [ "$i" -eq 20 ] && warn "API /health not responding after 60s"
  done
fi

ok "stack up. Frontend (if running): http://localhost:$FRONTEND_PORT | API: http://localhost:$API_PORT"
