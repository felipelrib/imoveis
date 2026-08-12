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

# --- Effective enrichment routing (DW-31) -----------------------------------
# `--serve` resolves routing through AppConfig, which reads the YAML map and
# THEN lays the generic `IMOVEIS_<SECTION>__<KEY>` env overrides on top — the
# env wins (src/infra/config.py::_apply_env_overrides). The env file IS the
# unit's `EnvironmentFile=`, so both inputs reach the service and a preflight
# that reads only the YAML lies in both directions: it warned that a host
# correctly enabled through the env override "would exit at startup and restart
# forever" (DW-31). The committed YAML is deliberately all-local and pinned
# there by the suite (NFR-1), so the env override is the sanctioned surface.
#
# The precedence rule is expressed a second time here, in bash, on purpose:
# preflight must work on a host whose venv cannot import the app — that is one
# of the failures it exists to catch. Both directions are unit-tested so the
# mirror cannot drift silently.
ROUTING_ENV_PREFIX="IMOVEIS_AI__ENRICHMENT_ROUTING__"

# The runner's default scope (src/core/backfill_runner.py::DEFAULT_BACKFILL_SCOPE).
# `--serve` refuses unless EVERY class here resolves to a cloud backend AND they
# all name the SAME one (scripts/dev/backfill_gemma.py::_resolve_backfill_backend)
# — it drives one client and has no local execution mode. A preflight that
# accepted "at least one class is cloud" would certify a host that crash-loops.
BACKFILL_SCOPE_CLASSES="visual sentiment deal_verdict"
# src/core/enrichment.py: EnrichmentTaskClass / EnrichmentBackend. AppConfig
# validates against these EXACTLY (case-sensitive), so `GEMMA` or `visuals` is a
# config error at startup, not a routing choice.
KNOWN_TASK_CLASSES="visual sentiment deal_verdict valuation embedding"
CLOUD_BACKENDS="gemma gemini"
LOCAL_BACKENDS="ollama lmstudio"

_in_list() {
  case " $2 " in *" $1 "*) return 0 ;; *) return 1 ;; esac
}

is_cloud_backend() { _in_list "$1" "$CLOUD_BACKENDS"; }
is_known_backend() { _in_list "$1" "$CLOUD_BACKENDS $LOCAL_BACKENDS"; }

# Names of the enrichment-routing override variables assigned in an env file
# (one per line, deduplicated). `export`-prefixed lines are listed too — the
# preflight fails them separately, because systemd would drop them.
routing_env_keys() {
  local file="$1"
  [ -f "$file" ] || return 0
  grep -Eo "^[[:space:]]*(export[[:space:]]+)?${ROUTING_ENV_PREFIX}[A-Za-z0-9_]+=" "$file" 2>/dev/null \
    | sed -E "s/^[[:space:]]*(export[[:space:]]+)?//; s/=$//" \
    | sort -u || true
}

# `class backend` per entry of the YAML ai.enrichment_routing block.
routing_yaml_pairs() {
  local cfg="$1"
  [ -f "$cfg" ] || return 0
  awk '
    /^[[:space:]]*enrichment_routing:[[:space:]]*$/ { inblock = 1; next }
    inblock {
      if ($0 ~ /^[[:space:]]*(#|$)/) next
      if ($0 !~ /^[[:space:]][[:space:]][[:space:]][[:space:]]/) { inblock = 0; next }
      line = $0
      sub(/[[:space:]]#.*$/, "", line)
      if (line !~ /:/) next
      key = line; sub(/:.*$/, "", key)
      val = line; sub(/^[^:]*:/, "", val)
      gsub(/[[:space:]"'"'"']/, "", key)
      gsub(/[[:space:]"'"'"']/, "", val)
      if (key != "" && val != "") print tolower(key), val
    }
  ' "$cfg" || true
}

# The backend one task class effectively resolves to: the env-file override when
# it sets one (the env layer is applied last and wins), else the YAML value.
# Empty output = the class is routed nowhere.
routing_effective_value() {
  local cfg="$1" file="${2-}" want="$3" key value pair_class pair_value
  for key in $(routing_env_keys "$file"); do
    if [ "$(printf '%s' "${key#"$ROUTING_ENV_PREFIX"}" | tr '[:upper:]' '[:lower:]')" = "$want" ]; then
      value="$(env_value_of "$file" "$key" || true)"
      printf '%s' "$value"
      return 0
    fi
  done
  while read -r pair_class pair_value; do
    [ "$pair_class" = "$want" ] || continue
    printf '%s' "$pair_value"
    return 0
  done <<EOF
$(routing_yaml_pairs "$cfg")
EOF
  return 0
}

# Verdict on the EFFECTIVE routing map (YAML overlaid with the env file's
# overrides), expressed the way `--serve` expresses it: every scoped class cloud,
# all on the same backend. Prints `ok <backend>`, `local <classes>` or
# `mixed <class>=<backend>,…`; exit status is 0 only for `ok`.
routing_scope_verdict() {
  local cfg="$1" file="${2-}" class value local_classes="" detail="" backends=""
  for class in $BACKFILL_SCOPE_CLASSES; do
    value="$(routing_effective_value "$cfg" "$file" "$class")"
    detail="${detail}${detail:+,}${class}=${value:-<unset>}"
    if is_cloud_backend "$value"; then
      _in_list "$value" "$backends" || backends="${backends}${backends:+ }${value}"
    else
      local_classes="${local_classes}${local_classes:+ }${class}"
    fi
  done
  if [ -n "$local_classes" ]; then
    printf 'local %s' "$local_classes"
    return 1
  fi
  if [ "$(printf '%s' "$backends" | wc -w)" -gt 1 ]; then
    printf 'mixed %s' "$detail"
    return 1
  fi
  printf 'ok %s' "$backends"
  return 0
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
    # Routing overrides: the same `export` trap one layer down, plus the two
    # ways an override is syntactically fine for systemd and still fatal for
    # AppConfig. Its validators are case-SENSITIVE and reject unknown names, so
    # `GEMMA`, `gemma1` or a misspelled class is a ConfigError at startup — a
    # crash loop a preflight that only asked "does it look cloud?" would miss.
    local rvalue rclass
    for key in $(routing_env_keys "$ENV_FILE"); do
      if env_key_uses_export "$ENV_FILE" "$key"; then
        fatal "$ENV_FILE sets $key with 'export'. systemd's EnvironmentFile= is not a shell:"
        fatal "it does not strip 'export', so this routing override would be unset in the"
        fatal "service, the runner would fall back to the all-local $CONFIG_REL map and exit"
        fatal "at startup. Drop the 'export '."
      fi
      rclass="$(printf '%s' "${key#"$ROUTING_ENV_PREFIX"}" | tr '[:upper:]' '[:lower:]')"
      if ! _in_list "$rclass" "$KNOWN_TASK_CLASSES"; then
        fatal "$key names '$rclass', which is not an enrichment task class. AppConfig would"
        fatal "reject the map at startup. Known classes: $KNOWN_TASK_CLASSES."
      fi
      rvalue="$(env_value_of "$ENV_FILE" "$key" || true)"
      if [ -z "$rvalue" ]; then
        fatal "$key is empty. An empty override still replaces the $CONFIG_REL value, and"
        fatal "AppConfig rejects '' as a backend — the supervisor would exit at startup."
      elif ! is_known_backend "$rvalue"; then
        fatal "$key is '$rvalue', which is not a known backend (case-sensitive)."
        fatal "Valid: $CLOUD_BACKENDS (cloud) or $LOCAL_BACKENDS (local)."
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

  if [ ! -f "$CONFIG_FILE" ]; then
    fatal "Config not found: $CONFIG_FILE — routing cannot be resolved (wrong --repo-root?)."
  else
    local verdict
    verdict="$(routing_scope_verdict "$CONFIG_FILE" "$ENV_FILE")" || true
    case "$verdict" in
      ok\ *)
        log "Effective backfill routing: ${verdict#ok } for $BACKFILL_SCOPE_CLASSES ($CONFIG_REL + $ENV_FILE)"
        ;;
      mixed\ *)
        warn "The backfill scope mixes cloud backends (${verdict#mixed }). One run drives one"
        warn "client, so --serve refuses and the unit would restart forever. Route every class"
        warn "in '$BACKFILL_SCOPE_CLASSES' to the SAME backend."
        ;;
      *)
        warn "These scoped task classes do not resolve to a cloud backend on this host:"
        warn "  ${verdict#local }"
        warn "--serve needs EVERY class in '$BACKFILL_SCOPE_CLASSES' cloud-routed (it drives one"
        warn "client and has no local mode); it validates that before polling, so the unit"
        warn "would exit at startup and restart forever. $CONFIG_REL is all-local by design —"
        warn "enable the cloud backfill PER HOST, in $ENV_FILE:"
        warn "  ${ROUTING_ENV_PREFIX}VISUAL=gemma"
        warn "  ${ROUTING_ENV_PREFIX}SENTIMENT=gemma"
        warn "  ${ROUTING_ENV_PREFIX}DEAL_VERDICT=gemma"
        warn "Do NOT edit ai.enrichment_routing in the committed $CONFIG_REL: it is pinned"
        warn "all-local by the test suite (NFR-1), so that edit turns the merge gate red."
        ;;
    esac
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
    warn "Usual causes: no ${ROUTING_ENV_PREFIX}* override in $ENV_FILE (routing"
    warn "resolves all-local), or GEMINI_API_KEY/DATABASE_URL are wrong for this host."
    warn "Last journal lines:"
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
