#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# teardown.sh [--remove] [--volumes]
#
# Stops and removes this workspace's containers (frees the ports).
#
# Volumes:
#   Primary project (COMPOSE_PROJECT_NAME=imoveis): volumes are KEPT unless
#   --volumes is passed (scraped data lives on the primary stack).
#   Worktree / non-primary projects: volumes are removed by default so
#   isolation does not leave orphan stacks; pass nothing extra.
#
# With --remove, also removes a linked git worktree and its registry entry.
# Run from INSIDE the worktree (or any checkout with .env.local).
# ---------------------------------------------------------------------------
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

REMOVE=0
REMOVE_VOLUMES=0
for arg in "$@"; do
  case "$arg" in
    --remove) REMOVE=1 ;;
    --volumes) REMOVE_VOLUMES=1 ;;
    *)
      if [ -n "$arg" ]; then
        die "Unknown flag: $arg. Usage: teardown.sh [--remove] [--volumes]"
      fi
      ;;
  esac
done

cd "$REPO_ROOT"

PRIMARY_COMPOSE_PROJECT="${PRIMARY_COMPOSE_PROJECT:-imoveis}"

if [ -f "$REPO_ROOT/.env.local" ]; then
  set -a; # shellcheck disable=SC1091
  source "$REPO_ROOT/.env.local"; set +a
  PROJ="${COMPOSE_PROJECT_NAME:-imoveis}"

  WIPE_VOLUMES=0
  if [ "$REMOVE_VOLUMES" -eq 1 ]; then
    WIPE_VOLUMES=1
  elif [ "$PROJ" != "$PRIMARY_COMPOSE_PROJECT" ]; then
    # Worktree / isolated stacks: drop their private volumes by default.
    WIPE_VOLUMES=1
  fi

  if [ "$WIPE_VOLUMES" -eq 1 ]; then
    log "Tearing down containers + volumes for project '$PROJ'"
    dc --env-file .env.local -p "$PROJ" down -v --remove-orphans || warn "compose down had issues"
    ok "containers + volumes removed"
  else
    log "Tearing down containers for primary project '$PROJ' (volumes preserved)"
    dc --env-file .env.local -p "$PROJ" down --remove-orphans || warn "compose down had issues"
    ok "containers removed (volumes preserved — pass --volumes to wipe Postgres/Redis)"
  fi
else
  warn "no .env.local — nothing to tear down here"
fi

if [ "$REMOVE" -eq 1 ]; then
  BRANCH="$(current_branch)"
  WT="$REPO_ROOT"
  if ! in_linked_worktree; then
    die "--remove only applies to linked worktrees (you are in the primary checkout)"
  fi
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
