#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# stop.sh
#
# Stop the development stack gracefully (containers are kept so restart is fast).
# Add --volumes to also remove named volumes (postgres_data, redis_data).
# ---------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"
require_docker

cd "$REPO_ROOT"

if [ -f "$REPO_ROOT/.env.local" ]; then
  set -a; source "$REPO_ROOT/.env.local"; set +a
fi

if [ "${1:-}" = "--volumes" ]; then
  log "Stopping stack and removing volumes..."
  compose_cmd down -v
  ok "Stack stopped and volumes removed"
else
  log "Stopping stack..."
  compose_cmd down
  ok "Stack stopped (volumes preserved)"
fi
