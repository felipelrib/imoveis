#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# clean.sh [--volumes] [--all]
#
# Tear down the development stack.
#
# Default:    Stop containers; keep named volumes (postgres_data, redis_data).
# --volumes:  Also remove named volumes (destroys local DB / Redis data).
# --all:      Also remove built images and build cache (nuclear option).
#             Implies --volumes. Only works interactively (TTY required);
#             skips image removal with a warning if run non-interactively.
# ---------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"
require_docker

cd "$REPO_ROOT"

if [ -f "$REPO_ROOT/.env.local" ]; then
  set -a; source "$REPO_ROOT/.env.local"; set +a
fi

REMOVE_IMAGES=false
REMOVE_VOLUMES=false
for arg in "$@"; do
  case "$arg" in
    --all) REMOVE_IMAGES=true; REMOVE_VOLUMES=true ;;
    --volumes) REMOVE_VOLUMES=true ;;
    *) die "Unknown flag: $arg. Usage: clean.sh [--volumes] [--all]" ;;
  esac
done

stop_frontend_dev

if [ "$REMOVE_IMAGES" = true ]; then
  if [ ! -t 0 ]; then
    warn "--all requires an interactive terminal (TTY). Skipping image removal."
    warn "Run interactively or use manual docker commands for full cleanup."
    REMOVE_IMAGES=false
  else
    echo ""
    warn "This will remove all Docker images and build cache for this project."
    warn "Named volumes (including Postgres data) will also be deleted."
    warn "Next start will require a full rebuild (~2-5 min)."
    echo ""
    read -r -p "Continue? [y/N] " confirm
    case "$confirm" in
      [yY][eE][sS]|[yY]) ;;
      *) log "Aborted."; exit 0 ;;
    esac
  fi
fi

if [ "$REMOVE_IMAGES" = true ]; then
  log "Stopping containers and removing volumes + images..."
  compose_cmd down -v --rmi local --remove-orphans

  log "Pruning build cache..."
  docker builder prune -f 2>/dev/null || true

  ok "Full cleanup complete (images removed, build cache pruned, volumes removed)"
elif [ "$REMOVE_VOLUMES" = true ]; then
  log "Stopping containers and removing volumes..."
  compose_cmd down -v
  ok "Stack stopped and volumes removed (images preserved)"
else
  log "Stopping containers (volumes preserved)..."
  compose_cmd down
  ok "Stack stopped (volumes preserved — pass --volumes to wipe Postgres/Redis data)"
fi
