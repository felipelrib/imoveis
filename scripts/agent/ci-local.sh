#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# ci-local.sh [job...]
#
# Runs GitHub Actions workflows locally using `act`.
# Default: runs lint + unit jobs (fast feedback).
# Requires: act (https://github.com/nektos/act), Docker.
#
# Usage:
#   bash scripts/agent/ci-local.sh              # lint + unit (fast)
#   bash scripts/agent/ci-local.sh lint unit    # specific jobs
#   bash scripts/agent/ci-local.sh -j lint      # act passthrough
# ---------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

if ! command -v act &>/dev/null; then
  warn "act is not installed — install from https://github.com/nektos/act"
  warn "  curl https://raw.githubusercontent.com/nektos/act/master/install.sh | sudo bash"
  exit 1
fi

JOBS=("${@:-lint,unit}")
log "Running CI jobs locally: ${JOBS[*]}"

if act pull_request -j "${JOBS[*]}" --rm; then
  ok "CI local PASSED"
else
  warn "CI local FAILED — check logs above"
  exit 1
fi
