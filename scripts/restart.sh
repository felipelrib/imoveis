#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# restart.sh [--build] [service ...]
#
# Stop and restart the development stack. Pass --build to rebuild images
# (useful after dependency or Dockerfile changes). Pass specific service names
# to restart only part of the stack.
# ---------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"
require_docker

BUILD_FLAG=""
SERVICES=()

for arg in "$@"; do
  if [ "$arg" = "--build" ]; then
    BUILD_FLAG="--build"
  else
    SERVICES+=("$arg")
  fi
done

log "Restarting stack..."
"$HERE/stop.sh"
"$HERE/start.sh" $BUILD_FLAG "${SERVICES[@]}"