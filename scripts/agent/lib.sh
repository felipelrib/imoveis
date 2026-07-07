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

REGISTRY_DIR="$PRIMARY_ROOT/.worktrees"
REGISTRY_FILE="$REGISTRY_DIR/registry.tsv"     # branch <tab> proj <tab> pg <tab> redis <tab> api <tab> fe
REGISTRY_LOCK="$REGISTRY_DIR/.lock"            # mkdir-based lock (atomic, portable)

# --- Logging ----------------------------------------------------------------
_c() { printf '\033[%sm' "$1"; }
log()   { printf '%s> %s%s\n' "$(_c 36)" "$*" "$(_c 0)"; }
ok()    { printf '%s  [OK] %s%s\n' "$(_c 32)" "$*" "$(_c 0)"; }
warn()  { printf '%s  [WARN] %s%s\n' "$(_c 33)" "$*" "$(_c 0)"; }
die()   { printf '%s  [FAIL] %s%s\n' "$(_c 31)" "$*" "$(_c 0)" >&2; exit 1; }

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

# --- Registry locking (race-free across parallel setup runs) ----------------
registry_lock() {
  mkdir -p "$REGISTRY_DIR"
  local waited=0
  until mkdir "$REGISTRY_LOCK" 2>/dev/null; do
    sleep 1; waited=$((waited + 1))
    if [ "$waited" -ge 30 ]; then
      warn "registry lock held >30s — breaking assumed-stale lock"
      rm -rf "$REGISTRY_LOCK"
    fi
  done
}
registry_unlock() { rm -rf "$REGISTRY_LOCK" 2>/dev/null || true; }

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

# Read a field for a branch from the registry: registry_get <branch> <col 2..6>
registry_get() {
  [ -f "$REGISTRY_FILE" ] || return 1
  awk -v b="$1" -v c="$2" -F '\t' '$1==b{print $c; exit}' "$REGISTRY_FILE"
}
