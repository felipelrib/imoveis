#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# migrate-primary.sh [--dry-run]
#
# EXPLICIT OPERATOR STEP: migrate the PRIMARY `realestate` database
# (alembic upgrade head). This is the ONLY sanctioned path for primary
# migration — validate.sh/finish-feature.sh never touch the primary stack.
#
# Backfill guard: refuses while the backfill runner's TTL'd heartbeat
# (`backfill:gemma:active`, refreshed while the runner is alive, TTL ~300s)
# exists in the primary Redis. The guard keys off the LIVE heartbeat only —
# leftover `backfill:gemma:*` pacer/checkpoint state never blocks. Absent
# heartbeat ⇒ the check passes in milliseconds; the key self-clears, never
# remove it manually.
#
# Runs host-side (alembic via .venv) against the primary DB URL — it migrates
# schema but never creates/stops/restarts containers.
# ---------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

DRY_RUN=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    *) die "Unknown flag: $arg. Usage: migrate-primary.sh [--dry-run]" ;;
  esac
done

cd "$REPO_ROOT"
[ -f "$REPO_ROOT/.env.local" ] && { set -a; # shellcheck disable=SC1091
  source "$REPO_ROOT/.env.local"; set +a; }

# This script targets the PRIMARY stack by definition — refuse to run from a
# worktree whose .env.local re-points ports at an isolated stack (the heartbeat
# check and the migration would silently target the wrong servers).
PRIMARY_COMPOSE_PROJECT="${PRIMARY_COMPOSE_PROJECT:-imoveis}"
if [ -f "$REPO_ROOT/.env.local" ]; then
  _proj="$(awk -F= '/^(export[[:space:]]+)?COMPOSE_PROJECT_NAME=/{v=$2; gsub(/["'\''[:space:]]/,"",v); print v; exit}' "$REPO_ROOT/.env.local")"
  if [ -n "$_proj" ] && [ "$_proj" != "$PRIMARY_COMPOSE_PROJECT" ]; then
    die "this checkout's .env.local names project '$_proj', not the primary '$PRIMARY_COMPOSE_PROJECT' — run migrate-primary.sh from the primary checkout"
  fi
fi

DB_USER="${POSTGRES_USER:-imoveis}"
DB_PASS="${POSTGRES_PASSWORD:-imoveis_local_dev}"
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"
PRIMARY_DB="${POSTGRES_DB:-realestate}"
PRIMARY_DB_URL="postgresql://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${PRIMARY_DB}"
REDIS_HOST="localhost"
REDIS_PRIMARY_PORT="${REDIS_PORT:-6379}"
HEARTBEAT_KEY="backfill:gemma:active"

PYTHON_BIN=""
if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
elif command -v python3 &>/dev/null; then
  PYTHON_BIN="python3"
else
  die "python3 required"
fi

log "Backfill heartbeat guard: checking ${HEARTBEAT_KEY} on primary Redis (${REDIS_HOST}:${REDIS_PRIMARY_PORT})..."
HB_STATE="$(
  REDIS_HOST="$REDIS_HOST" REDIS_PRIMARY_PORT="$REDIS_PRIMARY_PORT" HEARTBEAT_KEY="$HEARTBEAT_KEY" \
  "$PYTHON_BIN" - <<'PY'
import os
try:
    import redis
    r = redis.Redis(host=os.environ["REDIS_HOST"], port=int(os.environ["REDIS_PRIMARY_PORT"]), db=0,
                    socket_connect_timeout=3)
    print("alive" if r.exists(os.environ["HEARTBEAT_KEY"]) else "idle")
except Exception as exc:  # Redis unreachable → cannot prove idle → fail closed
    print(f"unknown:{exc}")
PY
)"

case "$HB_STATE" in
  idle)
    ok "no live backfill heartbeat — safe to migrate"
    ;;
  alive)
    die "backfill heartbeat is ALIVE — a runner is writing to the primary DB. Wait for it to finish (the key self-clears within its TTL) and re-run."
    ;;
  *)
    die "could not check the backfill heartbeat (${HB_STATE#unknown:}) — refusing to migrate without proof the primary is idle (fail closed). Is the primary Redis up?"
    ;;
esac

if [ "$DRY_RUN" = true ]; then
  log "DRY RUN — would run: alembic upgrade head against ${PRIMARY_DB} (port ${DB_PORT})"
  exit 0
fi

log "Migrating PRIMARY ${PRIMARY_DB} (alembic upgrade head, host-side)..."
DATABASE_URL="$PRIMARY_DB_URL" PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:$PYTHONPATH}" \
  "$PYTHON_BIN" -m alembic upgrade head
ok "primary ${PRIMARY_DB} migrated to head"
