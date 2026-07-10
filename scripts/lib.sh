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
