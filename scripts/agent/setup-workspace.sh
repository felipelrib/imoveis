#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# setup-workspace.sh <branch|slug> [base-branch]
#
# Chooses solo vs parallel isolation for a feature:
#
#   current  — this session is ALREADY inside a dedicated, isolated worktree
#              provided natively by the calling product (Claude Code's
#              EnterWorktree tool / Agent `isolation: "worktree"`, or Cursor's
#              background-agent dispatch) rather than by this script → skip
#              creating a second, nested/sibling worktree; setup-worktree.sh
#              just configures ports/.env.local/symlinks in place.
#   solo     — primary checkout is idle (on main + clean) → setup-branch.sh
#   parallel — primary is busy (feature branch and/or dirty) OR --force-worktree
#              → setup-worktree.sh (sibling worktree + private ports)
#
# Idle invariant: after finish-feature, agents return the primary checkout to
# main so the next agent can detect contention via workspace-status.sh /
# primary_is_idle.
#
# Flags:
#   --force-worktree  Always create a sibling worktree
#   --force-branch    Always use in-place setup-branch (warns if primary busy;
#                      also overrides the "current" (already-isolated) case
#                      below if you explicitly want a fresh branch in place)
#
# Prints a short summary; last line is the workspace path to cd / move into.
# ---------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

FORCE_WT=0
FORCE_BRANCH=0
ARGS=()
for arg in "$@"; do
  case "$arg" in
    --force-worktree) FORCE_WT=1 ;;
    --force-branch)   FORCE_BRANCH=1 ;;
    *)                ARGS+=("$arg") ;;
  esac
done

[ ${#ARGS[@]} -ge 1 ] || die "usage: setup-workspace.sh <branch|slug> [base-branch] [--force-worktree|--force-branch]"

if [ "$FORCE_WT" -eq 1 ] && [ "$FORCE_BRANCH" -eq 1 ]; then
  die "use only one of --force-worktree / --force-branch"
fi

# Already isolated: this session's cwd is a linked worktree (not the primary),
# meaning the calling product already gave it a dedicated worktree before this
# script ever ran. PRIMARY_ROOT's busy/idle state is irrelevant here — do NOT
# create ANOTHER (sibling) worktree, which would try to relocate outside the
# product's own sanctioned worktree root. setup-worktree.sh detects this same
# condition and configures the environment in place instead of creating one.
if in_linked_worktree && [ "$FORCE_BRANCH" -ne 1 ]; then
  ok "MODE=current (already in an isolated worktree at $REPO_ROOT — native product isolation, not this script)"
  bash "$HERE/setup-worktree.sh" "${ARGS[@]}"
  exit 0
fi

PB="$(primary_branch)"
if primary_is_idle; then
  IDLE=1
else
  IDLE=0
fi

OTHERS="$(other_worktree_paths | wc -l | tr -d ' ')"

log "Primary: $PRIMARY_ROOT (branch=$PB idle=$([[ $IDLE -eq 1 ]] && echo yes || echo no) other_worktrees=$OTHERS)"

MODE="solo"
REASON="primary idle on $PB"
if [ "$FORCE_WT" -eq 1 ]; then
  MODE="parallel"
  REASON="--force-worktree"
elif [ "$FORCE_BRANCH" -eq 1 ]; then
  MODE="solo"
  REASON="--force-branch"
  if [ "$IDLE" -eq 0 ]; then
    warn "primary is BUSY (branch=$PB) but --force-branch requested — you may disrupt another agent"
  fi
elif [ "$IDLE" -eq 0 ]; then
  MODE="parallel"
  REASON="primary busy (branch=$PB) — another agent likely using this checkout"
fi

ok "MODE=$MODE ($REASON)"

if [ "$MODE" = "parallel" ]; then
  bash "$HERE/setup-worktree.sh" "${ARGS[@]}"
else
  bash "$HERE/setup-branch.sh" "${ARGS[@]}"
  echo ""
  echo "  MODE=solo"
  echo "  BRANCH=$(git -C "$PRIMARY_ROOT" rev-parse --abbrev-ref HEAD)"
  echo "  Stay in primary checkout. When finished, finish-feature returns you to main."
  echo ""
  # Last line = workspace path
  echo "$PRIMARY_ROOT"
fi
