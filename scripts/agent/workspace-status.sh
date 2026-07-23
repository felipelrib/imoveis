#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# workspace-status.sh
#
# Reports whether the primary checkout is idle and recommends solo vs parallel.
# Agents should run this (or rely on setup-workspace.sh) before starting work.
#
# Idle invariant: primary on main|master + clean tracked tree.
# Busy: feature branch checked out and/or dirty → next agent uses a worktree.
# ---------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

PB="$(primary_branch)"
if primary_is_idle; then IDLE="yes"; REC="solo"; else IDLE="no"; REC="parallel"; fi

echo "primary_root=$PRIMARY_ROOT"
echo "primary_branch=$PB"
echo "primary_idle=$IDLE"
echo "recommendation=$REC"
echo "current_repo_root=$REPO_ROOT"
if in_linked_worktree; then
  echo "in_worktree=yes"
else
  echo "in_worktree=no"
fi

echo "other_worktrees<<"
other_worktree_paths || true
echo ">>"

if [ -f "$REGISTRY_FILE" ]; then
  echo "registry=$REGISTRY_FILE"
  echo "registry_entries<<"
  cat "$REGISTRY_FILE" 2>/dev/null || true
  echo ">>"
else
  echo "registry=(none)"
fi
