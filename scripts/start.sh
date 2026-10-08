#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# start.sh [--no-frontend] [service ...]
#
# Start the development stack. With no arguments, starts the full stack
# (postgres, redis, api, workers) and backgrounds the Vite frontend on
# FRONTEND_PORT (default 5173). Pass specific service names to start only part
# of it (e.g. `./scripts/start.sh postgres redis`).
#
# Database schema (DW-32):
#   - On the PRIMARY compose project (`${PRIMARY_COMPOSE_PROJECT:-imoveis}`,
#     which is also what a checkout with no project name of its own resolves
#     to) this script NEVER changes the schema. It reads the schema state,
#     reports it, and when a migration is pending it names the one command that
#     may apply it: `bash scripts/agent/migrate-primary.sh` — the operator step
#     that holds the migration lock and refuses under a live backfill runner.
#     The stack starts either way; a pending migration is a warning.
#   - On any other (isolated) compose project it migrates that project's own
#     database, as before: such a project owns its own Postgres volume, cannot
#     reach the primary database, and migrate-primary.sh refuses to run there.
#
# --no-frontend  Skip Vite (used by dev.sh, which runs it in the foreground).
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
# The primary project is named the way scripts/agent/migrate-primary.sh names it.
# That script compares the name exactly; this one compares it as Compose resolves
# it (see is_primary_project), which can only make more checkouts primary here.
PRIMARY_COMPOSE_PROJECT="${PRIMARY_COMPOSE_PROJECT:-imoveis}"
START_FRONTEND=1
SERVICES=()

for arg in "$@"; do
  case "$arg" in
    --no-frontend) START_FRONTEND=0 ;;
    # restart.sh may forward --build; start always rebuilds via `up --build`.
    --build) ;;
    *) SERVICES+=("$arg") ;;
  esac
done

# Read-only: compares the database's alembic_version rows with the heads of the
# migration scripts shipped in the api image. Creates nothing and changes
# nothing, whatever it finds. Prints `current`, `pending:<db>-><head>`, or
# `foreign:<db>-><head>` when the database carries a revision these migration
# scripts do not contain (the database is newer than this code, or another
# branch migrated it) — a state no migration from this checkout can fix.
report_primary_schema_state() {
  local state rc
  local pending_re='^pending:([A-Za-z0-9_,]+)->([A-Za-z0-9_,]+)$'
  local foreign_re='^foreign:([A-Za-z0-9_,]+)->([A-Za-z0-9_,]+)$'
  log "Checking the primary schema state (read-only)..."
  state="$(compose_cmd run --rm -T api python - 2>/dev/null <<'PY'
import os

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

cfg = Config("alembic.ini")
script = ScriptDirectory.from_config(cfg)
heads = sorted(script.get_heads())
known = {revision.revision for revision in script.walk_revisions()}
url = os.environ.get("DATABASE_URL") or cfg.get_main_option("sqlalchemy.url")
# Bounds the connection attempt only (an unreachable Postgres); a query that
# stalls after connecting is not bounded here.
connect_args = {"connect_timeout": 10} if url.startswith("postgresql") else {}
with create_engine(url, connect_args=connect_args).connect() as conn:
    if inspect(conn).has_table("alembic_version"):
        rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
        current = sorted(row[0] for row in rows)
    else:
        current = []
if current == heads:
    print("current")
else:
    kind = "foreign" if any(revision not in known for revision in current) else "pending"
    print("%s:%s->%s" % (kind, ",".join(current) or "none", ",".join(heads) or "none"))
PY
  )" && rc=0 || rc=$?
  state="${state//$'\r'/}"
  state="${state##*$'\n'}"

  if [ "$rc" -eq 0 ] && [ "$state" = "current" ]; then
    ok "primary schema is at head — nothing to migrate"
  elif [ "$rc" -eq 0 ] && [[ "$state" =~ $pending_re ]]; then
    warn "primary schema is behind: the database is at ${BASH_REMATCH[1]}, the code expects ${BASH_REMATCH[2]}."
    warn "  start.sh does not migrate the primary database. Run the guarded operator step"
    warn "  from the primary checkout:"
    warn "    bash scripts/agent/migrate-primary.sh"
  elif [ "$rc" -eq 0 ] && [[ "$state" =~ $foreign_re ]]; then
    warn "primary schema does not match this code: the database is at ${BASH_REMATCH[1]}, a revision"
    warn "  this checkout's migrations do not contain (they end at ${BASH_REMATCH[2]})."
    warn "  The database is newer than this code, or another branch migrated it."
    warn "  Nothing was changed, and no migration from this checkout applies."
  else
    warn "primary schema state is unknown (the read-only check did not answer, exit $rc)."
    warn "  start.sh does not migrate the primary database. If a migration is pending, apply it"
    warn "  with the guarded operator step, from the primary checkout:"
    warn "    bash scripts/agent/migrate-primary.sh"
  fi
}

# Compose normalizes project names (the v1 CLI lowercases and drops characters
# outside [a-z0-9_-]), so two spellings can name one project. Compare what
# Compose would use: a primary spelled differently is still the primary.
_normalized_project() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-'
}

# Whether this start targets the primary project. An EMPTY name counts as the
# primary: `docker compose -p ""` falls back to the directory name, which in the
# primary checkout is the primary project, so "not equal to the primary's name"
# would send it to the migrating branch. A project start.sh may migrate has a
# name of its own.
is_primary_project() {
  local project
  project="$(_normalized_project "$COMPOSE_PROJECT_NAME")"
  [ -z "$project" ] || [ "$project" = "$(_normalized_project "$PRIMARY_COMPOSE_PROJECT")" ]
}

# Only ever called for a compose project that is NOT the primary one.
migrate_isolated_project() {
  local output rc
  log "Applying Alembic migrations to the isolated project '$COMPOSE_PROJECT_NAME'..."
  output="$(compose_cmd run --rm api python -m alembic upgrade head 2>&1)" && rc=0 || rc=$?
  if [ "$rc" -eq 0 ]; then
    ok "migrations applied"
  elif echo "$output" | grep -q "DuplicateTable"; then
    warn "alembic: table already exists — the database schema is ahead of alembic's version tracker."
    warn "  This happens when migrations were applied outside alembic or on a previous setup."
  else
    warn "alembic failed (exit $rc):"
    echo "$output" | tail -5 | while read -r line; do warn "  $line"; done
  fi
}

log "Starting stack (project '$COMPOSE_PROJECT_NAME')"

if [ ${#SERVICES[@]} -eq 0 ]; then
  compose_cmd up -d --build
else
  compose_cmd up -d --build "${SERVICES[@]}"
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

# Schema step, only when the API service is present
if compose_cmd ps --services 2>/dev/null | grep -qx api; then
  if is_primary_project; then
    report_primary_schema_state
  else
    migrate_isolated_project
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

# Full-stack start only — not when targeting individual compose services.
if [ "$START_FRONTEND" -eq 1 ] && [ ${#SERVICES[@]} -eq 0 ]; then
  start_frontend_dev
fi

FRONTEND_URL="http://localhost:${FRONTEND_PORT:-5173}"
if is_frontend_running; then
  ok "Stack is up. API: http://localhost:$API_PORT | Frontend: $FRONTEND_URL"
else
  ok "Stack is up. API: http://localhost:$API_PORT"
  if [ "$START_FRONTEND" -eq 1 ] && [ ${#SERVICES[@]} -eq 0 ]; then
    warn "Frontend not running — try: ./scripts/dev.sh  (or check .run/frontend.log)"
  else
    log "Frontend skipped. Day-to-day UI: ./scripts/dev.sh → $FRONTEND_URL"
  fi
fi
