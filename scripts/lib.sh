#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# scripts/lib.sh — shared helpers for project-level scripts.
#
# Sourced by scripts/*.sh (start, stop, test, etc.). Provides:
# - Docker Compose shim (v2 plugin preferred, v1 fallback)
# - require_docker() guard — bails early with a clear message if Docker isn't accessible
# - Colored logging
# - Project root resolution
# - Compose command builder (respects .env.local if present)
# ---------------------------------------------------------------------------
set -euo pipefail

# --- Resolve project root ---------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Logging ----------------------------------------------------------------
_c() { printf '\033[%sm' "$1"; }
log()   { printf '%s> %s%s\n' "$(_c 36)" "$*" "$(_c 0)"; }
ok()    { printf '%s  [OK] %s%s\n' "$(_c 32)" "$*" "$(_c 0)"; }
warn()  { printf '%s  [WARN] %s%s\n' "$(_c 33)" "$*" "$(_c 0)"; }
die()   { printf '%s  [FAIL] %s%s\n' "$(_c 31)" "$*" "$(_c 0)" >&2; exit 1; }

# --- Docker Compose shim ----------------------------------------------------
dc() {
  if docker compose version >/dev/null 2>&1; then docker compose "$@"
  else docker-compose "$@"
  fi
}

# --- Compose command builder ------------------------------------------------
# Builds the `dc` arguments with the right env file and project name.
# If .env.local exists in REPO_ROOT, uses it; otherwise falls back to defaults.
# Override COMPOSE_PROJECT_NAME before sourcing lib.sh if needed.
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-imoveis}"

compose_cmd() {
  local env_file="$REPO_ROOT/.env.local"
  if [ -f "$env_file" ]; then
    dc --env-file "$env_file" -p "$COMPOSE_PROJECT_NAME" "$@"
  else
    dc -p "$COMPOSE_PROJECT_NAME" "$@"
  fi
}

# --- Docker guard -----------------------------------------------------------
# Call this at the top of any script that needs Docker. Exits early with a
# clear message instead of hanging for 30s+ on a connection timeout.
require_docker() {
  if ! docker info >/dev/null 2>&1; then
    die "Docker is not running or not accessible. Start the Docker daemon first (e.g. 'sudo systemctl start docker' or Docker Desktop)."
  fi
}

# --- Frontend (Vite) lifecycle ----------------------------------------------
# start.sh backgrounds the Vite dev server; stop.sh tears it down.
# Runtime state lives under .run/ (gitignored).
RUN_DIR="${REPO_ROOT}/.run"
FRONTEND_PID_FILE="${RUN_DIR}/frontend.pid"
FRONTEND_LOG_FILE="${RUN_DIR}/frontend.log"

frontend_port() {
  echo "${FRONTEND_PORT:-5173}"
}

frontend_pid_alive() {
  local pid="$1"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

# Returns 0 if a tracked Vite process is still alive.
is_frontend_running() {
  if [ -f "$FRONTEND_PID_FILE" ]; then
    local pid
    pid="$(tr -d '[:space:]' < "$FRONTEND_PID_FILE" || true)"
    if frontend_pid_alive "$pid"; then
      return 0
    fi
    rm -f "$FRONTEND_PID_FILE"
  fi
  return 1
}

# Stop a background Vite started by start_frontend_dev (no-op if none).
stop_frontend_dev() {
  if [ ! -f "$FRONTEND_PID_FILE" ]; then
    return 0
  fi
  local pid
  pid="$(tr -d '[:space:]' < "$FRONTEND_PID_FILE" || true)"
  if frontend_pid_alive "$pid"; then
    log "Stopping frontend dev server (pid $pid)..."
    # Kill the process group so npm + vite children exit together.
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
      frontend_pid_alive "$pid" || break
      sleep 0.25
    done
    if frontend_pid_alive "$pid"; then
      kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
    fi
    ok "Frontend stopped"
  fi
  rm -f "$FRONTEND_PID_FILE"
}

# Background Vite on FRONTEND_PORT (default 5173). Idempotent if already up.
# Skips when frontend/ is missing or node_modules are not installed.
start_frontend_dev() {
  if [ ! -d "$REPO_ROOT/frontend" ]; then
    warn "No frontend/ directory — skipping Vite"
    return 0
  fi
  if [ ! -d "$REPO_ROOT/frontend/node_modules" ]; then
    warn "frontend/node_modules missing — run: (cd frontend && npm install)"
    warn "Skipping Vite (API is up; UI will not be on :$(frontend_port))"
    return 0
  fi
  if is_frontend_running; then
    ok "Frontend already running at http://localhost:$(frontend_port)"
    return 0
  fi

  mkdir -p "$RUN_DIR"
  export FRONTEND_PORT="${FRONTEND_PORT:-5173}"
  export API_PORT="${API_PORT:-8000}"

  log "Starting frontend dev server on :$FRONTEND_PORT ..."
  # setsid gives a fresh process group so stop_frontend_dev can signal the tree.
  (
    cd "$REPO_ROOT/frontend"
    setsid npm run dev >"$FRONTEND_LOG_FILE" 2>&1 &
    echo $! >"$FRONTEND_PID_FILE"
  )

  local pid
  pid="$(tr -d '[:space:]' < "$FRONTEND_PID_FILE" || true)"
  # Wait briefly for Vite to bind (or fail fast with a log hint).
  for i in $(seq 1 40); do
    if ! frontend_pid_alive "$pid"; then
      warn "Frontend exited early — see $FRONTEND_LOG_FILE"
      rm -f "$FRONTEND_PID_FILE"
      return 0
    fi
    if curl -fsS "http://localhost:${FRONTEND_PORT}/" >/dev/null 2>&1; then
      ok "Frontend healthy at http://localhost:${FRONTEND_PORT}"
      return 0
    fi
    sleep 0.25
    if [ "$i" -eq 40 ]; then
      warn "Frontend not responding on :${FRONTEND_PORT} after 10s — see $FRONTEND_LOG_FILE"
    fi
  done
}
