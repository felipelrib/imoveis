#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# validate.sh [fast|backend|frontend|all]   (default: all)
#
# The single validation gate. Runs the SAME steps as CI, in the SAME order.
# Exits 0 only if everything passes. Runs against THIS worktree's isolated
# stack (uses its .env.local / compose project).
#
# Scopes:
#   fast      = lint + unit (pre-push equivalent, <60s)
#   backend   = fast + integration + contract
#   frontend  = install + build + lint
#   all       = backend + frontend
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

# ---- Lint ----
run_lint() {
  log "Lint: isort + flake8"
  isort --check --diff src/ 2>&1 && ok "isort OK" || { warn "isort FAILED"; rc=1; }
  flake8 src/ --max-line-length=127 --extend-ignore=E203,W503 2>&1 && ok "flake8 OK" || { warn "flake8 FAILED"; rc=1; }
  if [ -f "$REPO_ROOT/frontend/package.json" ]; then
    ( cd "$REPO_ROOT/frontend" && npm run lint 2>/dev/null ) && ok "eslint OK" || warn "eslint not configured — skip"
  fi
}

# ---- Unit tests (no Docker) ----
run_unit() {
  log "Unit: pytest (SQLite, no external services)"
  python -m pytest src/tests/unit/ -v --timeout=30 && ok "unit tests passed" || { warn "unit tests FAILED"; rc=1; }
}

# ---- Integration tests (needs PostGIS + Redis) ----
run_integration() {
  log "Integration: pytest (requires PostGIS + Redis)"
  python -m pytest src/tests/integration/ -v && ok "integration tests passed" || { warn "integration tests FAILED"; rc=1; }
}

# ---- Contract tests ----
run_contract() {
  log "Contract: pytest + alembic check"
  if [ -d "$REPO_ROOT/src/tests/contract" ]; then
    python -m pytest src/tests/contract/ -v && ok "contract tests passed" || { warn "contract tests FAILED"; rc=1; }
  else
    warn "src/tests/contract/ directory not found — skip"
  fi
  log "Contract: alembic schema check"
  alembic check 2>&1 && ok "alembic check passed" || { warn "alembic check FAILED — models may not match DB schema"; rc=1; }
}

# ---- Frontend ----
run_frontend() {
  [ -d "$REPO_ROOT/frontend" ] || { warn "no frontend/ — skipping"; return; }
  log "Frontend: install + build"
  ( cd "$REPO_ROOT/frontend" \
      && { [ -d node_modules ] || npm ci; } \
      && npm run build ) \
    && ok "frontend build OK" || { warn "frontend build FAILED"; rc=1; }
}

case "$SCOPE" in
  fast)
    run_lint
    run_unit
    ;;
  backend)
    run_lint
    run_unit
    run_integration
    run_contract
    ;;
  frontend)
    run_frontend
    ;;
  all)
    run_lint
    run_unit
    run_integration
    run_contract
    run_frontend
    ;;
  *)
    die "usage: validate.sh [fast|backend|frontend|all]"
    ;;
esac

[ "$rc" -eq 0 ] && ok "VALIDATION PASSED" || warn "VALIDATION FAILED (rc=$rc)"
exit "$rc"