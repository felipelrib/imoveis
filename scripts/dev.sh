#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# dev.sh
#
# Start the full backend stack + frontend dev server (hot-reload).
# This is the typical "day-to-day" command for frontend development.
#
# Ctrl+C will stop the frontend dev server. The backend containers keep
# running in the background — use `./scripts/stop.sh` to stop them.
# ---------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"
require_docker

log "Starting backend stack..."
"$HERE/start.sh"

if [ -d "$HERE/../frontend" ]; then
  log "Starting frontend dev server..."
  (cd "$HERE/../frontend" && npm run dev)
else
  warn "No frontend/ directory found — backend-only mode."
fi