#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# setup.sh
#
# First-time project setup. Idempotent — safe to run multiple times.
#
# Steps:
#   1. Check prerequisites (Docker)
#   2. Create .env.local from template (if missing)
#   3. Build and start the Docker stack
#   4. Run database migrations
#   5. Install frontend dependencies
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

# --- Step 2-4: Build and start the stack (includes migrations) ---------------
log "Building and starting the stack..."
"$HERE/start.sh"

# --- Step 5: Frontend dependencies -------------------------------------------
if [ -d "$REPO_ROOT/frontend" ]; then
  log "Installing frontend dependencies..."
  if [ ! -d "$REPO_ROOT/frontend/node_modules" ]; then
    (cd "$REPO_ROOT/frontend" && npm install) && ok "Frontend dependencies installed"
  else
    ok "Frontend dependencies already installed — skipping"
  fi
fi

# --- Done --------------------------------------------------------------------
echo ""
ok "Setup complete!"
echo ""
echo "  API:        http://localhost:${API_PORT:-8000}"
echo "  Frontend:   http://localhost:${FRONTEND_PORT:-5173}"
echo "  API docs:   http://localhost:${API_PORT:-8000}/docs"
echo ""
echo "  Start:  ./scripts/start.sh"
echo "  Stop:   ./scripts/stop.sh"
echo "  Test:   ./scripts/test.sh"
echo ""
