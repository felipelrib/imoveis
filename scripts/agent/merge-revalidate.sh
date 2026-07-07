#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# merge-revalidate.sh [base-branch]   (default: main)
#
# Run ONLY when the feature is otherwise finished. Pulls the latest base branch
# into this feature branch and re-validates so the feature still works alongside
# everyone else's merged changes.
#
# Exit codes:
#   0  merged cleanly AND validation passed — ready to merge to base
#   2  merge conflicts — resolve them, `git add` + `git commit`, then re-run
#   1  merged but validation failed — fix the feature, then re-run
# ---------------------------------------------------------------------------
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

BASE_BRANCH="${1:-main}"
cd "$REPO_ROOT"

BRANCH="$(current_branch)"
[ "$BRANCH" != "$BASE_BRANCH" ] || die "you are ON $BASE_BRANCH — must be on a feature branch/worktree"

# Refuse to merge on a dirty tree — commit your work first (the workflow requires frequent commits).
if [ -n "$(git status --porcelain)" ]; then
  die "working tree is dirty — commit your work before merging (workflow requires frequent commits)"
fi

if git remote get-url origin >/dev/null 2>&1; then
  log "Fetching origin..."; git fetch origin --quiet || warn "fetch failed; merging local $BASE_BRANCH"
  git rev-parse --verify "origin/$BASE_BRANCH" >/dev/null 2>&1 && MERGE_REF="origin/$BASE_BRANCH" || MERGE_REF="$BASE_BRANCH"
else
  MERGE_REF="$BASE_BRANCH"
fi

log "Merging $MERGE_REF into $BRANCH..."
if ! git merge --no-edit "$MERGE_REF"; then
  warn "MERGE CONFLICTS in:"
  git diff --name-only --diff-filter=U | sed 's/^/    /'
  echo ""
  echo "  Resolve each file, then:  git add <files> && git commit --no-edit"
  echo "  Then re-run: bash scripts/agent/merge-revalidate.sh $BASE_BRANCH"
  exit 2
fi
ok "merged cleanly"

log "Re-validating feature against updated base..."
if bash "$HERE/validate.sh" all; then
  ok "STILL VALID after merge — ready to integrate into $BASE_BRANCH"
  exit 0
else
  warn "validation FAILED after merge — fix the feature, commit, then re-run"
  exit 1
fi
