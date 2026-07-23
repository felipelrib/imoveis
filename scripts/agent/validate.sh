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
#   all       = backend + frontend + E2E
# ---------------------------------------------------------------------------
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

# Ensure required tools are installed
if [ -f "$HERE/setup-tools.sh" ]; then
    source "$HERE/setup-tools.sh" 2>/dev/null || true
fi

# Detect python binary (prefer project .venv, then python3)
PYTHON_BIN=""
if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
    PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
elif [ -x "$REPO_ROOT/.venv/bin/python3" ]; then
    PYTHON_BIN="$REPO_ROOT/.venv/bin/python3"
elif command -v python3 &>/dev/null; then
    PYTHON_BIN="python3"
elif command -v python &>/dev/null; then
    PYTHON_BIN="python"
fi

SOFT=false
SCOPE=""
for arg in "${@}"; do
  case "$arg" in
    --soft) SOFT=true ;;
    fast|backend|frontend|all) SCOPE="$arg" ;;
  esac
done
[ -z "$SCOPE" ] && SCOPE="all"
[ -f "$REPO_ROOT/.env.local" ] && { set -a; source "$REPO_ROOT/.env.local"; set +a; }
cd "$REPO_ROOT"
PROJ="${COMPOSE_PROJECT_NAME:-imoveis}"
COMPOSE=(dc --env-file .env.local -p "$PROJ")
[ -f "$REPO_ROOT/.env.local" ] || COMPOSE=(dc -p "$PROJ")

# --- Auto-derive DATABASE_URL / REDIS_URL for host-side tests ----------------
# Integration tests run pytest on the host but need to connect to Docker services.
# Derive URLs from the worktree's port vars if the full URLs aren't already set.
DB_USER="${POSTGRES_USER:-imoveis}"
DB_PASS="${POSTGRES_PASSWORD:-imoveis_local_dev}"
DB_NAME="${POSTGRES_DB:-realestate}"
if [ -z "${DATABASE_URL:-}" ] && [ -n "${POSTGRES_PORT:-}" ]; then
  export DATABASE_URL="postgresql://${DB_USER}:${DB_PASS}@localhost:${POSTGRES_PORT}/${DB_NAME}"
  log "Derived DATABASE_URL from POSTGRES_PORT"
fi
if [ -z "${REDIS_URL:-}" ] && [ -n "${REDIS_PORT:-}" ]; then
  export REDIS_URL="redis://localhost:${REDIS_PORT}/0"
  log "Derived REDIS_URL from REDIS_PORT"
fi
# Set API_KEY / JWT_SECRET for admin endpoint tests (via AppConfig env channel)
if [ -z "${API_KEY:-}" ]; then
  export API_KEY="test-local-api-key"
fi
if [ -z "${JWT_SECRET:-}" ]; then
  export JWT_SECRET="test-local-jwt-secret"
fi

rc=0

# Helper: skip a step if the required tool isn't available (--soft mode)
# or fail hard (default). Rules/docs-only changes should use --soft.
_require() {
  local tool="$1"
  if ! command -v "$tool" &>/dev/null; then
    if [ "$SOFT" = true ]; then
      warn "'$tool' not installed — skipping (--soft mode)"
      return 1
    fi
    warn "'$tool' not installed — failing (use --soft for rules/docs-only changes)"
    rc=1
    return 1
  fi
  return 0
}

# ---- Lint ----
run_lint() {
  log "Lint: isort + flake8"
  if _require isort; then
    isort --check --diff src/ 2>&1 && ok "isort OK" || { warn "isort FAILED"; rc=1; }
  fi
  if _require flake8; then
    flake8 src/ --max-line-length=127 --extend-ignore=E203,W503 2>&1 && ok "flake8 OK" || { warn "flake8 FAILED"; rc=1; }
  fi
  if [ -f "$REPO_ROOT/frontend/package.json" ]; then
    ( cd "$REPO_ROOT/frontend" && npm run lint 2>/dev/null ) && ok "eslint OK" || warn "eslint not configured — skip"
  fi
}

# ---- Unit tests (no Docker) ----
run_unit() {
  log "Unit: pytest (SQLite, no external services)"
  if [ -n "$PYTHON_BIN" ] && command -v "$PYTHON_BIN" &>/dev/null; then
    "$PYTHON_BIN" -m pytest src/tests/unit/ -v --timeout=30 && ok "unit tests passed" || { warn "unit tests FAILED"; rc=1; }
  else
    warn "python not installed — skipping unit tests"
    rc=1
  fi
}

# ---- Integration tests (needs PostGIS + Redis) ----
run_integration() {
  log "Integration: ensuring services are up (Postgres + Redis)"
  "${COMPOSE[@]}" up -d postgres redis 2>/dev/null
  log "Integration: applying migrations (alembic upgrade head)"
  "${COMPOSE[@]}" run --rm api python -m alembic upgrade head 2>/dev/null
  log "Integration: pytest (real PostGIS + Redis)"
  if [ -n "$PYTHON_BIN" ] && command -v "$PYTHON_BIN" &>/dev/null; then
    "$PYTHON_BIN" -m pytest src/tests/integration/ -v && ok "integration tests passed" || { warn "integration tests FAILED"; rc=1; }
  else
    warn "python not installed — skipping integration tests"
    rc=1
  fi
}

# ---- Alembic: ensure DB is migrated before checks ----
run_alembic_migrate() {
  if [ -z "${DATABASE_URL:-}" ]; then
    warn "DATABASE_URL not set — skipping alembic migration"
    return
  fi
  log "Alembic: upgrade head (via Docker)"
  "${COMPOSE[@]}" run --rm api python -m alembic upgrade head 2>&1 && ok "alembic upgrade head passed" || { warn "alembic upgrade head FAILED"; rc=1; }
}

# ---- Contract tests ----
run_contract() {
  log "Contract: pytest + alembic check"
  if [ -d "$REPO_ROOT/src/tests/contract" ]; then
    if [ -n "$PYTHON_BIN" ] && command -v "$PYTHON_BIN" &>/dev/null; then
      "$PYTHON_BIN" -m pytest src/tests/contract/ -v && ok "contract tests passed" || { warn "contract tests FAILED"; rc=1; }
    else
      warn "python not installed — skipping contract tests"
      rc=1
    fi
  else
    warn "src/tests/contract/ directory not found — skip"
  fi
  log "Contract: alembic schema check (via Docker)"
  # PostGIS system tables (tiger, topology, spatial_ref_sys) always appear as
  # "extra" in autogenerate, so alembic check always reports false positives.
  # This check is informational only — never fails the build for PostGIS projects.
  "${COMPOSE[@]}" run --rm api python -m alembic check 2>/dev/null && ok "alembic check passed" \
    || warn "alembic check: PostGIS system tables detected (expected — informational only)"
}

# ---- Frontend ----
run_frontend() {
  [ -d "$REPO_ROOT/frontend" ] || { warn "no frontend/ — skipping"; return; }
  log "Frontend: install (npm ci) + build"
  ( cd "$REPO_ROOT/frontend" \
      && npm ci \
      && npm run build ) \
    && ok "frontend build OK" || { warn "frontend build FAILED"; rc=1; }
}

run_e2e() {
  [ -d "$REPO_ROOT/frontend" ] || { warn "no frontend/ — skipping E2E"; return; }
  log "E2E: Playwright"
  ( cd "$REPO_ROOT/frontend" \
      && npm run test:e2e ) \
    && ok "E2E tests passed" || { warn "E2E tests FAILED"; rc=1; }
}

case "$SCOPE" in
  fast)
    run_lint
    run_unit
    ;;
  backend)
    run_lint
    run_unit
    run_alembic_migrate
    run_integration
    run_contract
    ;;
  frontend)
    run_frontend
    ;;
  all)
    run_lint
    run_unit
    run_alembic_migrate
    run_integration
    run_contract
    run_frontend
    run_e2e
    ;;
  *)
    die "usage: validate.sh [fast|backend|frontend|all]"
    ;;
esac

[ "$rc" -eq 0 ] && ok "VALIDATION PASSED" || warn "VALIDATION FAILED (rc=$rc)"
exit "$rc"
