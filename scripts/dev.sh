#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# dev.sh
#
# Start the full backend stack + frontend dev server (hot-reload) in the
# foreground. Prefer this when you want Vite logs attached to the terminal.
#
# `./scripts/start.sh` / `restart.sh` already background Vite for a
# detached full stack; this script stops any background Vite first so the
# port is free, then runs it in the foreground.
#
# Ctrl+C will stop the frontend dev server. The backend containers keep
# running in the background — use `./scripts/stop.sh` to stop them.
# ---------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"
require_docker

# Free :FRONTEND_PORT if start.sh left a background Vite running.
stop_frontend_dev

log "Starting backend stack (frontend will run in this terminal)..."
"$HERE/start.sh" --no-frontend

if [ -d "$HERE/../frontend" ]; then
  if [ -f "$REPO_ROOT/.env.local" ]; then
    set -a; source "$REPO_ROOT/.env.local"; set +a
  fi
  export FRONTEND_PORT="${FRONTEND_PORT:-5173}"
  export API_PORT="${API_PORT:-8000}"
  log "Starting frontend dev server on :$FRONTEND_PORT ..."
  (cd "$HERE/../frontend" && npm run dev)
else
  warn "No frontend/ directory found — backend-only mode."
fi
