#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# stop.sh
#
# Stop the development stack gracefully (containers are kept so restart is fast).
#
# This script CANNOT delete data. It never removes named volumes: postgres_data
# holds the whole scraped + AI-enriched corpus, image_store holds every
# downloaded photo, and redis_data holds backfill checkpoints. Rebuilding that
# costs days of scraping and enrichment, so a single mistyped flag must not be
# able to destroy it (v0.13-fu5). `--volumes` was removed for that reason; see
# the refusal message below for the deliberate manual procedure.
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

stop_frontend_dev

if [ "$#" -gt 0 ]; then
  die "stop.sh takes no flags. '--volumes' was REMOVED: it wiped postgres_data
  (the entire scraped + AI-enriched corpus), image_store, and redis_data with no
  confirmation. Volumes are never deleted by this script.

  If you genuinely intend to destroy local data, do it deliberately by hand
  (take a dump first):
    docker compose --env-file .env.local -p imoveis down
    docker volume rm imoveis_postgres_data imoveis_redis_data imoveis_image_store"
fi

log "Stopping stack..."
compose_cmd down
ok "Stack stopped (volumes always preserved)"
