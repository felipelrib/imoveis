#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# scripts/install-backfill-runner.sh — operator installer for the cloud
# backfill supervisor's systemd unit (ADR 0006, story v0.13-s3.1).
#
# Renders deploy/systemd/imoveis-backfill-serve.service.in for THIS host,
# preflights the env contract the runner needs, and installs / enables /
# uninstalls the unit. Without it, `POST /admin/backfill/start` only records a
# request that nothing consumes (DW-27).
#
# Modes:
#   (default)     render + preflight + install + enable + restart   [needs sudo]
#   --print       render to stdout only (warnings only, no privilege)
#   --check       preflight only, no rendering, no privilege
#   --uninstall   disable + stop + remove the unit                  [needs sudo]
#   --status      systemctl status for the unit (non-zero when not installed)
#   --help        this text
#
# Overrides: --user --python --env-file --repo-root --unit-name
#
# --force        downgrade every preflight FAILURE to a warning and carry on.
#                For hosts that configure the key/DB outside the env file (see
#                IMOVEIS_<SECTION>__<KEY> in src/infra/config.py). It also
#                overrides the linked-worktree refusal — only do that knowing
#                the unit dies with the worktree.
#
# This script performs NO container-stack action of any kind (no compose, no
# container CLI): the primary stack stays inviolable, and so does every gate.
# Secrets are never read back, printed or logged — only variable NAMES appear.
# ---------------------------------------------------------------------------
set -euo pipefail

# --- Logging (stderr; stdout is reserved for the rendered unit) -------------
# Colour only when stderr is a terminal: a captured log or a journal entry must
# not carry escape sequences.
if [ -t 2 ]; then
  _c() { printf '\033[%sm' "$1"; }
else
  _c() { :; }
fi
log()  { printf '%s> %s%s\n' "$(_c 36)" "$*" "$(_c 0)" >&2; }
ok()   { printf '%s  [OK] %s%s\n' "$(_c 32)" "$*" "$(_c 0)" >&2; }
warn() { printf '%s  [WARN] %s%s\n' "$(_c 33)" "$*" "$(_c 0)" >&2; }
err()  { printf '%s  [FAIL] %s%s\n' "$(_c 31)" "$*" "$(_c 0)" >&2; }
die()  { err "$*"; exit 1; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Defaults ---------------------------------------------------------------
DEFAULT_UNIT_NAME="imoveis-backfill-serve.service"
# Floor for TimeoutStopSec; raised to the configured lease TTL when that is
# larger, so a stop can never SIGKILL a run that still holds its lease.
FLOOR_TIMEOUT_STOP=900
RUNNER_REL="scripts/dev/backfill_gemma.py"
TEMPLATE_REL="deploy/systemd/imoveis-backfill-serve.service.in"
CONFIG_REL="configs/app_config.yaml"
DEFAULT_REDIS_PORT=6379
DEFAULT_DB_NAME="imoveis"

MODE="install"
REPO_ROOT=""
RUN_USER=""
PYTHON_BIN=""
ENV_FILE=""
UNIT_NAME="$DEFAULT_UNIT_NAME"
FORCE=0

# The help text IS this file's header comment block — derived from its `# ---`
# delimiters, never from a hardcoded line range that drifts into source code.
usage() {
  awk '
    NR == 1 { next }
    /^# -{10,}/ { if (started) exit; started = 1; next }
    started && /^#/ { sub(/^# ?/, ""); print; next }
    started { exit }
  ' "${BASH_SOURCE[0]}"
}

# --- Argument parsing -------------------------------------------------------
# An option whose value is missing (last argument) or is itself an option must
# fail loudly: `--user --check` silently swallowing a flag is how a unit ends up
# running as the wrong user.
require_value() {
  local flag="$1" argc="$2" value="${3-}"
  [ "$argc" -ge 2 ] || die "$flag requires a value, but none was given. Try --help."
  case "$value" in
    "")  die "$flag requires a non-empty value. Try --help." ;;
    --*) die "$flag requires a value, but the next argument is the option '$value'. Try --help." ;;
  esac
}

while [ $# -gt 0 ]; do
  case "$1" in
    --print)     MODE="print" ;;
    --check)     MODE="check" ;;
    --uninstall) MODE="uninstall" ;;
    --status)    MODE="status" ;;
    --install)   MODE="install" ;;
    --force)     FORCE=1 ;;
    --help|-h)   usage; exit 0 ;;
    --user)      require_value "$1" "$#" "${2-}"; RUN_USER="$2"; shift ;;
    --python)    require_value "$1" "$#" "${2-}"; PYTHON_BIN="$2"; shift ;;
    --env-file)  require_value "$1" "$#" "${2-}"; ENV_FILE="$2"; shift ;;
    --repo-root) require_value "$1" "$#" "${2-}"; REPO_ROOT="$2"; shift ;;
    --unit-name) require_value "$1" "$#" "${2-}"; UNIT_NAME="$2"; shift ;;
    --user=*)      RUN_USER="${1#*=}" ;;
    --python=*)    PYTHON_BIN="${1#*=}" ;;
    --env-file=*)  ENV_FILE="${1#*=}" ;;
    --repo-root=*) REPO_ROOT="${1#*=}" ;;
    --unit-name=*) UNIT_NAME="${1#*=}" ;;
    *) die "Unknown argument: $1 (try --help)" ;;
  esac
  shift
done

# --- Resolve paths ----------------------------------------------------------
# systemd rejects a relative ExecStart / EnvironmentFile, so every path the unit
# will carry is absolutised here, against the invoking CWD.
absolutize() {
  case "$1" in
    /*) printf '%s' "$1" ;;
    *)  printf '%s/%s' "$(pwd)" "$1" ;;
  esac
}

if [ -z "$REPO_ROOT" ]; then
  REPO_ROOT="$(cd "$HERE/.." && pwd)"
else
  [ -d "$REPO_ROOT" ] || die "--repo-root does not exist: $REPO_ROOT"
  REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"
fi

# The unit name becomes a root-written path under /etc/systemd/system: it must
# be a bare unit name, never a path fragment.
case "$UNIT_NAME" in
  "") die "--unit-name must not be empty" ;;
  *[!A-Za-z0-9._@-]*)
    die "--unit-name may only contain [A-Za-z0-9._@-] (no '/', no path segments): $UNIT_NAME" ;;
esac
case "$UNIT_NAME" in
  *.service) ;;
  *) UNIT_NAME="${UNIT_NAME}.service" ;;
esac
UNIT_PATH="/etc/systemd/system/${UNIT_NAME}"

[ -n "$RUN_USER" ]   || RUN_USER="${SUDO_USER:-$(id -un)}"
[ -n "$PYTHON_BIN" ] || PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
[ -n "$ENV_FILE" ]   || ENV_FILE="$REPO_ROOT/.env.local"
PYTHON_BIN="$(absolutize "$PYTHON_BIN")"
ENV_FILE="$(absolutize "$ENV_FILE")"

TEMPLATE="$REPO_ROOT/$TEMPLATE_REL"
RUNNER="$REPO_ROOT/$RUNNER_REL"
CONFIG_FILE="$REPO_ROOT/$CONFIG_REL"

# --- Preflight helpers ------------------------------------------------------
PREFLIGHT_FAILED=0
# Fatal in install/check, advisory in --print (rendering needs no live host) and
# under --force (the operator owns the consequences).
fatal() {
  if [ "$MODE" = "print" ] || [ "$FORCE" -eq 1 ]; then
    warn "$*"
  else
    err "$*"
    PREFLIGHT_FAILED=1
  fi
}

# A linked git worktree has a `.git` FILE (`gitdir: …`), not a directory. Its
# path is disposable — `teardown.sh --remove` deletes it — so a unit pinned to
# it would silently stop working. Emits through the caller's reporter and
# returns 0 when REPO_ROOT is such a worktree.
worktree_finding() {
  local emit="$1" dotgit="$REPO_ROOT/.git" gitdir primary
  [ -f "$dotgit" ] || return 1
  gitdir="$(sed -n 's/^gitdir:[[:space:]]*//p' "$dotgit" | head -n 1)"
  primary="unknown (run: git worktree list)"
  case "$gitdir" in
    */.git/worktrees/*) primary="${gitdir%%/.git/worktrees/*}" ;;
  esac
  "$emit" "$REPO_ROOT is a linked git worktree (its .git is a file, not a directory)."
  "$emit" "Worktrees are disposable — teardown.sh --remove deletes this path and the"
  "$emit" "unit would point at nothing. Run this from the primary checkout instead:"
  "$emit" "  $primary"
  return 0
}

systemd_available() {
  [ "$(ps -p 1 -o comm= 2>/dev/null | tr -d '[:space:]')" = "systemd" ] && return 0
  command -v systemctl >/dev/null 2>&1 && systemctl list-units --no-pager >/dev/null 2>&1 && return 0
  return 1
}

# Last assignment of KEY in an env file, quotes and inline comment stripped.
# NEVER logged/printed by any caller — only used to test emptiness, compare a
# port number or inspect a URL's database component.
env_value_of() {
  local file="$1" key="$2" line value
  [ -f "$file" ] || return 1
  line="$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}=" "$file" | tail -n 1 || true)"
  [ -n "$line" ] || return 1
  line="${line%$'\r'}"
  value="${line#*=}"
  value="$(printf '%s' "$value" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  case "$value" in
    '"'*'"') value="${value#\"}"; value="${value%\"}" ;;
    "'"*"'") value="${value#\'}"; value="${value%\'}" ;;
    *)
      # Unquoted: a whitespace-preceded '#' starts an inline comment, so
      # `REDIS_PORT=6379 # default` is the value 6379, not "6379 # default".
      value="$(printf '%s' "$value" | sed -e 's/[[:space:]]\{1,\}#.*$//' -e 's/[[:space:]]*$//')"
      ;;
  esac
  printf '%s' "$value"
}

env_key_is_set() {
  local value
  value="$(env_value_of "$1" "$2")" || return 1
  [ -n "$value" ]
}

# systemd's EnvironmentFile= is NOT a shell: it does not strip `export`, so
# `export KEY=…` leaves the variable unset in the service.
env_key_uses_export() {
  grep -Eq "^[[:space:]]*export[[:space:]]+$2=" "$1"
}

env_file_has_cr() {
  grep -q $'\r' "$1"
}

# True when DATABASE_URL's database component is the config default `imoveis`
# rather than the primary stack's `realestate`. The value itself never leaves
# this function.
env_db_is_config_default() {
  local url dbname
  url="$(env_value_of "$1" DATABASE_URL)" || return 1
  dbname="${url##*/}"
  dbname="${dbname%%\?*}"
  [ "$dbname" = "$DEFAULT_DB_NAME" ]
}

# True when ai.enrichment_routing routes at least one task class to a cloud
# backend. `--serve` validates routing BEFORE its poll loop and exits when no
# scope is cloud, so an all-local host would crash-loop under Restart=always.
routing_has_cloud_backend() {
  local cfg="$1"
  [ -f "$cfg" ] || return 1
  awk '
    /^[[:space:]]*enrichment_routing:[[:space:]]*$/ { inblock = 1; next }
    inblock {
      if ($0 ~ /^[[:space:]]*(#|$)/) next
      if ($0 !~ /^[[:space:]][[:space:]][[:space:]][[:space:]]/) { inblock = 0; next }
      if ($0 ~ /:[[:space:]]*(gemma|gemini)([[:space:]]|#|$)/) found = 1
    }
    END { exit(found ? 0 : 1) }
  ' "$cfg"
}

# TimeoutStopSec must be >= backfill.lease_ttl_seconds so a stop never SIGKILLs
# a lease-holding run mid-property. Scoped to the `backfill:` block — another
# section gaining a `lease_ttl_seconds` key must not change the stop timeout.
resolve_timeout_stop() {
  local ttl=""
  if [ -f "$CONFIG_FILE" ]; then
    ttl="$(awk '
      /^backfill:[[:space:]]*(#.*)?$/ { inblock = 1; next }
      inblock {
        if ($0 ~ /^[[:space:]]*(#|$)/) next
        if ($0 !~ /^[[:space:]]/) { inblock = 0; next }
        if ($0 ~ /^[[:space:]]+lease_ttl_seconds:[[:space:]]*[0-9]+/) {
          sub(/^[[:space:]]+lease_ttl_seconds:[[:space:]]*/, "")
          sub(/[^0-9].*$/, "")
          print
          exit
        }
      }
    ' "$CONFIG_FILE" || true)"
  fi
  case "$ttl" in
    ''|*[!0-9]*) ttl=0 ;;
  esac
  if [ "$ttl" -gt "$FLOOR_TIMEOUT_STOP" ]; then
    printf '%s' "$ttl"
  else
    printf '%s' "$FLOOR_TIMEOUT_STOP"
  fi
}

preflight() {
  worktree_finding fatal || true

  if ! systemd_available; then
    fatal "systemd is not available (PID 1 is not systemd and systemctl is unusable)."
    fatal "On WSL2, enable it: put 'systemd=true' under [boot] in /etc/wsl.conf, then 'wsl --shutdown'."
  fi

  if [ ! -x "$PYTHON_BIN" ]; then
    fatal "Python interpreter not found or not executable: $PYTHON_BIN"
    fatal "Create the repo virtualenv first (bash scripts/setup.sh), or pass --python <path>."
  fi

  if [ ! -f "$RUNNER" ]; then
    fatal "Backfill runner not found: $RUNNER (ExecStart would point at nothing)."
  elif ! grep -q -- '--serve' "$RUNNER"; then
    fatal "$RUNNER no longer mentions --serve; the unit's ExecStart is stale."
  fi

  if ! id -u "$RUN_USER" >/dev/null 2>&1; then
    warn "No such user on this host: $RUN_USER — systemd would refuse to start the unit."
    warn "Pass --user <existing user> (the operator account that owns the repo .venv)."
  elif [ "$(id -u "$RUN_USER")" -eq 0 ]; then
    warn "The unit would run as root ($RUN_USER). The supervisor only needs the operator"
    warn "account that owns the repo and its .venv — pass --user <operator>."
  fi

  if [ ! -f "$ENV_FILE" ]; then
    fatal "Env file not found: $ENV_FILE (copy .env.local.example and fill it in)."
  else
    if env_file_has_cr "$ENV_FILE"; then
      fatal "$ENV_FILE has CRLF line endings. systemd's EnvironmentFile= keeps the trailing"
      fatal "carriage return in every value, so the runner would see corrupt URLs and keys."
      fatal "Convert it to LF (dos2unix, or 'sed -i \$'s/\\r\$//' <file>')."
    fi
    local key
    for key in GEMINI_API_KEY DATABASE_URL; do
      if env_key_uses_export "$ENV_FILE" "$key"; then
        fatal "$ENV_FILE sets $key with 'export'. systemd's EnvironmentFile= is not a shell:"
        fatal "it does not strip 'export', so $key would be unset in the service and the"
        fatal "supervisor would crash-loop with a certified-OK install. Drop the 'export '."
      elif ! env_key_is_set "$ENV_FILE" "$key"; then
        fatal "$ENV_FILE does not set a non-empty $key — the supervisor would exit at startup."
      fi
    done
    if env_db_is_config_default "$ENV_FILE"; then
      warn "$ENV_FILE points DATABASE_URL at database '$DEFAULT_DB_NAME' — that is the config"
      warn "default, not the primary stack's 'realestate'. The runner would enrich a"
      warn "different (probably empty) database. This is the exact reason DATABASE_URL is required."
    fi
    local redis_port
    redis_port="$(env_value_of "$ENV_FILE" REDIS_PORT || true)"
    if [ -n "$redis_port" ] && [ "$redis_port" != "$DEFAULT_REDIS_PORT" ] \
       && ! env_key_is_set "$ENV_FILE" REDIS_URL; then
      warn "$ENV_FILE sets a non-default REDIS_PORT but no REDIS_URL — the runner would"
      warn "talk to the default Redis instead of this host's published one."
    fi
  fi

  if ! routing_has_cloud_backend "$CONFIG_FILE"; then
    warn "ai.enrichment_routing in $CONFIG_REL routes no task class to gemma/gemini."
    warn "--serve validates routing before polling, so the unit would exit at startup and"
    warn "restart forever. Set visual/sentiment/deal_verdict to gemma (or gemini) first."
  fi

  if [ "$PREFLIGHT_FAILED" -ne 0 ]; then
    err "Preflight failed. Fix the items above, or re-run with --force to install anyway."
    exit 1
  fi
}

# --- Rendering --------------------------------------------------------------
# Escape a replacement for `sed s|…|…|`: an unescaped '&' re-expands the whole
# match (a --user 'a&b' rendered as 'a@@USER@@b'), '|' ends the expression and a
# backslash starts an escape.
sed_escape() {
  printf '%s' "$1" | sed -e 's/[\\|&]/\\&/g'
}

render_unit() {
  [ -f "$TEMPLATE" ] || die "Unit template missing: $TEMPLATE"
  local timeout_stop rendered leftovers
  timeout_stop="$(resolve_timeout_stop)"
  rendered="$(sed \
    -e "s|@@USER@@|$(sed_escape "$RUN_USER")|g" \
    -e "s|@@REPO_ROOT@@|$(sed_escape "$REPO_ROOT")|g" \
    -e "s|@@PYTHON@@|$(sed_escape "$PYTHON_BIN")|g" \
    -e "s|@@ENV_FILE@@|$(sed_escape "$ENV_FILE")|g" \
    -e "s|@@TIMEOUT_STOP@@|$(sed_escape "$timeout_stop")|g" \
    "$TEMPLATE")"
  leftovers="$(printf '%s\n' "$rendered" | grep -o '@@[A-Za-z0-9_]*@@' | sort -u | tr '\n' ' ' || true)"
  if [ -n "$leftovers" ]; then
    die "Render incomplete — the unit still carries placeholder(s): ${leftovers% }. Installing it would give systemd a literal @@…@@ value."
  fi
  printf '%s\n' "$rendered"
}

require_privilege() {
  SUDO=""
  if [ "$(id -u)" -ne 0 ]; then
    command -v sudo >/dev/null 2>&1 \
      || die "This step writes to /etc/systemd/system and needs root, but sudo is not available. Re-run as root."
    SUDO="sudo"
  fi
}

# Only one supervisor may beat backfill:gemma:supervisor:active.
warn_on_running_supervisor() {
  command -v pgrep >/dev/null 2>&1 || return 0
  if pgrep -f 'backfill_gemma\.py --serve' >/dev/null 2>&1; then
    warn "A 'backfill_gemma.py --serve' process is already running on this host (hand-started?)."
    warn "Stop it before the unit takes over — two supervisors would fight over the same"
    warn "lease and both beat backfill:gemma:supervisor:active."
  fi
}

# --- Modes ------------------------------------------------------------------
do_print() {
  preflight
  render_unit
}

do_check() {
  preflight
  if [ "$FORCE" -eq 1 ]; then
    ok "Preflight completed with warnings only (--force) — $UNIT_NAME can be installed from $REPO_ROOT"
  else
    ok "Preflight passed — ready to install $UNIT_NAME from $REPO_ROOT"
  fi
}

do_install() {
  preflight
  warn_on_running_supervisor
  require_privilege

  local tmp
  tmp="$(mktemp)"
  # shellcheck disable=SC2064
  trap "rm -f '$tmp'" EXIT
  render_unit >"$tmp"

  log "Installing $UNIT_PATH"
  $SUDO install -m 0644 "$tmp" "$UNIT_PATH"
  $SUDO systemctl daemon-reload
  # enable, then restart — deliberately NOT enable with `--now`, whose start is a
  # no-op on an already-active unit: a re-install after a repo move or an
  # interpreter change would leave the OLD ExecStart and env running. restart
  # both starts a stopped unit and reloads a running one.
  $SUDO systemctl enable "$UNIT_NAME"
  $SUDO systemctl restart "$UNIT_NAME"
  log "$UNIT_NAME installed and enabled; waiting for it to settle…"

  sleep 3
  if $SUDO systemctl is-active --quiet "$UNIT_NAME"; then
    ok "$UNIT_NAME is active"
  else
    warn "$UNIT_NAME is NOT active a few seconds after start — it is probably crash-looping."
    warn "Usual causes: ai.enrichment_routing is all-local, or GEMINI_API_KEY/DATABASE_URL"
    warn "are wrong for this host. Last journal lines:"
    $SUDO journalctl -u "$UNIT_NAME" -n 20 --no-pager >&2 || true
  fi

  log "Next:"
  log "  systemctl status $UNIT_NAME"
  log "  journalctl -u $UNIT_NAME -f"
  log "Re-run this script after a repo move, an interpreter change or an upgrade."
}

do_uninstall() {
  # No worktree guard here: the unit lives in /etc, not in the repo, and a moved
  # or deleted checkout is exactly when uninstall is most needed.
  require_privilege

  # Every step tolerates absence: an already-removed unit is not an error.
  $SUDO systemctl disable --now "$UNIT_NAME" >/dev/null 2>&1 || true
  if [ -f "$UNIT_PATH" ]; then
    $SUDO rm -f "$UNIT_PATH"
    log "Removed $UNIT_PATH"
  else
    log "$UNIT_PATH was already absent"
  fi
  $SUDO systemctl daemon-reload
  ok "$UNIT_NAME uninstalled (a run already in flight keeps its lease until it drains)"
}

do_status() {
  command -v systemctl >/dev/null 2>&1 || die "systemctl is not available on this host."
  if [ ! -f "$UNIT_PATH" ]; then
    err "$UNIT_PATH does not exist — the supervisor has never been installed on this host."
    err "That is the DW-27 state: Start in Operações only records a request nothing consumes."
    err "Install it with: bash scripts/install-backfill-runner.sh"
    exit 1
  fi
  systemctl status --no-pager "$UNIT_NAME" || true
  log "Note: this shows the UNIT's state only. The admin API's runner_present comes from"
  log "Redis (lease held OR the backfill:gemma:supervisor:active heartbeat) and is not read"
  log "by this script — a unit that is 'active' but wedged can still report absent there."
}

case "$MODE" in
  print)     do_print ;;
  check)     do_check ;;
  install)   do_install ;;
  uninstall) do_uninstall ;;
  status)    do_status ;;
  *)         die "Unknown mode: $MODE" ;;
esac
