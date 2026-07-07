#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# finish-feature.sh [feature-slug]
#
# Merges the current feature branch into main, validates, removes the
# worktree, and optionally deletes the feature branch. Run from INSIDE the
# worktree (or pass the slug so the script can find it).
#
# Exit codes:
#   0  merged, validated, worktree removed — done
#   2  merge conflicts — resolve manually, then re-run
#   1  validation failed after merge — fix, commit, re-run
# ---------------------------------------------------------------------------
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

# --- Resolve the feature branch and worktree --------------------------------
if [ -n "${1:-}" ]; then
  SLUG="$(sanitize_proj "$1")"
  BRANCH="feat/$SLUG"
  WT="$REGISTRY_DIR/$SLUG"
else
  BRANCH="$(current_branch)"
  # Strip feat/ prefix to derive slug
  SLUG="${BRANCH#feat/}"
  WT="$(git rev-parse --show-toplevel)"
fi

[ "$BRANCH" != "main" ] || die "you are ON main — run this from a feature worktree"
echo "$BRANCH" | grep -q "^feat/" || die "branch '$BRANCH' does not start with feat/"

# --- Pre-flight checks ------------------------------------------------------
if [ -d "$WT" ] && [ -n "$(cd "$WT" && git status --porcelain 2>/dev/null)" ]; then
  die "working tree at $WT is dirty — commit your work first"
fi

# --- Merge feature into main ------------------------------------------------
cd "$PRIMARY_ROOT"
log "Switching to main..."
git checkout main

log "Merging $BRANCH into main..."
if ! git merge --no-edit "$BRANCH"; then
  warn "MERGE CONFLICTS in:"
  git diff --name-only --diff-filter=U | sed 's/^/    /'
  echo ""
  echo "  Resolve each file, then:  git add <files> && git commit --no-edit"
  echo "  Then re-run: bash scripts/agent/finish-feature.sh"
  exit 2
fi
ok "merged $BRANCH into main"

# --- Post-merge validation --------------------------------------------------
log "Running post-merge validation..."
if bash "$HERE/validate.sh" all; then
  ok "VALIDATION PASSED after merge"
else
  warn "VALIDATION FAILED after merge"
  warn "Rolling back merge: git reset --hard HEAD~1"
  git reset --hard HEAD~1
  warn "Switching back to feature branch..."
  git checkout "$BRANCH"
  exit 1
fi

# --- Tear down worktree and containers --------------------------------------
log "Tearing down worktree..."
if [ -f "$PRIMARY_ROOT/.env.local" ]; then
  set -a; source "$PRIMARY_ROOT/.env.local"; set +a
  PROJ="${COMPOSE_PROJECT_NAME:-imoveis}"
  dc --env-file .env.local -p "$PROJ" down -v --remove-orphans 2>/dev/null || true
fi

if [ -d "$WT" ]; then
  # Remove from registry
  registry_lock
  if [ -f "$REGISTRY_FILE" ]; then
    grep -vP "^$BRANCH\t" "$REGISTRY_FILE" > "$REGISTRY_FILE.tmp" 2>/dev/null || true
    mv "$REGISTRY_FILE.tmp" "$REGISTRY_FILE" 2>/dev/null || true
  fi
  registry_unlock

  git worktree remove --force "$WT" 2>/dev/null && ok "worktree removed" || warn "could not remove worktree"
fi

# --- Clean up feature branch ------------------------------------------------
log "Deleting feature branch $BRANCH..."
git branch -D "$BRANCH" 2>/dev/null && ok "branch $BRANCH deleted" || warn "could not delete branch $BRANCH"

echo ""
ok "Feature '$SLUG' merged into main and cleaned up."
echo "  Main is at: $(git rev-parse --short HEAD)"
echo "  Feature branch and worktree have been removed."