#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# validate.sh [backend|frontend|all]   (default: all)
#
# The single validation gate. Exits 0 only if everything passes, so it can be
# used directly as a recipe `retry.checks` command. Runs against THIS worktree's
# isolated stack (uses its .env.local / compose project).
# ---------------------------------------------------------------------------
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

SCOPE="${1:-all}"
[ -f "$REPO_ROOT/.env.local" ] && { set -a; source "$REPO_ROOT/.env.local"; set +a; }
cd "$REPO_ROOT"
PROJ="${COMPOSE_PROJECT_NAME:-imoveis}"
COMPOSE=(dc --env-file .env.local -p "$PROJ")
[ -f "$REPO_ROOT/.env.local" ] || COMPOSE=(dc -p "$PROJ")

rc=0

run_backend() {
  log "Backend: pytest (inside api container)"
  if "${COMPOSE[@]}" run --rm api python -m pytest; then
    ok "backend tests passed"
  else
    warn "backend tests FAILED"; rc=1
  fi

  if [ -n "${API_PORT:-}" ]; then
    log "Backend: /health smoke check on :$API_PORT"
    if curl -fsS "http://localhost:$API_PORT/health" >/dev/null 2>&1; then
      ok "API /health OK"
    else
      warn "API /health did not respond (is the stack up? run-services.sh)"; rc=1
    fi
  fi
}

run_frontend() {
  [ -d "$REPO_ROOT/frontend" ] || { warn "no frontend/ — skipping"; return; }
  log "Frontend: install + build"
  ( cd "$REPO_ROOT/frontend" \
      && { [ -d node_modules ] || npm ci; } \
      && npm run build ) \
    && ok "frontend build OK" || { warn "frontend build FAILED"; rc=1; }
}

case "$SCOPE" in
  backend)  run_backend ;;
  frontend) run_frontend ;;
  all)      run_backend; run_frontend ;;
  *) die "usage: validate.sh [backend|frontend|all]" ;;
esac

[ "$rc" -eq 0 ] && ok "VALIDATION PASSED" || warn "VALIDATION FAILED (rc=$rc)"
exit "$rc"
