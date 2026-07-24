#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# setup.sh
#
# First-time project setup. Idempotent — safe to run multiple times.
#
# Steps:
#   1. Check prerequisites (Docker)
#   2. Create .env.local from template (if missing)
#   3. Install frontend dependencies
#   4. Build and start the Docker stack + background Vite
#   5. Run database migrations (via start.sh)
# ---------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"
require_docker

cd "$REPO_ROOT"

# --- Step 1: Create .env.local from template --------------------------------
if [ ! -f "$REPO_ROOT/.env.local" ]; then
  log "Creating .env.local from template..."
  cp "$REPO_ROOT/.env.local.example" "$REPO_ROOT/.env.local"
  ok ".env.local created with default ports"
else
  ok ".env.local already exists — skipping"
fi

# --- Step 2: Frontend dependencies (before start.sh backgrounds Vite) ------
if [ -d "$REPO_ROOT/frontend" ]; then
  log "Installing frontend dependencies..."
  if [ ! -d "$REPO_ROOT/frontend/node_modules" ]; then
    (cd "$REPO_ROOT/frontend" && npm install) && ok "Frontend dependencies installed"
  else
    ok "Frontend dependencies already installed — skipping"
  fi
fi

# --- Step 3-5: Build and start the stack (includes migrations + Vite) ------
log "Building and starting the stack..."
"$HERE/start.sh"

# --- Done --------------------------------------------------------------------
echo ""
ok "Setup complete!"
echo ""
echo "  API:        http://localhost:${API_PORT:-8000}"
echo "  Frontend:   http://localhost:${FRONTEND_PORT:-5173}"
echo "  API docs:   http://localhost:${API_PORT:-8000}/docs"
echo ""
echo "  Next:"
echo "    1. Ensure API_KEY is set in .env.local (template default: local-dev-api-key)"
echo "    2. ./scripts/restart.sh   # if you just added/changed API_KEY (restarts Vite too)"
echo "    3. Open the Frontend URL above and paste that API_KEY into \"API credential\""
echo "    4. Optional: ./scripts/dev.sh  # same stack, Vite in the foreground"
echo ""
echo "  Stop:   ./scripts/stop.sh"
echo "  Test:   ./scripts/test.sh"
echo ""
