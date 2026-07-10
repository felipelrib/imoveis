#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# finish-feature.sh [feature-slug]
#
# Pushes the current feature branch, validates it, and prepares it for a PR.
# Run from INSIDE the feature branch (or pass the slug so the script can find it).
#
# Exit codes:
#   0  pushed, validated — ready for PR
#   1  validation failed — fix, commit, re-run
#
# Flags:
#   --dry-run        Show what would happen without doing it
#   --skip-docs      Skip the gen-docs step
#   --skip-validate  Skip validation (use for rules/docs-only changes)
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
PR_MODE=false

for arg in "$@"; do
  case "$arg" in
    --dry-run)        DRY_RUN=true ;;
    --skip-docs)      SKIP_DOCS=true ;;
    --skip-validate)  SKIP_VALIDATE=true ;;
    --validate-only)  VALIDATE_ONLY=true ;;
    --pr)             PR_MODE=true ;;
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
else
  BRANCH="$(current_branch)"
  # Extract slug: strip the type prefix (feat/, fix/, feature/, etc.)
  SLUG="${BRANCH#*/}"
fi

[ "$BRANCH" != "main" ] || die "you are ON main — run this from a feature branch"
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
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  die "working tree is dirty — commit your work first"
fi

if [ "$DRY_RUN" = true ]; then
  log "DRY RUN — would do:"
  log "  1. Run validate.sh all"
  log "  2. Delete branch $BRANCH (after PR)"
  exit 0
fi

# --- Sync with main before validation ---------------------------------------
log "Syncing with latest main before validation..."
git fetch origin --quiet 2>/dev/null || true

# --- Validation -------------------------------------------------------------
if [ "$SKIP_VALIDATE" = true ]; then
  warn "Skipping validation (--skip-validate)"
else
  log "Running validation..."
  if bash "$HERE/validate.sh" all; then
    ok "VALIDATION PASSED"
  else
    warn "VALIDATION FAILED"
    exit 1
  fi
fi

# --- Open PR and wait for CI (--pr mode) -----------------------------------
if [ "$PR_MODE" = true ]; then
  log "Pushing branch $BRANCH..."
  git push origin "$BRANCH" 2>/dev/null || die "git push failed"

  log "Opening pull request..."
  PR_TITLE="$(git log -1 --pretty=%s "$BRANCH" 2>/dev/null || echo "Feature: $SLUG")"
  PR_URL=$(gh pr create \
    --base main \
    --head "$BRANCH" \
    --title "$PR_TITLE" \
    --body "$(printf '## Changes\n\n%s\n\n## Validation\n\n- [ ] CI must pass (lint, unit, integration, contract, E2E)\n- [ ] validate.sh all must pass locally' \
      "$(git log main.."$BRANCH" --oneline --no-merges 2>/dev/null | sed 's/^/- /' || echo "- $PR_TITLE")")" \
    2>&1) || die "gh pr create failed: $PR_URL"
  ok "PR created: $PR_URL"

  log "Waiting for CI checks to pass (this may take a few minutes)..."
  gh pr checks --watch "$BRANCH" 2>/dev/null || {
    warn "CI checks failed or timed out."
    warn "Fix issues, push fixes, and re-run: bash scripts/agent/finish-feature.sh --pr"
    exit 1
  }
  ok "All CI checks passed"
  exit 0
fi

log "Pushing branch $BRANCH..."
git push origin "$BRANCH" 2>/dev/null || die "git push failed"
ok "Feature '$SLUG' is pushed and ready for PR."
echo "  Run: gh pr create"

# --- Generate docs (unless skipped) -----------------------------------------
if [ "$SKIP_DOCS" = false ] && [ -f "$HERE/gen-docs.sh" ]; then
  log "Generating feature docs..."
  if bash "$HERE/gen-docs.sh" "$SLUG" "" 2>/dev/null; then
    ok "Docs generated"
  else
    warn "gen-docs.sh skipped (may need title argument)"
  fi
fi

# --- Clean up feature branch (if requested by user later, script doesn't delete it directly now since it's a PR) ----

echo ""
ok "Feature '$SLUG' processed."
