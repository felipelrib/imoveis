#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# setup-branch.sh <branch> [base-branch]
#
# Creates a standard git branch for one feature and installs dependencies.
# This replaces the old worktree-based setup which was too complex for agents.
#
# <branch> follows the Conventional Branch v1.1.0 spec:
#   <type>/<description>          — e.g. feat/eng-123-add-login
#   <slug>                       — shorthand, defaults to feat/<slug>
#
# Valid types: feature, feat, bugfix, fix, hotfix, release, chore, ai,
#              copilot, cursor, claude, codex
# ---------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/lib.sh"

[ $# -ge 1 ] || die "usage: setup-branch.sh <branch|slug> [base-branch]"

INPUT="$1"
if echo "$INPUT" | grep -q '/'; then
  BRANCH="$INPUT"
  validate_conventional_branch "$BRANCH" || die "branch '$BRANCH' violates Conventional Branch v1.1.0"
else
  SLUG="$(sanitize_proj "$INPUT")"
  [ -n "$SLUG" ] || die "empty/invalid feature slug"
  DETECTED_TYPE=""
  while IFS='|' read -ra _types; do
    for _t in "${_types[@]}"; do
      if [[ "$SLUG" == "$_t-"* ]]; then
        DETECTED_TYPE="$_t"
        SLUG="${SLUG#$_t-}"
        break 2
      fi
    done
  done <<< "$VALID_BRANCH_TYPES"
  if [ -n "$DETECTED_TYPE" ]; then
    BRANCH="$DETECTED_TYPE/$SLUG"
  else
    BRANCH="feat/$SLUG"
  fi
fi

parse_branch "$BRANCH"
SLUG="$BRANCH_DESC"
BASE_BRANCH="${2:-main}"

log "Preparing branch '$BRANCH'"

if git remote get-url origin >/dev/null 2>&1; then
  git fetch origin --quiet || warn "git fetch failed; using local $BASE_BRANCH"
  git rev-parse --verify "origin/$BASE_BRANCH" >/dev/null 2>&1 && BASE_REF="origin/$BASE_BRANCH" || BASE_REF="$BASE_BRANCH"
else
  BASE_REF="$BASE_BRANCH"
fi

if git rev-parse --verify "$BRANCH" >/dev/null 2>&1; then
  warn "branch $BRANCH already exists — checking it out"
  git checkout "$BRANCH"
else
  git checkout -b "$BRANCH" "$BASE_REF"
  ok "branch created: $BRANCH from $BASE_REF"
fi

echo ""
ok "Workspace ready. You are now on branch $BRANCH."
echo "Dependencies update step:"
echo "  pip install -r requirements.txt"
echo "  cd frontend && npm install"
echo ""
