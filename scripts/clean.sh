#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# clean.sh [--all]
#
# Tear down the development stack.
#
# Default: Stop containers. Named volumes are ALWAYS preserved.
# --all:   Also remove built images and build cache. Images and cache are
#          rebuildable in minutes, so this is safe; it no longer touches
#          volumes. Requires an interactive TTY.
#
# This script CANNOT delete data (v0.13-fu5). `--volumes` was removed: it ran
# `down -v` against the primary project with no confirmation, destroying
# postgres_data (the whole scraped + AI-enriched corpus), image_store (every
# downloaded photo), and redis_data (backfill checkpoints) — days of scraping
# and enrichment behind one flag. See the refusal message for the deliberate
# manual procedure.
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
    --volumes)
      die "'--volumes' was REMOVED — it destroyed postgres_data (the entire
  scraped + AI-enriched corpus), image_store, and redis_data with no
  confirmation. Volumes are never deleted by this script.

  If you genuinely intend to destroy local data, do it deliberately by hand
  (take a dump first):
    docker compose --env-file .env.local -p imoveis down
    docker volume rm imoveis_postgres_data imoveis_redis_data imoveis_image_store" ;;
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
    warn "Named volumes (Postgres/Redis/images) are PRESERVED — no data is lost."
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
  log "Stopping containers and removing images (volumes preserved)..."
  compose_cmd down --rmi local --remove-orphans

  log "Pruning build cache..."
  docker builder prune -f 2>/dev/null || true

  ok "Cleanup complete (images removed, build cache pruned, volumes preserved)"
else
  log "Stopping containers (volumes preserved)..."
  compose_cmd down
  ok "Stack stopped (volumes always preserved)"
fi
