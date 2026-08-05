#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# validate.sh [fast|backend|frontend|all]   (default: all)
#
# The single validation gate — and since CI retirement, THE merge gate.
# Exits 0 only if everything passes.
#
# Primary-stack invariant (CAP-1): this script NEVER touches the primary
# compose project. DB/Redis needs are met by the ephemeral "<workspace>-test"
# stack (scripts/agent/test-stack.sh — docker-assigned ports, throwaway
# volumes). Safe to run at any time, including during a live backfill.
# Primary `realestate` migration is a separate explicit operator step:
# scripts/agent/migrate-primary.sh.
#
# Scopes:
#   fast      = lint (pre-commit, all files) + unit (<60s)
#   backend   = fast + integration + contract
#   frontend  = install + build + lint
#   all       = backend + frontend + E2E
# ---------------------------------------------------------------------------
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

# Project venv tools (pre-commit, alembic, pytest) win over system ones.
if [ -d "$REPO_ROOT/.venv/bin" ]; then
    export PATH="$REPO_ROOT/.venv/bin:$PATH"
fi

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
# .env.local supplies workspace identity + PLAYWRIGHT_PORT; DB/Redis URLs for
# tests are derived from the ephemeral test stack below, never from here.
[ -f "$REPO_ROOT/.env.local" ] && { set -a; source "$REPO_ROOT/.env.local"; set +a; }
cd "$REPO_ROOT"

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

# Bring up the ephemeral test stack and point host pytest at it.
# Integration fixtures truncate all tables — they must NEVER see the primary
# server. Everything below runs against the throwaway "<workspace>-test" stack.
TEST_STACK_READY=false
ensure_test_stack() {
  [ "$TEST_STACK_READY" = true ] && return 0
  log "Ephemeral test stack: up (never the primary project)"
  bash "$HERE/test-stack.sh" up || { warn "test stack failed to start"; rc=1; return 1; }
  local env_out
  env_out="$(bash "$HERE/test-stack.sh" env)" || { warn "test stack env resolution failed"; rc=1; return 1; }
  eval "$env_out"
  export DATABASE_URL="$TEST_DATABASE_URL"
  REDIS_TEST_DB="${REDIS_TEST_DB:-15}"
  export REDIS_URL="redis://127.0.0.1:${TEST_STACK_REDIS_PORT}/${REDIS_TEST_DB}"
  log "Host pytest DATABASE_URL → ephemeral ${TEST_DATABASE_URL##*/} (port ${TEST_STACK_POSTGRES_PORT})"
  log "Host pytest REDIS_URL → ephemeral port ${TEST_STACK_REDIS_PORT} DB ${REDIS_TEST_DB}"
  TEST_STACK_READY=true
}

# ---- Lint ----
run_lint() {
  log "Lint: pre-commit on ALL files (full CI-parity gate — src/ and beyond)"
  if _require pre-commit; then
    pre-commit run --all-files && ok "pre-commit OK" || { warn "pre-commit FAILED"; rc=1; }
  fi
  if [ -f "$REPO_ROOT/frontend/package.json" ]; then
    ( cd "$REPO_ROOT/frontend" && npm run lint 2>/dev/null ) && ok "eslint OK" || warn "eslint not configured — skip"
  fi
}

# ---- Unit tests (no Docker) ----
run_unit() {
  log "Unit: pytest (SQLite, no external services)"
  if [ -n "$PYTHON_BIN" ] && command -v "$PYTHON_BIN" &>/dev/null; then
    # Exclude ``slow`` (live Ollama golden in test_ai_quality) — validate-ai.sh owns that.
    "$PYTHON_BIN" -m pytest src/tests/unit/ -v --timeout=30 -m "not slow" && ok "unit tests passed" || { warn "unit tests FAILED"; rc=1; }
  else
    warn "python not installed — skipping unit tests"
    rc=1
  fi
}

# ---- Test DB (ephemeral stack) ----
run_test_db() {
  ensure_test_stack || return
  log "Test DB: ensure + migrate ${TEST_DATABASE_URL##*/} on the ephemeral server"
  bash "$HERE/ensure-test-db.sh" || { warn "ensure-test-db FAILED"; rc=1; }
}

# ---- Integration tests (needs PostGIS + Redis — ephemeral stack) ----
run_integration() {
  ensure_test_stack || return
  log "Integration: pytest (real PostGIS + Redis) against the ephemeral stack"
  if [ -n "$PYTHON_BIN" ] && command -v "$PYTHON_BIN" &>/dev/null; then
    "$PYTHON_BIN" -m pytest src/tests/integration/ -v && ok "integration tests passed" || { warn "integration tests FAILED"; rc=1; }
  else
    warn "python not installed — skipping integration tests"
    rc=1
  fi
}

# ---- Contract tests ----
run_contract() {
  ensure_test_stack || return
  log "Contract: pytest + alembic check (host → ephemeral test DB)"
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
  if [ -n "$PYTHON_BIN" ]; then
    log "Contract: alembic schema check (host → ephemeral test DB)"
    # PostGIS system tables (tiger, topology, spatial_ref_sys) always appear as
    # "extra" in autogenerate, so alembic check always reports false positives.
    # This check is informational only — never fails the build for PostGIS projects.
    ( cd "$REPO_ROOT" && PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}" \
        "$PYTHON_BIN" -m alembic check 2>/dev/null ) && ok "alembic check passed" \
      || warn "alembic check: PostGIS system tables detected (expected — informational only)"
  fi
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
  # PLAYWRIGHT_PORT is separate from Compose FRONTEND_PORT. Prefer .env.local
  # (sourced above); if unset, probe 5177 then 5187..5197 (etc.) for a free port.
  local pw_port
  pw_port="$(resolve_playwright_port)"
  export PLAYWRIGHT_PORT="$pw_port"
  log "E2E: Playwright (port ${pw_port})"
  ( cd "$REPO_ROOT/frontend" \
      && PLAYWRIGHT_PORT="$pw_port" npm run test:e2e ) \
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
    run_test_db
    run_integration
    run_contract
    ;;
  frontend)
    run_frontend
    ;;
  all)
    run_lint
    run_unit
    run_test_db
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
