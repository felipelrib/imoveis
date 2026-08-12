#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# scripts/agent/lib.sh — shared helpers for the parallel-agent workflow.
#
# Sourced by every scripts/agent/*.sh. Designed for Git Bash on Windows and
# any POSIX bash. Keeps all fiddly determinism (port math, project naming,
# race-free registry) OUT of the LLM so small local models just call scripts.
# ---------------------------------------------------------------------------
set -euo pipefail

# --- Resolve repo roots -----------------------------------------------------
# REPO_ROOT   : the CURRENT working tree (may be a worktree).
# PRIMARY_ROOT: the main checkout that owns .git — where the shared registry lives.
REPO_ROOT="$(git rev-parse --show-toplevel)"
# `git rev-parse --git-common-dir` points at the shared .git; its parent is primary.
_common_git="$(git rev-parse --git-common-dir)"
case "$_common_git" in
  /*|[A-Za-z]:*) PRIMARY_ROOT="$(dirname "$_common_git")" ;;
  *)             PRIMARY_ROOT="$(cd "$REPO_ROOT/$(dirname "$_common_git")" && pwd)" ;;
esac

# Port/session registry (user-writable). Nested `.worktrees/` is legacy/root-owned —
# sibling dirs `../<repo>-wt-<slug>` are used for parallel isolation instead.
REGISTRY_DIR="$PRIMARY_ROOT/.agent-workspaces"
REGISTRY_FILE="$REGISTRY_DIR/registry.tsv"     # branch <tab> proj <tab> pg <tab> redis <tab> api <tab> fe <tab> path
REGISTRY_LOCK="$REGISTRY_DIR/.lock"            # mkdir-based lock (atomic, portable)
WORKTREE_PARENT="$(dirname "$PRIMARY_ROOT")"
PRIMARY_BASENAME="$(basename "$PRIMARY_ROOT")"

# Absolute path for a parallel worktree: sibling of the primary checkout.
worktree_path_for_slug() {
  printf '%s/%s-wt-%s' "$WORKTREE_PARENT" "$PRIMARY_BASENAME" "$1"
}

primary_branch() {
  git -C "$PRIMARY_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown"
}

# Idle = primary on main/master AND clean working tree.
# Agents treat a non-idle primary as "another agent is using this checkout" → use a worktree.
primary_is_idle() {
  local b
  b="$(primary_branch)"
  case "$b" in
    main|master) ;;
    *) return 1 ;;
  esac
  [ -z "$(git -C "$PRIMARY_ROOT" status --porcelain --untracked-files=no 2>/dev/null)" ] || return 1
  return 0
}

# List absolute paths of linked worktrees other than PRIMARY_ROOT (one per line).
other_worktree_paths() {
  git -C "$PRIMARY_ROOT" worktree list --porcelain 2>/dev/null \
    | awk -v primary="$PRIMARY_ROOT" '
        /^worktree / {
          p = substr($0, 10)
          if (p != primary) print p
        }'
}

in_linked_worktree() {
  [ "$REPO_ROOT" != "$PRIMARY_ROOT" ]
}

# --- Logging ----------------------------------------------------------------
_c() { printf '\033[%sm' "$1"; }
log()   { printf '%s> %s%s\n' "$(_c 36)" "$*" "$(_c 0)"; }
ok()    { printf '%s  [OK] %s%s\n' "$(_c 32)" "$*" "$(_c 0)"; }
warn()  { printf '%s  [WARN] %s%s\n' "$(_c 33)" "$*" "$(_c 0)"; }
die()   { printf '%s  [FAIL] %s%s\n' "$(_c 31)" "$*" "$(_c 0)" >&2; exit 1; }

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
# Scope: this narrows only the gate scripts (validate.sh / finish-feature.sh).
# test-stack.sh / ensure-test-db.sh / run-services.sh / migrate-primary.sh are
# separate processes that re-source the file themselves and keep full access.
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

# --- Branch / project naming ------------------------------------------------
current_branch() { git rev-parse --abbrev-ref HEAD; }

# Docker project names must be lowercase alnum + dashes.
sanitize_proj() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g'
}

# Conventional Branch v1.1.0 — valid type prefixes.
# See https://conventionalbranch.org/
VALID_BRANCH_TYPES="feature|feat|bugfix|fix|hotfix|release|chore|ai|copilot|cursor|claude|codex"

# build_branch <type> <description>
# Constructs a conventional branch name: <type>/<description>
build_branch() {
  local btype="$1" desc="$2"
  printf '%s/%s' "$btype" "$desc"
}

# parse_branch <full-branch-name>
# Splits "type/description" into BRANCH_TYPE and BRANCH_DESC.
# Sets BRANCH_TYPE and BRANCH_DESC as globals.
parse_branch() {
  local full="$1"
  BRANCH_TYPE="${full%%/*}"
  BRANCH_DESC="${full#*/}"
  # If there was no slash, description equals the whole thing (no type).
  if [ "$BRANCH_TYPE" = "$full" ]; then BRANCH_TYPE=""; BRANCH_DESC="$full"; fi
}

# validate_conventional_branch <full-branch-name>
# Returns 0 if the branch name conforms to Conventional Branch v1.1.0, 1 otherwise.
validate_conventional_branch() {
  local name="$1"
  parse_branch "$name"

  # Trunk branches are always valid.
  case "$name" in
    main|master|develop) return 0 ;;
  esac

  # Must have a valid type prefix.
  if [ -z "$BRANCH_TYPE" ]; then
    warn "branch '$name' has no type prefix (expected <type>/<description>)"
    return 1
  fi
  if ! echo "$BRANCH_TYPE" | grep -qE "^($VALID_BRANCH_TYPES)$"; then
    warn "branch type '$BRANCH_TYPE' is not a recognised Conventional Branch type"
    return 1
  fi

  # Description must not be empty.
  if [ -z "$BRANCH_DESC" ]; then
    warn "branch '$name' has an empty description"
    return 1
  fi

  # Description rules: lowercase alnum, hyphens, dots. No consecutive hyphens/dots,
  # no leading/trailing hyphens/dots.
  if ! printf '%s' "$BRANCH_DESC" | grep -qE '^[a-z0-9]([a-z0-9]*[.]?[a-z0-9]*)(-[a-z0-9]([a-z0-9]*[.]?[a-z0-9]*))*$'; then
    warn "branch description '$BRANCH_DESC' violates Conventional Branch naming rules (lowercase alnum, hyphens, dots; no consecutive/leading/trailing hyphens or dots)"
    return 1
  fi

  return 0
}

# --- Docs-only change detection ---------------------------------------------
# True when every file in origin/main...HEAD is docs/planning prose. Used by
# finish-feature.sh to swap the heavy validate gate for mkdocs build --strict.
is_docs_only_vs_main() {
  local files f
  git fetch origin main --quiet 2>/dev/null || true
  files="$(git diff --name-only "origin/main...HEAD" 2>/dev/null || true)"
  if [ -z "$files" ]; then
    return 1
  fi
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    case "$f" in
      docs/*|mkdocs.yml|README.md|_bmad-output/*|_bmad/*|.agents/*|*.md) ;;
      *) return 1 ;;
    esac
  done <<< "$files"
  return 0
}

validate_docs_only() {
  if command -v mkdocs >/dev/null 2>&1; then
    log "Docs-only change — running mkdocs build --strict"
    (cd "$REPO_ROOT" && mkdocs build --strict) || return 1
    return 0
  fi
  warn "mkdocs not installed — skipping local docs build (CI Docs workflow will validate)"
  return 0
}

# --- Registry locking (race-free across parallel setup runs) ----------------
# Prefer flock on .ports.lock (atomic across agents). Fall back to mkdir lock
# when flock is unavailable (rare). Covers port pick + registry.tsv writes.
PORTS_LOCK_FILE="$REGISTRY_DIR/.ports.lock"
REGISTRY_LOCK_FD=""

registry_lock() {
  mkdir -p "$REGISTRY_DIR" 2>/dev/null || true
  if [ ! -d "$REGISTRY_DIR" ] || [ ! -w "$REGISTRY_DIR" ]; then
    die "registry dir not writable: $REGISTRY_DIR (fix ownership or use .agent-workspaces on primary)"
  fi
  if command -v flock >/dev/null 2>&1; then
    # Open/create lock file and hold an exclusive flock for the critical section.
    # FD stays open until registry_unlock (or process exit).
    exec {REGISTRY_LOCK_FD}<>"$PORTS_LOCK_FILE"
    if ! flock -w 90 "$REGISTRY_LOCK_FD"; then
      exec {REGISTRY_LOCK_FD}>&- 2>/dev/null || true
      REGISTRY_LOCK_FD=""
      die "could not acquire ports lock after 90s at $PORTS_LOCK_FILE"
    fi
    return 0
  fi
  local attempts=0
  until mkdir "$REGISTRY_LOCK" 2>/dev/null; do
    sleep 1
    attempts=$((attempts + 1))
    if [ "$attempts" -eq 30 ] || [ "$attempts" -eq 60 ]; then
      warn "registry lock held — breaking assumed-stale lock (attempt $attempts)"
      rm -rf "$REGISTRY_LOCK"
    fi
    if [ "$attempts" -ge 90 ]; then
      die "could not acquire registry lock after ${attempts}s at $REGISTRY_LOCK"
    fi
  done
}
registry_unlock() {
  if [ -n "${REGISTRY_LOCK_FD:-}" ]; then
    flock -u "$REGISTRY_LOCK_FD" 2>/dev/null || true
    exec {REGISTRY_LOCK_FD}>&- 2>/dev/null || true
    REGISTRY_LOCK_FD=""
  fi
  rm -rf "$REGISTRY_LOCK" 2>/dev/null || true
}

# --- Port helpers -----------------------------------------------------------
# A port is "free" if we cannot open a TCP connection to it on localhost.
port_free() {
  local p="$1"
  ! (exec 3<>"/dev/tcp/127.0.0.1/$p") 2>/dev/null
}

# True if the port is already claimed in the registry by ANOTHER branch.
port_reserved() {
  local p="$1" self="${2:-}"
  [ -f "$REGISTRY_FILE" ] || return 1
  awk -v p="$p" -v self="$self" -F '\t' \
    '$1!=self && ($3==p||$4==p||$5==p||$6==p){found=1} END{exit found?0:1}' \
    "$REGISTRY_FILE"
}

# Deterministic starting block from the branch name, then probe upward for a
# gap of 4 consecutive ports that are both OS-free and registry-unreserved.
alloc_port_block() {
  local branch="$1"
  local seed base p ok_block
  seed=$(printf '%s' "$branch" | cksum | cut -d' ' -f1)
  base=$(( 20000 + (seed % 400) * 10 ))   # 20000..23990, stride 10
  for attempt in $(seq 0 400); do
    base=$(( 20000 + ((seed % 400 + attempt) % 400) * 10 ))
    ok_block=1
    for off in 0 1 2 3; do
      p=$(( base + off ))
      if ! port_free "$p" || port_reserved "$p" "$branch"; then ok_block=0; break; fi
    done
    [ "$ok_block" -eq 1 ] && { printf '%s' "$base"; return 0; }
  done
  die "could not find a free port block after 400 attempts"
}

# Playwright binds its own ephemeral Vite (PLAYWRIGHT_PORT), separate from the
# Compose FRONTEND_PORT. Parallel agents must not all default to 5177.
# Collect PLAYWRIGHT_PORT values already written to sibling worktree .env.local.
playwright_ports_in_use() {
  local path envf p
  [ -f "$REGISTRY_FILE" ] || return 0
  while IFS=$'\t' read -r _branch _proj _pg _rd _api _fe path; do
    [ -n "${path:-}" ] || continue
    envf="$path/.env.local"
    [ -f "$envf" ] || continue
    p="$(awk -F= '/^PLAYWRIGHT_PORT=/{print $2; exit}' "$envf" 2>/dev/null || true)"
    [ -n "$p" ] && printf '%s\n' "$p"
  done < "$REGISTRY_FILE"
}

# True if Playwright port is claimed by another worktree's .env.local.
playwright_port_reserved() {
  local p="$1"
  playwright_ports_in_use | grep -qx "$p"
}

# Pick a free Playwright port in 5177..5299.
# Optional preferred start (e.g. derived from FE). Call under registry_lock when
# writing .env.local so parallel setups do not collide.
# Prefer: preferred (if given) → 5177 → 5187..5197 → remaining 5178..5299.
alloc_playwright_port() {
  local preferred="${1:-}"
  local p used
  used="$(playwright_ports_in_use | tr '\n' ' ')"
  _pw_try() {
    local cand="$1"
    [ -n "$cand" ] || return 1
    case " $used " in
      *" $cand "*) return 1 ;;
    esac
    playwright_port_reserved "$cand" && return 1
    port_free "$cand" || return 1
    printf '%s' "$cand"
    return 0
  }
  if [ -n "$preferred" ] && _pw_try "$preferred"; then return 0; fi
  if _pw_try 5177; then return 0; fi
  for p in $(seq 5187 5197); do
    if _pw_try "$p"; then return 0; fi
  done
  for p in $(seq 5178 5186) $(seq 5198 5299); do
    if _pw_try "$p"; then return 0; fi
  done
  die "could not find a free PLAYWRIGHT_PORT in 5177..5299"
}

# If PLAYWRIGHT_PORT is unset, probe for a free port (validate/finish). Does not
# take the registry lock — best-effort for a single agent run.
resolve_playwright_port() {
  if [ -n "${PLAYWRIGHT_PORT:-}" ]; then
    printf '%s' "$PLAYWRIGHT_PORT"
    return 0
  fi
  alloc_playwright_port ""
}

# Read a field for a branch from the registry: registry_get <branch> <col 2..6>
registry_get() {
  [ -f "$REGISTRY_FILE" ] || return 1
  awk -v b="$1" -v c="$2" -F '\t' '$1==b{print $c; exit}' "$REGISTRY_FILE"
}
