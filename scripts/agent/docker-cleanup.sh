#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# docker-cleanup.sh [--dry-run]
#
# Remove temporary Docker resources left after feature development wrap-up:
#   - stopped containers
#   - dangling (untagged) images
#   - unused *temporary* tagged images from feature/worktree Compose projects
#   - unused build cache (builder prune, non-all)
#
# Keeps (never removes):
#   - Running containers and any image they use
#   - Images for still-running Compose projects (full project prefix)
#   - Primary stack images (`imoveis-*` except `imoveis-wt-*`)
#   - Third-party / base images (redis, postgres upstream, ghcr.io, …)
#   - Named volumes (postgres_data / redis_data)
#
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
# shellcheck source=docker-cleanup-lib.sh
source "$HERE/docker-cleanup-lib.sh"

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

log "Cleaning temporary Docker containers and images (volumes + primary stack preserved)..."

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

# --- Unused temporary tagged images (feat-*/fix-*/imoveis-wt-*, …) ----------
# Collect Compose project names that still have running containers so a
# partial stack (e.g. only postgres up) does not lose sibling service images.
active_projects=""
while IFS= read -r proj; do
  [ -n "$proj" ] || continue
  active_projects="${active_projects}"$'\n'"${proj}"
done < <(docker ps --format '{{.Label "com.docker.compose.project"}}' 2>/dev/null | sort -u)

image_in_use_by_running() {
  local ref="$1"
  local id="$2"
  docker ps -q --filter "ancestor=${ref}" 2>/dev/null | grep -q . && return 0
  docker ps -q --filter "ancestor=${id}" 2>/dev/null | grep -q . && return 0
  return 1
}

removed=0
skipped_active=0
while IFS=$'\t' read -r repo tag id; do
  [ -n "$repo" ] || continue
  [ "$repo" = "<none>" ] && continue

  should_remove_temporary_image_repo "$repo" "$active_projects" || continue

  ref="${repo}:${tag}"
  if [ "$tag" = "<none>" ]; then
    ref="$id"
  fi

  if image_in_use_by_running "$ref" "$id"; then
    skipped_active=$((skipped_active + 1))
    continue
  fi

  if [ "$DRY_RUN" = true ]; then
    log "DRY RUN — would remove temporary image ${ref}"
    removed=$((removed + 1))
    continue
  fi
  if docker image rm "$ref" >/dev/null 2>&1; then
    removed=$((removed + 1))
  else
    # Race: container started mid-cleanup, or shared layers — non-fatal.
    warn "could not remove ${ref} (in use or already gone)"
  fi
done < <(docker images --format '{{.Repository}}\t{{.Tag}}\t{{.ID}}' 2>/dev/null)

if [ "$removed" -gt 0 ] || [ "$skipped_active" -gt 0 ]; then
  log "temporary tagged images: removed=${removed} kept_for_active_projects=${skipped_active}"
fi

# Build cache only — not volumes, not tagged images still in use.
prune_step "builder" docker builder prune -f

ok "temporary Docker containers/images cleaned (primary stack + named volumes untouched)"
