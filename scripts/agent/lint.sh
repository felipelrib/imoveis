#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# lint.sh [--fix]
#
# Run all linters for the project. Matches CI pipeline exactly.
#   --fix   auto-fix with isort and eslint where possible
# ---------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

FIX=false
[ "${1:-}" = "--fix" ] && FIX=true

rc=0

log "Running Python lint (isort)"
if $FIX; then
  isort src/ || { warn "isort fix failed"; rc=1; }
  ok "isort (fix) done"
else
  if isort --check --diff src/; then
    ok "isort OK"
  else
    warn "isort FAILED — run 'bash scripts/agent/lint.sh --fix'"; rc=1
  fi
fi

log "Running Python lint (flake8)"
if flake8 src/ --max-line-length=127 --extend-ignore=E203,W503; then
  ok "flake8 OK"
else
  warn "flake8 FAILED"; rc=1
fi

if [ -f "$REPO_ROOT/frontend/package.json" ]; then
  log "Running Frontend lint (eslint)"
  if ( cd "$REPO_ROOT/frontend" && npm run lint 2>/dev/null ); then
    ok "eslint OK"
  else
    warn "eslint not configured or FAILED — check frontend/package.json"; rc=1
  fi
fi

[ "$rc" -eq 0 ] && ok "LINT PASSED" || warn "LINT FAILED (rc=$rc)"
exit "$rc"