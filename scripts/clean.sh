#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# clean.sh [--all]
#
# Tear down the development stack and clean up.
#
# Default:    Stop containers and remove volumes (safe — images kept).
# --all:      Also remove built images and build cache (nuclear option).
#             Only works interactively (TTY required); skips with a warning
#             if run non-interactively (piped or scripted).
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
for arg in "$@"; do
  case "$arg" in
    --all) REMOVE_IMAGES=true ;;
    --volumes) ;;  # no-op — default behavior
    *) die "Unknown flag: $arg. Usage: clean.sh [--all]" ;;
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
  log "Stopping containers and removing volumes..."
  compose_cmd down -v --rmi local --remove-orphans

  log "Pruning build cache..."
  docker builder prune -f 2>/dev/null || true

  ok "Full cleanup complete (images removed, build cache pruned)"
else
  log "Stopping containers and removing volumes..."
  compose_cmd down -v
  ok "Stack stopped and volumes removed (images preserved)"
fi
