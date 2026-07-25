#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# docker-cleanup.sh [--dry-run]
#
# Remove temporary Docker resources left after feature development wrap-up:
#   - stopped containers
#   - dangling (untagged) images
#   - unused build cache (builder prune, non-all)
#
# NEVER removes named volumes (postgres_data / redis_data).
# NEVER runs `docker system prune --volumes` or `docker volume rm`.
# Does NOT stop a running Compose stack — only prunes leftovers.
#
# Called automatically from finish-feature.sh after merge cleanup.
# Safe to re-run manually anytime.
# ---------------------------------------------------------------------------
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

DRY_RUN=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    *)
      if [ -n "$arg" ]; then
        die "Unknown flag: $arg. Usage: docker-cleanup.sh [--dry-run]"
      fi
      ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  warn "docker not found — skipping temporary container/image cleanup"
  exit 0
fi
if ! docker info >/dev/null 2>&1; then
  warn "docker daemon not reachable — skipping temporary container/image cleanup"
  exit 0
fi

log "Cleaning temporary Docker containers and images (volumes preserved)..."

prune_step() {
  local label="$1"
  shift
  if [ "$DRY_RUN" = true ]; then
    log "DRY RUN — would run: $*"
    return 0
  fi
  if "$@" >/dev/null 2>&1; then
    return 0
  fi
  warn "${label} prune had issues"
}

# Stopped containers only (never kills a running stack).
prune_step "container" docker container prune -f

# Untagged/dangling images left by rebuilds (docker compose build).
prune_step "image" docker image prune -f

# Build cache only — not volumes, not tagged images still in use.
prune_step "builder" docker builder prune -f

ok "temporary Docker containers/images cleaned (named volumes untouched)"
