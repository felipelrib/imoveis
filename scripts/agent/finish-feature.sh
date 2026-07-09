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
#
# Flags:
#   --dry-run        Show what would happen without doing it
#   --skip-docs      Skip the gen-docs step
#   --skip-validate  Skip post-merge validation (use for rules/docs-only changes)
#   --validate-only  Only validate, don't merge (sync with main + re-validate)
# ---------------------------------------------------------------------------
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

# --- Parse flags -------------------------------------------------------------
DRY_RUN=false
SKIP_DOCS=false
VALIDATE_ONLY=false
SKIP_VALIDATE=false

for arg in "$@"; do
  case "$arg" in
    --dry-run)        DRY_RUN=true ;;
    --skip-docs)      SKIP_DOCS=true ;;
    --skip-validate)  SKIP_VALIDATE=true ;;
    --validate-only)  VALIDATE_ONLY=true ;;
  esac
done

# --- Resolve the feature branch and worktree --------------------------------
resolve_branch() {
  local slug="$1"
  # Try both common prefixes: feat/ and feature/
  local type
  for type in feat feature; do
    if git rev-parse --verify "$type/$slug" >/dev/null 2>&1; then
      echo "$type/$slug"
      return 0
    fi
  done
  return 1
}

if [ -n "${1:-}" ] && [[ ! "$1" =~ ^-- ]]; then
  SLUG="$(sanitize_proj "$1")"
  BRANCH="$(resolve_branch "$SLUG")" || die "could not find branch 'feat/$SLUG' or 'feature/$SLUG'"
  WT="$REGISTRY_DIR/$SLUG"
else
  BRANCH="$(current_branch)"
  # Extract slug: strip the type prefix (feat/, fix/, feature/, etc.)
  SLUG="${BRANCH#*/}"
  WT="$(git rev-parse --show-toplevel)"
fi

[ "$BRANCH" != "main" ] || die "you are ON main — run this from a feature worktree"
# Accept any branch under a recognized conventional type prefix.
BRANCH_TYPE="${BRANCH%%/*}"
echo "$BRANCH_TYPE" | grep -qE "^($VALID_BRANCH_TYPES)$" || die "branch '$BRANCH' does not have a valid conventional type prefix (expected one of: $VALID_BRANCH_TYPES)"

# --- Validate-only mode (sync with main + re-validate) ----------------------
if [ "$VALIDATE_ONLY" = true ]; then
  log "Validate-only mode: syncing with main and re-validating"
  
  cd "$PRIMARY_ROOT"
  log "Fetching latest from origin..."
  git fetch origin --quiet || warn "git fetch failed"
  
  log "Syncing feature branch with main..."
  if ! git checkout "$BRANCH"; then
    die "could not checkout $BRANCH"
  fi
  if ! git merge --no-edit "origin/$BASE_BRANCH" 2>/dev/null && ! git merge --no-edit main 2>/dev/null; then
    warn "could not sync with main — may need manual merge"
    exit 2
  fi
  
  cd "$WT"
  log "Running validation..."
  if bash "$HERE/validate.sh" all; then
    ok "VALIDATION PASSED"
  else
    warn "VALIDATION FAILED"
    exit 1
  fi
  exit 0
fi

# --- Pre-flight checks ------------------------------------------------------
if [ -d "$WT" ] && [ -n "$(cd "$WT" && git status --porcelain 2>/dev/null)" ]; then
  die "working tree at $WT is dirty — commit your work first"
fi

if [ "$DRY_RUN" = true ]; then
  log "DRY RUN — would do:"
  log "  1. Merge $BRANCH into main"
  log "  2. Run validate.sh all"
  log "  3. Tear down worktree $WT"
  log "  4. Delete branch $BRANCH"
  exit 0
fi

# --- Sync with main before merge (prevents unnecessary conflicts) -----------
log "Syncing with latest main before merge..."
cd "$PRIMARY_ROOT"
git fetch origin --quiet 2>/dev/null || true
if [ -d "$WT" ]; then
  cd "$WT"
  git fetch origin --quiet 2>/dev/null || true
fi

# --- Merge feature into main ------------------------------------------------
cd "$PRIMARY_ROOT"
log "Switching to main..."
git checkout main
git pull --ff-only 2>/dev/null || true

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
if [ "$SKIP_VALIDATE" = true ]; then
  warn "Skipping post-merge validation (--skip-validate)"
else
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
fi

# --- Generate docs (unless skipped) -----------------------------------------
if [ "$SKIP_DOCS" = false ] && [ -f "$HERE/gen-docs.sh" ]; then
  log "Generating feature docs..."
  if bash "$HERE/gen-docs.sh" "$SLUG" "" 2>/dev/null; then
    ok "Docs generated"
  else
    warn "gen-docs.sh skipped (may need title argument)"
  fi
fi

# --- Tear down worktree and containers --------------------------------------
log "Tearing down worktree..."
if [ -f "$PRIMARY_ROOT/.env.local" ]; then
  set -a; source "$PRIMARY_ROOT/.env.local"; set +a
  PROJ="${COMPOSE_PROJECT_NAME:-imoveis}"
  # Stop containers, remove volumes AND images built by compose
  dc --env-file .env.local -p "$PROJ" down -v --remove-orphans --rmi local 2>/dev/null || true
  # Clean up build cache left behind by this project
  docker builder prune --filter "label=com.docker.compose.project=$PROJ" 2>/dev/null || true
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
