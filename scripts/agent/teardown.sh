#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# teardown.sh [--remove]
#
# Stops and removes this worktree's containers + volumes + images (frees the
# ports). With --remove, also removes the git worktree and its registry entry.
# Run from INSIDE the worktree.
# ---------------------------------------------------------------------------
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

REMOVE=0; [ "${1:-}" = "--remove" ] && REMOVE=1
cd "$REPO_ROOT"

if [ -f "$REPO_ROOT/.env.local" ]; then
  set -a; source "$REPO_ROOT/.env.local"; set +a
  PROJ="${COMPOSE_PROJECT_NAME:-imoveis}"
  log "Tearing down containers + volumes + images for project '$PROJ'"
  # Stop containers, remove volumes, and remove images built by compose
  dc --env-file .env.local -p "$PROJ" down -v --remove-orphans --rmi local 2>/dev/null || warn "compose down had issues"
  # Clean up build cache left behind by this project
  docker builder prune --filter "label=com.docker.compose.project=$PROJ" 2>/dev/null || true
  ok "containers + volumes + images removed"
else
  warn "no .env.local — nothing to tear down here"
fi

if [ "$REMOVE" -eq 1 ]; then
  BRANCH="$(current_branch)"
  WT="$REPO_ROOT"
  log "Removing worktree $WT and registry entry for $BRANCH"
  registry_lock
  if [ -f "$REGISTRY_FILE" ]; then
    grep -vP "^$BRANCH\t" "$REGISTRY_FILE" > "$REGISTRY_FILE.tmp" 2>/dev/null || true
    mv "$REGISTRY_FILE.tmp" "$REGISTRY_FILE" 2>/dev/null || true
  fi
  registry_unlock
  cd "$PRIMARY_ROOT"
  git worktree remove --force "$WT" && ok "worktree removed" || warn "could not remove worktree (uncommitted changes? use with care)"
  echo "  Branch '$BRANCH' is kept. Delete it with: git branch -D $BRANCH"
fi
