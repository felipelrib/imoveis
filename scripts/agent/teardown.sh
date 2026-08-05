#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# teardown.sh [--remove] [--volumes] [--primary]
#
# Stops and removes this workspace's containers (frees the ports).
#
# FAIL-CLOSED identity guard (CAP-2): the compose project is read from
# .env.local ONLY — an inherited COMPOSE_PROJECT_NAME env var is never
# trusted for destruction. Refuses when:
#   - .env.local is missing or does not define COMPOSE_PROJECT_NAME
#     (ambiguous identity — no defaulting to the primary project), or
#   - the project resolves to the primary stack and --primary was not
#     explicitly passed (and even then, volumes are NEVER wiped:
#     --primary --volumes is always refused — scraped data lives there).
#
# Volumes:
#   Worktree / non-primary projects: private volumes are removed by default
#   so isolation does not leave orphan stacks; `down --rmi local` also drops
#   Compose-built images. The ephemeral "<proj>-test" validation stack is
#   torn down too.
#   Primary project (--primary): containers only; volumes + images preserved.
#
# Always runs docker-cleanup.sh afterward (stopped containers + dangling
# images + unused feat/wt tagged images + build cache; never named volumes).
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
ALLOW_PRIMARY=0
for arg in "$@"; do
  case "$arg" in
    --remove) REMOVE=1 ;;
    --volumes) REMOVE_VOLUMES=1 ;;
    --primary) ALLOW_PRIMARY=1 ;;
    *)
      if [ -n "$arg" ]; then
        die "Unknown flag: $arg. Usage: teardown.sh [--remove] [--volumes] [--primary]"
      fi
      ;;
  esac
done

cd "$REPO_ROOT"

PRIMARY_COMPOSE_PROJECT="${PRIMARY_COMPOSE_PROJECT:-imoveis}"

if [ ! -f "$REPO_ROOT/.env.local" ]; then
  die "no .env.local — project identity unknown, refusing to tear anything down (fail closed). Run setup-workspace.sh/setup-worktree.sh to (re)create it, or clean up manually."
fi

# Identity comes from the FILE, never from inherited env (fail closed on drift).
# Tolerates `export COMPOSE_PROJECT_NAME=…` and quoted values.
PROJ="$(awk -F= '/^(export[[:space:]]+)?COMPOSE_PROJECT_NAME=/{v=$2; gsub(/["'\''[:space:]]/,"",v); print v; exit}' "$REPO_ROOT/.env.local")"
if [ -z "$PROJ" ]; then
  die "COMPOSE_PROJECT_NAME is not defined in .env.local — project identity is ambiguous, refusing to tear anything down (fail closed). Fix .env.local (setup-workspace.sh/setup-worktree.sh write it) and re-run."
fi

# Rest of the env (ports, passwords) is still useful for compose.
set -a; # shellcheck disable=SC1091
source "$REPO_ROOT/.env.local"; set +a
export COMPOSE_PROJECT_NAME="$PROJ"

# This workspace's ephemeral validation stack goes first — its "-test" suffix
# means it can never be the primary, so it is safe to drop even when the guard
# below refuses to touch the workspace stack itself.
bash "$HERE/test-stack.sh" down || warn "test-stack down had issues"

if [ "$PROJ" = "$PRIMARY_COMPOSE_PROJECT" ]; then
  if [ "$ALLOW_PRIMARY" -ne 1 ]; then
    die "project '$PROJ' is the PRIMARY stack — refusing to touch it (fail closed). Agents/validation must never stop the primary; an operator may pass --primary to stop its containers (volumes always preserved)."
  fi
  if [ "$REMOVE_VOLUMES" -eq 1 ]; then
    die "refusing --volumes on the primary stack — scraped data lives in its named volumes. Removing them is a manual operator decision outside this script."
  fi
fi

if [ "$PROJ" = "$PRIMARY_COMPOSE_PROJECT" ]; then
  log "Tearing down containers for PRIMARY project '$PROJ' (--primary; volumes + tagged images preserved)"
  dc --env-file .env.local -p "$PROJ" down --remove-orphans || warn "compose down had issues"
  ok "containers removed (volumes preserved — primary volumes are never wiped by this script)"
else
  # Worktree / isolated stacks: drop their private volumes + local images by
  # default so isolation does not leave orphans. (--volumes is implied here.)
  log "Tearing down containers + volumes + local images for project '$PROJ'"
  dc --env-file .env.local -p "$PROJ" down -v --rmi local --remove-orphans || warn "compose down had issues"
  ok "containers + volumes + local images removed"
fi

# Always prune stopped leftovers / dangling images after compose down (never volumes).
bash "$HERE/docker-cleanup.sh" || warn "docker-cleanup.sh had issues"


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
