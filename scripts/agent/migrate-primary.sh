#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# migrate-primary.sh [--dry-run]
#
# EXPLICIT OPERATOR STEP: migrate the PRIMARY `realestate` database
# (alembic upgrade head). This is the ONLY sanctioned path for primary
# migration — validate.sh/finish-feature.sh never touch the primary stack.
#
# Backfill guard, both halves (DW-3/DW-4):
#   1. This script takes `backfill:gemma:migrating` (SET NX EX, per-invocation
#      token) BEFORE it probes anything, renews it in the background for as long
#      as the upgrade runs, and releases it from an EXIT trap by token
#      compare-and-swap. A backfill runner reads that key at pass entry and
#      launches no row while it is held.
#   2. It then refuses while the runner's TTL'd heartbeat
#      (`backfill:gemma:active`, refreshed while the runner is alive, TTL ~300s)
#      exists in the primary Redis. The guard keys off the LIVE heartbeat only —
#      leftover `backfill:gemma:*` pacer/checkpoint state never blocks.
# The runner beats `:active` before reading `:migrating`, so with both sides
# set-then-check at least one of the two always sees the other: they can never
# both proceed. Both keys self-clear on their TTLs — never remove them manually.
#
# `--dry-run` never touches Redis beyond reading: it changes nothing, so taking
# a production key even for a second could bounce a runner starting in that
# window. It probes both keys, reports, and exits 0.
#
# Runs host-side (alembic via .venv) against the primary DB URL — it migrates
# schema but never creates/stops/restarts containers.
# ---------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

DRY_RUN=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    *) die "Unknown flag: $arg. Usage: migrate-primary.sh [--dry-run]" ;;
  esac
done

cd "$REPO_ROOT"
[ -f "$REPO_ROOT/.env.local" ] && { set -a; # shellcheck disable=SC1091
  source "$REPO_ROOT/.env.local"; set +a; }

# This script targets the PRIMARY stack by definition — refuse to run from a
# worktree whose .env.local re-points ports at an isolated stack (the heartbeat
# check and the migration would silently target the wrong servers).
PRIMARY_COMPOSE_PROJECT="${PRIMARY_COMPOSE_PROJECT:-imoveis}"
if [ -f "$REPO_ROOT/.env.local" ]; then
  _proj="$(awk -F= '/^(export[[:space:]]+)?COMPOSE_PROJECT_NAME=/{v=$2; gsub(/["'\''[:space:]]/,"",v); print v; exit}' "$REPO_ROOT/.env.local")"
  if [ -n "$_proj" ] && [ "$_proj" != "$PRIMARY_COMPOSE_PROJECT" ]; then
    die "this checkout's .env.local names project '$_proj', not the primary '$PRIMARY_COMPOSE_PROJECT' — run migrate-primary.sh from the primary checkout"
  fi
fi

DB_USER="${POSTGRES_USER:-imoveis}"
DB_PASS="${POSTGRES_PASSWORD:-imoveis_local_dev}"
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"
PRIMARY_DB="${POSTGRES_DB:-realestate}"
PRIMARY_DB_URL="postgresql://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${PRIMARY_DB}"
REDIS_HOST="localhost"
REDIS_PRIMARY_PORT="${REDIS_PORT:-6379}"
HEARTBEAT_KEY="backfill:gemma:active"
MIGRATE_LOCK_KEY="backfill:gemma:migrating"
# TTL, not a shutdown hook, is what frees the key after a hard kill — same
# contract as the runner's heartbeat and lease. Long enough for a real upgrade.
MIGRATE_LOCK_TTL_SECONDS="${MIGRATE_LOCK_TTL_SECONDS:-1800}"
# Validated here, not by redis: a non-numeric value aborts on the watchdog's
# arithmetic under `set -u` with no message, and `0` makes redis reject `ex=0`,
# which the acquire's blanket `except` turns into "is the primary Redis up?" —
# blaming healthy infrastructure for a typo.
case "$MIGRATE_LOCK_TTL_SECONDS" in
  ''|*[!0-9]*) die "MIGRATE_LOCK_TTL_SECONDS must be a positive integer of seconds (got '$MIGRATE_LOCK_TTL_SECONDS')" ;;
esac
[ "$MIGRATE_LOCK_TTL_SECONDS" -ge 1 ] || die "MIGRATE_LOCK_TTL_SECONDS must be >= 1 (got '$MIGRATE_LOCK_TTL_SECONDS')"
MIGRATE_LOCK_TOKEN="migrate-primary:${HOSTNAME:-host}:$$:$(date +%s)"

PYTHON_BIN=""
if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
elif command -v python3 &>/dev/null; then
  PYTHON_BIN="python3"
else
  die "python3 required"
fi

if [ "$DRY_RUN" = true ]; then
  # A dry run reports the guard, it does not participate in it: taking
  # ${MIGRATE_LOCK_KEY} here (even for the 1-2s the probe costs) makes a runner
  # that happens to start in that window refuse and exit 8 for a command that
  # by contract changes nothing. Read-only probe, no trap, no write.
  log "DRY RUN — probing the backfill guard on primary Redis (${REDIS_HOST}:${REDIS_PRIMARY_PORT}); no key is taken..."
  PROBE="$(
    REDIS_HOST="$REDIS_HOST" REDIS_PRIMARY_PORT="$REDIS_PRIMARY_PORT" \
    MIGRATE_LOCK_KEY="$MIGRATE_LOCK_KEY" HEARTBEAT_KEY="$HEARTBEAT_KEY" \
    "$PYTHON_BIN" - <<'PY'
import os
try:
    import redis
    r = redis.Redis(host=os.environ["REDIS_HOST"], port=int(os.environ["REDIS_PRIMARY_PORT"]), db=0,
                    socket_connect_timeout=3, socket_timeout=5)
    holder = r.get(os.environ["MIGRATE_LOCK_KEY"])
    if isinstance(holder, bytes):
        holder = holder.decode("utf-8", "replace")
    beat = "alive" if r.exists(os.environ["HEARTBEAT_KEY"]) else "idle"
    print(f"{'held:' + holder if holder else 'free'} {beat}")
except Exception as exc:  # Redis unreachable → the probe proves nothing
    print(f"unknown:{exc}")
PY
  )"
  read -r LOCK_PROBE HB_PROBE <<<"$PROBE"
  case "$LOCK_PROBE" in
    free)
      ok "${MIGRATE_LOCK_KEY} is free — a real run would take it"
      ;;
    held:*)
      warn "another migrate-primary.sh holds ${MIGRATE_LOCK_KEY} (token ${LOCK_PROBE#held:}) — a real run would refuse"
      ;;
    *)
      die "could not probe the backfill guard (${PROBE#unknown:}) — is the primary Redis up?"
      ;;
  esac
  case "$HB_PROBE" in
    idle) ok "no live backfill heartbeat (${HEARTBEAT_KEY}) — a real run would migrate" ;;
    alive) warn "backfill heartbeat ${HEARTBEAT_KEY} is ALIVE — a real run would refuse" ;;
  esac
  log "DRY RUN — would run: alembic upgrade head against ${PRIMARY_DB} (port ${DB_PORT})"
  exit 0
fi

# Release by owner-token compare-and-swap, so an invocation that was itself
# refused can never delete the key the *live* migration is holding.
release_migration_lock() {
  REDIS_HOST="$REDIS_HOST" REDIS_PRIMARY_PORT="$REDIS_PRIMARY_PORT" \
  MIGRATE_LOCK_KEY="$MIGRATE_LOCK_KEY" MIGRATE_LOCK_TOKEN="$MIGRATE_LOCK_TOKEN" \
  "$PYTHON_BIN" - <<'PY' || true
import os
try:
    import redis
    r = redis.Redis(host=os.environ["REDIS_HOST"], port=int(os.environ["REDIS_PRIMARY_PORT"]), db=0,
                    socket_connect_timeout=3, socket_timeout=5)
    r.eval("if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('del',KEYS[1]) end return 0",
           1, os.environ["MIGRATE_LOCK_KEY"], os.environ["MIGRATE_LOCK_TOKEN"])
except Exception:  # the key self-clears on its TTL — never fail the exit path
    pass
PY
}

# Re-EXPIRE by the same owner-token CAS: extending a key we no longer own would
# hand a *second* migration's window back to us.
renew_migration_lock() {
  REDIS_HOST="$REDIS_HOST" REDIS_PRIMARY_PORT="$REDIS_PRIMARY_PORT" \
  MIGRATE_LOCK_KEY="$MIGRATE_LOCK_KEY" MIGRATE_LOCK_TOKEN="$MIGRATE_LOCK_TOKEN" \
  MIGRATE_LOCK_TTL_SECONDS="$MIGRATE_LOCK_TTL_SECONDS" \
  "$PYTHON_BIN" - <<'PY'
import os
try:
    import redis
    r = redis.Redis(host=os.environ["REDIS_HOST"], port=int(os.environ["REDIS_PRIMARY_PORT"]), db=0,
                    socket_connect_timeout=3, socket_timeout=5)
    kept = r.eval("if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('expire',KEYS[1],ARGV[2]) end return 0",
                  1, os.environ["MIGRATE_LOCK_KEY"], os.environ["MIGRATE_LOCK_TOKEN"],
                  os.environ["MIGRATE_LOCK_TTL_SECONDS"])
    print("renewed" if kept else "lost")
except Exception as exc:
    print(f"unknown:{exc}")
PY
}

# Whether the key is still ours, without touching its TTL.
migration_lock_owner_state() {
  REDIS_HOST="$REDIS_HOST" REDIS_PRIMARY_PORT="$REDIS_PRIMARY_PORT" \
  MIGRATE_LOCK_KEY="$MIGRATE_LOCK_KEY" MIGRATE_LOCK_TOKEN="$MIGRATE_LOCK_TOKEN" \
  "$PYTHON_BIN" - <<'PY'
import os
try:
    import redis
    r = redis.Redis(host=os.environ["REDIS_HOST"], port=int(os.environ["REDIS_PRIMARY_PORT"]), db=0,
                    socket_connect_timeout=3, socket_timeout=5)
    held = r.get(os.environ["MIGRATE_LOCK_KEY"])
    if isinstance(held, bytes):
        held = held.decode("utf-8", "replace")
    print("ours" if held == os.environ["MIGRATE_LOCK_TOKEN"] else f"lost:{held or 'gone'}")
except Exception as exc:
    print(f"unknown:{exc}")
PY
}

LOCK_RENEW_PID=""
# A lock taken once with a fixed TTL stops excluding anything the moment
# `alembic upgrade head` outruns it: the DDL keeps writing while a runner that
# starts after the expiry sees a free guard — DW-3, reintroduced by the clock.
start_migration_lock_watchdog() {
  local interval=$(( MIGRATE_LOCK_TTL_SECONDS / 3 ))
  [ "$interval" -lt 1 ] && interval=1
  # `$$` stays the *script's* pid inside the subshell below (unlike `$BASHPID`),
  # which is exactly the process whose death must stop the renewals.
  local owner_pid=$$
  (
    # Bash resets traps for a background subshell, but pin it: a watchdog that
    # inherited the EXIT trap would release the very lock it exists to keep alive.
    trap - EXIT
    while true; do
      # 1s steps, not one long `sleep`: killing this subshell leaves its `sleep`
      # child alive holding the caller's stdout pipe, so a long one would hang
      # whoever reads this script's output for the rest of the interval.
      #
      # The liveness check is what makes the documented "a hard-killed migration
      # self-clears on its TTL" true: a SIGKILLed script never runs its EXIT
      # trap, so an orphaned watchdog would keep renewing ${MIGRATE_LOCK_KEY}
      # forever and block every backfill until someone found and killed it — and
      # the key is contractually never deleted by hand.
      for _ in $(seq "$interval"); do
        sleep 1
        kill -0 "$owner_pid" 2>/dev/null || exit 0
      done
      # `|| true`: a renewal that cannot even start (interpreter gone, OOM-killed
      # child) must not take the watchdog down with it under `set -e` — that
      # stops every later renewal silently and the lock lapses mid-upgrade.
      state="$(renew_migration_lock || true)"
      case "$state" in
        renewed) ;;
        lost)
          # Never kill the running alembic over this: a half-applied migration
          # is worse than an unguarded one. Say it loudly instead.
          warn "MIGRATION LOCK LOST: ${MIGRATE_LOCK_KEY} is no longer held by this invocation — a backfill runner can start mid-upgrade. Check 'backfill_gemma.py --status' when alembic finishes." >&2
          ;;
        *)
          detail="${state:-renewal command failed to run}"
          warn "could not renew ${MIGRATE_LOCK_KEY} (${detail#unknown:}) — mutual exclusion may lapse before alembic finishes" >&2
          ;;
      esac
    done
  ) &
  LOCK_RENEW_PID=$!
}

release_migration_lock_and_watchdog() {
  # The watchdog goes first: it must not renew a key this exit is about to hand
  # back, and a surviving child keeps the script's stdout pipe open.
  if [ -n "$LOCK_RENEW_PID" ]; then
    kill "$LOCK_RENEW_PID" 2>/dev/null || true
    wait "$LOCK_RENEW_PID" 2>/dev/null || true
    LOCK_RENEW_PID=""
  fi
  release_migration_lock
}
# Armed BEFORE the acquire below runs: every exit path (success, refusal, error)
# hands the key back, and the CAS makes arming it early a no-op if we never win.
trap release_migration_lock_and_watchdog EXIT

log "Migration lock: taking ${MIGRATE_LOCK_KEY} on primary Redis (${REDIS_HOST}:${REDIS_PRIMARY_PORT})..."
# Taking the lock BEFORE the heartbeat probe is the whole fix: probing first
# left the entire `alembic upgrade` window unguarded, so a runner that started
# in the gap migrated against a live writer (DW-3).
LOCK_STATE="$(
  REDIS_HOST="$REDIS_HOST" REDIS_PRIMARY_PORT="$REDIS_PRIMARY_PORT" \
  MIGRATE_LOCK_KEY="$MIGRATE_LOCK_KEY" MIGRATE_LOCK_TOKEN="$MIGRATE_LOCK_TOKEN" \
  MIGRATE_LOCK_TTL_SECONDS="$MIGRATE_LOCK_TTL_SECONDS" \
  "$PYTHON_BIN" - <<'PY'
import os
try:
    import redis
    r = redis.Redis(host=os.environ["REDIS_HOST"], port=int(os.environ["REDIS_PRIMARY_PORT"]), db=0,
                    socket_connect_timeout=3, socket_timeout=5)
    # SET NX is atomic, so two concurrent invocations cannot both win.
    took = r.set(os.environ["MIGRATE_LOCK_KEY"], os.environ["MIGRATE_LOCK_TOKEN"],
                 nx=True, ex=int(os.environ["MIGRATE_LOCK_TTL_SECONDS"]))
    print("taken" if took else "busy")
except Exception as exc:  # Redis unreachable → no mutual exclusion → fail closed
    print(f"unknown:{exc}")
PY
)"

case "$LOCK_STATE" in
  taken)
    ok "migration lock held (${MIGRATE_LOCK_TTL_SECONDS}s TTL, renewed while alembic runs) — a backfill runner starting now will launch nothing"
    ;;
  busy)
    die "another migrate-primary.sh already holds ${MIGRATE_LOCK_KEY} — wait for it to finish (the key self-clears within its TTL) and re-run."
    ;;
  *)
    die "could not take ${MIGRATE_LOCK_KEY} (${LOCK_STATE#unknown:}) — refusing to migrate without mutual exclusion against the backfill runner (fail closed). Is the primary Redis up?"
    ;;
esac

log "Backfill heartbeat guard: checking ${HEARTBEAT_KEY} on primary Redis (${REDIS_HOST}:${REDIS_PRIMARY_PORT})..."
HB_STATE="$(
  REDIS_HOST="$REDIS_HOST" REDIS_PRIMARY_PORT="$REDIS_PRIMARY_PORT" HEARTBEAT_KEY="$HEARTBEAT_KEY" \
  "$PYTHON_BIN" - <<'PY'
import os
try:
    import redis
    r = redis.Redis(host=os.environ["REDIS_HOST"], port=int(os.environ["REDIS_PRIMARY_PORT"]), db=0,
                    socket_connect_timeout=3, socket_timeout=5)
    print("alive" if r.exists(os.environ["HEARTBEAT_KEY"]) else "idle")
except Exception as exc:  # Redis unreachable → cannot prove idle → fail closed
    print(f"unknown:{exc}")
PY
)"

case "$HB_STATE" in
  idle)
    ok "no live backfill heartbeat — safe to migrate"
    ;;
  alive)
    die "backfill heartbeat is ALIVE — a runner is writing to the primary DB. Wait for it to finish (the key self-clears within its TTL) and re-run."
    ;;
  *)
    die "could not check the backfill heartbeat (${HB_STATE#unknown:}) — refusing to migrate without proof the primary is idle (fail closed). Is the primary Redis up?"
    ;;
esac

start_migration_lock_watchdog
log "Migration lock: renewing every $(( MIGRATE_LOCK_TTL_SECONDS / 3 ))s for as long as alembic runs (pid ${LOCK_RENEW_PID})"

log "Migrating PRIMARY ${PRIMARY_DB} (alembic upgrade head, host-side)..."
# Not under `set -e`: a FAILED upgrade is exactly when "was this guarded?" matters
# most (the schema may be half-applied), and dying on the spot skipped the check.
set +e
DATABASE_URL="$PRIMARY_DB_URL" PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:$PYTHONPATH}" \
  "$PYTHON_BIN" -m alembic upgrade head
ALEMBIC_RC=$?
set -e

# The upgrade ran; whether it ran *guarded* is a separate question, and one an
# operator must not have to infer from scrollback timing.
LOCK_FINAL_STATE="$(migration_lock_owner_state)"
if [ "$LOCK_FINAL_STATE" != "ours" ]; then
  warn "${MIGRATE_LOCK_KEY} was not ours when alembic finished (${LOCK_FINAL_STATE}) — the upgrade ran part of the time without mutual exclusion. Check the backfill runner's --status and recent enrichment timestamps." >&2
fi

if [ "$ALEMBIC_RC" -ne 0 ]; then
  # `warn` + explicit exit, not `die`: alembic's own status is the useful one.
  # The EXIT trap still hands the key back on the way out.
  warn "alembic upgrade head FAILED (exit ${ALEMBIC_RC}) — the primary may be partially migrated" >&2
  exit "$ALEMBIC_RC"
fi
ok "primary ${PRIMARY_DB} migrated to head"
