#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# scripts/agent/lib.sh — shared helpers for the remaining bash scripts
# (migrate-primary.sh, gen-docs.sh, validate.sh wrapper, scripts/ops/*).
#
# The gate itself is scripts/agent/validate.py (Python, cross-platform). This
# file keeps only: repo roots, logging, host-Python discovery, the DW-33
# workspace-env allowlist loader, the compose shim and project-name sanitizing.
# The parallel-worktree registry, port allocation, branch-name validation and
# docs-only detection were retired with finish-feature.sh (ADR 0007).
# ---------------------------------------------------------------------------
set -euo pipefail
# --- Resolve repo roots -----------------------------------------------------
# REPO_ROOT   : the CURRENT working tree (may be a worktree).
# PRIMARY_ROOT: the main checkout that owns .git — where the shared registry lives.
REPO_ROOT="$(git rev-parse --show-toplevel)"
# Ask Git for both absolute paths: mixing Git's C:/... with MSYS pwd's /c/...
# incorrectly identifies a Windows primary checkout as a linked worktree.
_common_git="$(git rev-parse --path-format=absolute --git-common-dir)"
PRIMARY_ROOT="$(dirname "$_common_git")"


in_linked_worktree() {
  [ "$REPO_ROOT" != "$PRIMARY_ROOT" ]
}

# --- Logging ----------------------------------------------------------------
_c() { printf '\033[%sm' "$1"; }
log()   { printf '%s> %s%s\n' "$(_c 36)" "$*" "$(_c 0)"; }
ok()    { printf '%s  [OK] %s%s\n' "$(_c 32)" "$*" "$(_c 0)"; }
warn()  { printf '%s  [WARN] %s%s\n' "$(_c 33)" "$*" "$(_c 0)"; }
die()   { printf '%s  [FAIL] %s%s\n' "$(_c 31)" "$*" "$(_c 0)" >&2; exit 1; }

# --- Host Python -----------------------------------------------------------
# Select an executable interpreter, not a WindowsApps alias that only exists.
# Linked worktrees can use the primary venv without Windows symlink privileges.
activate_project_python() {
  local candidate platform tools_dir
  local candidates=()
  case "${OSTYPE:-}" in
    msys*)
      candidates=("$REPO_ROOT/.venv/Scripts/python.exe" "$PRIMARY_ROOT/.venv/Scripts/python.exe" python python3)
      ;;
    *)
      candidates=("$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/.venv/bin/python3"
                  "$PRIMARY_ROOT/.venv/bin/python" python3 python)
      ;;
  esac
  PYTHON_BIN=""
  PYTHON_PLATFORM=""
  for candidate in "${candidates[@]}"; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    platform="$("$candidate" -c 'import sys; print(sys.platform)' 2>/dev/null)" || continue
    platform="${platform%$'\r'}"
    # A Windows gate must never silently delegate host execution to WSL.
    case "${OSTYPE:-}:$platform" in msys*:win32) ;; msys*:*) continue ;; esac
    PYTHON_BIN="$(command -v "$candidate")"
    PYTHON_PLATFORM="$platform"
    tools_dir="$(dirname "$PYTHON_BIN")"
    case "${OSTYPE:-}" in msys*) tools_dir="$(cygpath -u "$tools_dir")" ;; esac
    export PATH="$tools_dir:$PATH"
    # Committed source/config is UTF-8 on both platforms, including subprocesses.
    export PYTHONUTF8=1
    export PYTHON_BIN PYTHON_PLATFORM
    return 0
  done
  return 1
}

# Native Python uses semicolons; MSYS's implicit conversion cannot handle a
# POSIX path prepended to an inherited C:\... list. Convert only our new entry.
prepend_python_path() {
  local entry="$1" separator=:
  if [ "${PYTHON_PLATFORM:-}" = win32 ]; then
    entry="$(cygpath -m "$entry")"
    separator=';'
  fi
  export PYTHONPATH="${entry}${PYTHONPATH:+${separator}${PYTHONPATH}}"
}

# --- Workspace env: default-deny allowlist (DW-33) --------------------------
# `.env.local` is dual-purpose: it carries this workspace's compose/port
# identity AND it is the systemd `EnvironmentFile=` of the host-side cloud
# backfill runner (ADR 0006, story v0.13-s3.1). A wholesale `set -a; source`
# therefore hands the operator's whole runner contract — GEMINI_API_KEY, the
# PRIMARY DATABASE_URL, any `IMOVEIS_<SECTION>__<KEY>` config override — to the
# gate process, where it silently rewrites config underneath pytest (DW-33:
# three routing overrides made an unrelated Redis test fail on a partial
# routing map). The gate reads ONLY the workspace-identity keys below.
#
# Default-deny on purpose: a variable an operator adds to `.env.local` tomorrow
# does not reach the gate unless it is listed here. Adding a key is a
# deliberate decision — never DATABASE_URL, REDIS_URL, GEMINI_API_KEY or
# anything IMOVEIS_*: the test DB/Redis URLs come from the ephemeral test stack
# (test-stack.sh), and the config-override channel must stay out of pytest.
#
# Scope: validate.py carries the same allowlist in Python (pinned equal by a
# unit test); migrate-primary.sh re-sources the file itself and keeps full access.
WORKSPACE_ENV_ALLOWLIST="COMPOSE_PROJECT_NAME
POSTGRES_PORT
POSTGRES_USER
POSTGRES_PASSWORD
POSTGRES_DB
POSTGRES_TEST_DB
REDIS_PORT
REDIS_TEST_DB
API_PORT
FRONTEND_PORT
PLAYWRIGHT_PORT
PLAYWRIGHT_BASE_URL
API_KEY
JWT_SECRET
TEST_DATABASE_URL"

# load_workspace_env [env-file]
# Export the allowlisted assignments from an env file (default: the workspace's
# `.env.local`). Last assignment of a key wins; surrounding quotes, a trailing
# CR and an inline comment (after the closing quote, or after whitespace on an
# unquoted value) are stripped; values are taken LITERALLY (no shell expansion,
# no command substitution — this is not `source`).
# A missing file is a no-op, never an error; an unreadable one warns and is
# skipped (the gate must still run — it has its own defaults for every key).
load_workspace_env() {
  local file="${1:-$REPO_ROOT/.env.local}"
  [ -f "$file" ] || return 0
  if [ ! -r "$file" ]; then
    # Without this the greps below fail one by one, printing permission errors
    # and leaving the gate to run on defaults with no explanation.
    warn "$file exists but is not readable — skipping it; the gate falls back to its defaults." >&2
    return 0
  fi
  local key line value
  while IFS= read -r key; do
    [ -n "$key" ] || continue
    line="$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}=" "$file" | tail -n 1 || true)"
    [ -n "$line" ] || continue
    line="${line%$'\r'}"
    value="${line#*=}"
    value="${value#"${value%%[![:space:]]*}"}"   # ltrim
    value="${value%"${value##*[![:space:]]}"}"   # rtrim
    case "$value" in
      # Quoted: the value ends at its CLOSING quote and whatever follows is an
      # inline comment — `API_KEY="k" # generated` is the value `k`, exactly as
      # `set -a; source` and Compose's dotenv parser read it. A '#' *inside* the
      # quotes stays part of the value. (Stripping comments first would eat a
      # quoted '#'; matching the quotes first, as this does, keeps both cases
      # right — an unterminated quote falls through to the unquoted branch.)
      '"'*'"'*) value="${value#\"}"; value="${value%%\"*}" ;;
      "'"*"'"*) value="${value#\'}"; value="${value%%\'*}" ;;
      *)
        # Unquoted: a whitespace-preceded '#' starts an inline comment, so
        # `REDIS_PORT=6379 # default` is the value 6379.
        value="$(printf '%s' "$value" | sed -e 's/[[:space:]]\{1,\}#.*$//' -e 's/[[:space:]]*$//')"
        ;;
    esac
    export "$key=$value"
  done <<< "$WORKSPACE_ENV_ALLOWLIST"
  return 0
}

# --- docker compose shim (v2 plugin preferred, v1 fallback) -----------------
dc() {
  if docker compose version >/dev/null 2>&1; then docker compose "$@"
  else docker-compose "$@"; fi
}

# --- Project naming --------------------------------------------------------
current_branch() { git rev-parse --abbrev-ref HEAD; }

# Docker project names must be lowercase alnum + dashes.
sanitize_proj() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g'
}
