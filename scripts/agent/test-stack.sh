#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# test-stack.sh [up|env|down|status]
#
# Single owner of the ephemeral validation stack (docker-compose.test.yml):
# Postgres (PostGIS + pgvector, image parity with primary) + Redis under the
# throwaway compose project "<workspace>-test" (primary checkout: imoveis-test;
# worktrees: <their-project>-test). Host ports are docker-assigned — never
# hardcoded, never colliding with the primary stack or sibling worktrees.
#
#   up      start (or reuse) the stack, wait until healthy
#   env     print `export` lines for the derived connection env — eval them:
#             eval "$(bash scripts/agent/test-stack.sh env)"
#           exports: TEST_STACK_POSTGRES_PORT, TEST_STACK_REDIS_PORT,
#                    TEST_DATABASE_URL (realestate_test on the ephemeral server)
#   down    destroy the stack incl. its anonymous volumes (throwaway by design;
#           the compose file defines no named volumes)
#   status  show the stack's containers
#
# This script can never touch the primary project: the project name is always
# suffixed "-test" and asserted different from PRIMARY_COMPOSE_PROJECT.
# ---------------------------------------------------------------------------
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

# The ephemeral stack needs compose v2 (`up --wait`, `port`).
docker compose version >/dev/null 2>&1 \
  || die "docker compose v2 required for the ephemeral test stack (docker-compose v1 has no 'up --wait')"

# .env.local supplies POSTGRES_PASSWORD / COMPOSE_PROJECT_NAME (workspace identity).
if [ -f "$REPO_ROOT/.env.local" ]; then
  set -a; # shellcheck disable=SC1091
  source "$REPO_ROOT/.env.local"; set +a
fi

PRIMARY_COMPOSE_PROJECT="${PRIMARY_COMPOSE_PROJECT:-imoveis}"
# Workspace identity comes from the FILE when present (stale inherited env from
# a torn-down worktree must not redirect the stack); env is only a fallback.
PROJ_FROM_FILE=""
if [ -f "$REPO_ROOT/.env.local" ]; then
  PROJ_FROM_FILE="$(awk -F= '/^(export[[:space:]]+)?COMPOSE_PROJECT_NAME=/{v=$2; gsub(/["'\''[:space:]]/,"",v); print v; exit}' "$REPO_ROOT/.env.local")"
fi
WORKSPACE_PROJ="$(sanitize_proj "${PROJ_FROM_FILE:-${COMPOSE_PROJECT_NAME:-imoveis}}")"
[ -n "$WORKSPACE_PROJ" ] || die "workspace project name sanitized to empty — fix COMPOSE_PROJECT_NAME in .env.local"
TEST_PROJ="${WORKSPACE_PROJ}-test"
[ "$TEST_PROJ" != "$PRIMARY_COMPOSE_PROJECT" ] \
  || die "test project name resolves to the primary project — refusing (fail closed)"

TC=(dc -f "$REPO_ROOT/docker-compose.test.yml" -p "$TEST_PROJ")

DB_USER="${POSTGRES_USER:-imoveis}"
DB_PASS="${POSTGRES_PASSWORD:-imoveis_local_dev}"
TEST_DB_NAME="${POSTGRES_TEST_DB:-realestate_test}"

resolve_port() {
  # `docker compose port <service> <container-port>` → "127.0.0.1:49321"
  "${TC[@]}" port "$1" "$2" 2>/dev/null | awk -F: 'NF > 1 {print $NF; exit}'
}

cmd_up() {
  log "Starting ephemeral validation stack (project ${TEST_PROJ})..."
  "${TC[@]}" up -d --wait postgres redis || die "test stack failed to start"
  ok "test stack up (postgres:$(resolve_port postgres 5432) redis:$(resolve_port redis 6379))"
}

cmd_env() {
  local pg rd
  pg="$(resolve_port postgres 5432)"
  rd="$(resolve_port redis 6379)"
  if [ -z "$pg" ] || [ -z "$rd" ]; then
    die "test stack not running — run: bash scripts/agent/test-stack.sh up"
  fi
  # %q-quote values — a password with shell metacharacters must survive the
  # `eval` in validate.sh intact (and must never be executed).
  printf 'export TEST_STACK_POSTGRES_PORT=%q\n' "$pg"
  printf 'export TEST_STACK_REDIS_PORT=%q\n' "$rd"
  printf 'export TEST_DATABASE_URL=%q\n' \
    "postgresql://${DB_USER}:${DB_PASS}@127.0.0.1:${pg}/${TEST_DB_NAME}"
}

cmd_down() {
  log "Destroying ephemeral validation stack (project ${TEST_PROJ})..."
  # -v removes only this project's anonymous volumes; the compose file defines
  # no named volumes, so nothing persistent can be lost here.
  "${TC[@]}" down -v --remove-orphans 2>/dev/null || warn "test stack down had issues"
  ok "test stack removed"
}

cmd_status() {
  "${TC[@]}" ps
}

case "${1:-}" in
  up)     cmd_up ;;
  env)    cmd_env ;;
  down)   cmd_down ;;
  status) cmd_status ;;
  *)      die "usage: test-stack.sh [up|env|down|status]" ;;
esac
