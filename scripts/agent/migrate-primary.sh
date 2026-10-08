#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# migrate-primary.sh [--dry-run]
#
# EXPLICIT OPERATOR STEP: migrate the PRIMARY `realestate` database
# (alembic upgrade head). This is the ONLY sanctioned path for primary
# migration — validate.py/ship.py never touch the primary stack.
#
# Backfill guard, both halves (DW-3/DW-4):
#   1. This script takes `<prefix>:migrating` (SET NX EX, per-invocation
#      token) BEFORE it probes anything, renews it in the background for as long
#      as the upgrade runs, and releases it from an EXIT trap by token
#      compare-and-swap. A backfill runner reads that key at pass entry and
#      launches no row while it is held.
#   2. It then refuses while the runner's TTL'd heartbeat
#      (`<prefix>:active`, refreshed while the runner is alive, TTL ~300s)
#      exists in the primary Redis. The guard keys off the LIVE heartbeat only —
#      leftover `<prefix>:*` pacer/checkpoint state never blocks.
# The runner beats `:active` before reading `:migrating`, so with both sides
# set-then-check at least one of the two always sees the other: they can never
# both proceed. Both keys self-clear on their TTLs — never remove them manually.
#
# Where the keys live (DW-8): the Redis endpoint and `<prefix>` are NOT written
# in this file. They are resolved once through `infra.config.load_config()` —
# `cfg.redis.url` and `cfg.backfill.redis_prefix`, the values the runner's own
# client and key names come from — after sourcing `.env.local`, the runner's env
# file. If that resolution fails the script refuses (fail closed), dry run
# included. `REDIS_PORT` is not an input: the runner does not read it.
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

activate_project_python || die "runnable Python required"
# Ahead of the resolution below, not only ahead of alembic: the config loader
# is `infra.config` under src/, and it imports `src.core.*` from the root.
prepend_python_path "$REPO_ROOT/src"
prepend_python_path "$REPO_ROOT"

# The guard's Redis endpoint and key prefix come from the loader the backfill
# runner itself uses (infra.config: REDIS_URL, IMOVEIS_BACKFILL__REDIS_PREFIX,
# configs/app_config.yaml), in the environment the runner gets — `.env.local`,
# sourced above, is the runner's own env file. A host, db or key name written
# here instead is what DW-8 was: change either setting and the two sides sit in
# different keyspaces, neither sees the other's key, and both proceed.
# One tab-separated line, so a prefix or URL can carry any other character.
GUARD_RESOLUTION="$("$PYTHON_BIN" - <<'PY' || true
try:
    from infra.config import load_config

    cfg = load_config()
    url = cfg.redis.url
    prefix = cfg.backfill.redis_prefix
    try:
        # What the redis client does first with this URL. It raises when a
        # password carries an unencoded "/", "?" or "#", and its message quotes
        # the piece of the password in front of that character — so fail here,
        # in words, instead of in every Redis call below.
        from urllib.parse import urlparse

        urlparse(url).port
    except ValueError:
        raise ValueError(
            "the Redis URL from the app config does not parse; a password"
            " containing / ? or # must be percent-encoded"
        ) from None
    if not isinstance(prefix, str) or not prefix or any(ch.isspace() for ch in prefix):
        raise ValueError("backfill.redis_prefix is empty or contains whitespace")
    if not url or any(ch.isspace() for ch in url):
        raise ValueError("the Redis URL is empty or contains whitespace")
    # Shown to the operator instead of the URL, which can carry a password.
    endpoint = f"{cfg.redis.host}:{cfg.redis.port}/{cfg.redis.db}"
    print("\t".join(("ok", url, prefix, endpoint)))
except Exception as exc:  # no endpoint or no prefix → no guard → fail closed
    import re

    # The loader's validation errors quote the offending input, and for a
    # section-level error that input is the whole section (API keys included).
    # Keep the location and the message, never the value.
    reason = " ".join(f"{type(exc).__name__}: {exc}".split())
    reason = re.sub(r"input_value=.*?, input_type=", "input_value=<hidden>, input_type=", reason)
    if isinstance(exc, ValueError) and type(exc).__name__ != "ValidationError":
        # A plain ValueError out of the loader is a parse error on an
        # environment value (REDIS_URL, DATABASE_URL), and urlparse / int()
        # quote the piece they choked on — which can be part of a password.
        # Keep the words in front of the first quote, drop the rest.
        cut = re.split(r"[\x27\x22]", reason, maxsplit=1)  # either quote character
        if len(cut) > 1:
            reason = cut[0].rstrip(" :") + " <value hidden>"
    print(f"unknown:{reason[:300]}")
PY
)"
GUARD_RESOLUTION="${GUARD_RESOLUTION//$'\r'/}"
GUARD_RESOLUTION="${GUARD_RESOLUTION##*$'\n'}"
GUARD_REDIS_URL=""; GUARD_PREFIX=""; GUARD_ENDPOINT=""
case "$GUARD_RESOLUTION" in
  ok$'\t'*)
    IFS=$'\t' read -r _ GUARD_REDIS_URL GUARD_PREFIX GUARD_ENDPOINT <<<"$GUARD_RESOLUTION"
    ;;
esac
if [ -z "$GUARD_REDIS_URL" ] || [ -z "$GUARD_PREFIX" ] || [ -z "$GUARD_ENDPOINT" ]; then
  # Also for --dry-run: a report about keys that may not be the runner's is
  # worse than no report. Falling back to a default here would be DW-8 again.
  _why="${GUARD_RESOLUTION#unknown:}"
  case "$GUARD_RESOLUTION" in ok$'\t'*) _why="the resolver returned an incomplete answer" ;; esac
  die "the backfill guard's Redis endpoint and key prefix could not be resolved through infra.config (${_why:-the resolver printed nothing}) — refusing to migrate without knowing where the runner's keys live (fail closed). The reason in parentheses comes from the app config loader, which reads .env.local and configs/app_config.yaml; the guard's own settings are REDIS_URL and IMOVEIS_BACKFILL__REDIS_PREFIX."
fi
# Exported once and read by every Redis snippet below from the environment:
# never on a command line and never in a log line (it can carry a password).
export GUARD_REDIS_URL
HEARTBEAT_KEY="${GUARD_PREFIX}:active"
MIGRATE_LOCK_KEY="${GUARD_PREFIX}:migrating"

# REDIS_PORT is the compose port mapping; the runner never reads it. The guard
# follows the runner, and says so when the two disagree.
_guard_port="${GUARD_ENDPOINT##*:}"
_guard_port="${_guard_port%%/*}"
if [ -n "${REDIS_PORT:-}" ] && [ "$REDIS_PORT" != "$_guard_port" ]; then
  warn "REDIS_PORT=${REDIS_PORT} is not what the backfill runner uses: it takes its Redis from REDIS_URL / app config (${GUARD_ENDPOINT}), and the guard follows the runner. Set REDIS_URL in .env.local if the primary Redis listens elsewhere."
fi

if [ "$DRY_RUN" = true ]; then
  # A dry run reports the guard, it does not participate in it: taking
  # ${MIGRATE_LOCK_KEY} here (even for the 1-2s the probe costs) makes a runner
  # that happens to start in that window refuse and exit 8 for a command that
  # by contract changes nothing. Read-only probe, no trap, no write.
  log "DRY RUN — probing the backfill guard on primary Redis (${GUARD_ENDPOINT}); no key is taken..."
  PROBE="$(
    MIGRATE_LOCK_KEY="$MIGRATE_LOCK_KEY" HEARTBEAT_KEY="$HEARTBEAT_KEY" \
    "$PYTHON_BIN" - <<'PY'
import os
try:
    import redis
    r = redis.Redis.from_url(os.environ["GUARD_REDIS_URL"], socket_connect_timeout=3, socket_timeout=5)
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
  MIGRATE_LOCK_KEY="$MIGRATE_LOCK_KEY" MIGRATE_LOCK_TOKEN="$MIGRATE_LOCK_TOKEN" \
  "$PYTHON_BIN" - <<'PY' || true
import os
try:
    import redis
    r = redis.Redis.from_url(os.environ["GUARD_REDIS_URL"], socket_connect_timeout=3, socket_timeout=5)
    r.eval("if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('del',KEYS[1]) end return 0",
           1, os.environ["MIGRATE_LOCK_KEY"], os.environ["MIGRATE_LOCK_TOKEN"])
except Exception:  # the key self-clears on its TTL — never fail the exit path
    pass
PY
}

# Re-EXPIRE by the same owner-token CAS: extending a key we no longer own would
# hand a *second* migration's window back to us.
renew_migration_lock() {
  MIGRATE_LOCK_KEY="$MIGRATE_LOCK_KEY" MIGRATE_LOCK_TOKEN="$MIGRATE_LOCK_TOKEN" \
  MIGRATE_LOCK_TTL_SECONDS="$MIGRATE_LOCK_TTL_SECONDS" \
  "$PYTHON_BIN" - <<'PY'
import os
try:
    import redis
    r = redis.Redis.from_url(os.environ["GUARD_REDIS_URL"], socket_connect_timeout=3, socket_timeout=5)
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
  MIGRATE_LOCK_KEY="$MIGRATE_LOCK_KEY" MIGRATE_LOCK_TOKEN="$MIGRATE_LOCK_TOKEN" \
  "$PYTHON_BIN" - <<'PY'
import os
try:
    import redis
    r = redis.Redis.from_url(os.environ["GUARD_REDIS_URL"], socket_connect_timeout=3, socket_timeout=5)
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

log "Migration lock: taking ${MIGRATE_LOCK_KEY} on primary Redis (${GUARD_ENDPOINT})..."
# Taking the lock BEFORE the heartbeat probe is the whole fix: probing first
# left the entire `alembic upgrade` window unguarded, so a runner that started
# in the gap migrated against a live writer (DW-3).
LOCK_STATE="$(
  MIGRATE_LOCK_KEY="$MIGRATE_LOCK_KEY" MIGRATE_LOCK_TOKEN="$MIGRATE_LOCK_TOKEN" \
  MIGRATE_LOCK_TTL_SECONDS="$MIGRATE_LOCK_TTL_SECONDS" \
  "$PYTHON_BIN" - <<'PY'
import os
try:
    import redis
    r = redis.Redis.from_url(os.environ["GUARD_REDIS_URL"], socket_connect_timeout=3, socket_timeout=5)
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

log "Backfill heartbeat guard: checking ${HEARTBEAT_KEY} on primary Redis (${GUARD_ENDPOINT})..."
HB_STATE="$(
  HEARTBEAT_KEY="$HEARTBEAT_KEY" \
  "$PYTHON_BIN" - <<'PY'
import os
try:
    import redis
    r = redis.Redis.from_url(os.environ["GUARD_REDIS_URL"], socket_connect_timeout=3, socket_timeout=5)
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
DATABASE_URL="$PRIMARY_DB_URL" \
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
