#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# test.sh [unit|integration|e2e|all] [--args "..."]
#
# Run the test suite against the running stack.
#
#   unit        — Fast unit tests (no external services needed). Default.
#   integration — Integration tests (requires postgres + redis).
#   e2e         — End-to-end tests (requires full stack).
#   all         — Run everything.
#
# Extra pytest flags can be passed via --args:
#   ./scripts/test.sh unit --args "-v -k test_dedupe"
# ---------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"
require_docker

cd "$REPO_ROOT"

SCOPE="unit"
EXTRA_ARGS=()

while [ $# -gt 0 ]; do
  case "$1" in
    unit|integration|e2e|all) SCOPE="$1" ;;
    --args) shift; EXTRA_ARGS+=("$@"); break ;;
    *) EXTRA_ARGS+=("$1") ;;
  esac
  shift
done

run_unit() {
  log "Running unit tests..."
  compose_cmd run --rm api python -m pytest src/tests/unit/ -v "${EXTRA_ARGS[@]}"
}

run_integration() {
  log "Running integration tests..."
  compose_cmd run --rm api python -m pytest src/tests/integration/ -v --tb=short "${EXTRA_ARGS[@]}"
}

run_e2e() {
  log "Running end-to-end tests..."
  compose_cmd run --rm api python -m pytest src/tests/integration/test_e2e.py -v "${EXTRA_ARGS[@]}"
}

rc=0
case "$SCOPE" in
  unit)        run_unit         || rc=$? ;;
  integration) run_integration  || rc=$? ;;
  e2e)         run_e2e          || rc=$? ;;
  all)
    run_unit          || rc=$?
    run_integration   || rc=$?
    run_e2e           || rc=$?
    ;;
  *) die "usage: test.sh [unit|integration|e2e|all] [--args \"...\"]" ;;
esac

if [ "$rc" -eq 0 ]; then
  ok "ALL TESTS PASSED"
else
  warn "SOME TESTS FAILED (exit code $rc)"
fi
exit "$rc"
