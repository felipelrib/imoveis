#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# finish-feature.sh [feature-slug]
#
# Validates the current feature branch, pushes it, and optionally opens a PR.
# Run from INSIDE the feature workspace (primary solo branch or a worktree).
#
# Idle invariant: after a successful finish on the PRIMARY checkout, checks out
# main so the next agent sees primary_is_idle and can use solo mode.
# Worktree finishes leave the primary alone; use teardown.sh --remove to drop
# the worktree when done.
#
# Exit codes:
#   0  pushed, validated — ready for PR / PR created
#   1  validation failed — fix, commit, re-run
#
# Flags:
#   --dry-run        Show what would happen without doing it
#   --skip-docs      Skip the gen-docs step
#   --skip-validate  Skip validation (use for rules/docs-only changes)
#   --validate-only  Only validate, don't push
#   --pr             Push, open PR, watch CI
#   --keep-branch    Do not checkout main on primary after finish (rare)
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
KEEP_BRANCH=false

for arg in "$@"; do
  case "$arg" in
    --dry-run)        DRY_RUN=true ;;
    --skip-docs)      SKIP_DOCS=true ;;
    --skip-validate)  SKIP_VALIDATE=true ;;
    --validate-only)  VALIDATE_ONLY=true ;;
    --pr)             PR_MODE=true ;;
    --keep-branch)    KEEP_BRANCH=true ;;
  esac
done

return_primary_to_idle() {
  if [ "$KEEP_BRANCH" = true ]; then
    warn "skipping return-to-main (--keep-branch)"
    return 0
  fi
  if in_linked_worktree; then
    log "Finished in a worktree — primary left as-is. Optional: bash scripts/agent/teardown.sh --remove"
    return 0
  fi
  if [ "$REPO_ROOT" != "$PRIMARY_ROOT" ]; then
    return 0
  fi
  log "Returning primary checkout to main (idle invariant for parallel agents)..."
  git -C "$PRIMARY_ROOT" fetch origin --quiet 2>/dev/null || true
  if git -C "$PRIMARY_ROOT" checkout main 2>/dev/null; then
    git -C "$PRIMARY_ROOT" pull --ff-only origin main 2>/dev/null || true
    ok "primary now on $(git -C "$PRIMARY_ROOT" rev-parse --abbrev-ref HEAD)"
  else
    warn "could not checkout main on primary — fix manually so the next agent can detect idle"
  fi
}

# --- Resolve the feature branch ---------------------------------------------
resolve_branch() {
  local slug="$1"
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
  SLUG="${BRANCH#*/}"
fi

[ "$BRANCH" != "main" ] || die "you are ON main — run this from a feature branch"
BRANCH_TYPE="${BRANCH%%/*}"
echo "$BRANCH_TYPE" | grep -qE "^($VALID_BRANCH_TYPES)$" || die "branch '$BRANCH' does not have a valid conventional type prefix (expected one of: $VALID_BRANCH_TYPES)"

# --- Validate-only mode -----------------------------------------------------
if [ "$VALIDATE_ONLY" = true ]; then
  log "Validate-only mode: syncing with main and re-validating"

  log "Fetching latest from origin..."
  git fetch origin --quiet || warn "git fetch failed"

  log "Syncing feature branch with main..."
  if ! git merge --no-edit "origin/main" 2>/dev/null && ! git merge --no-edit main 2>/dev/null; then
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
  log "  2. Push $BRANCH"
  [ "$PR_MODE" = true ] && log "  3. Open PR + watch CI"
  log "  4. Return primary to main (unless worktree / --keep-branch)"
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
  git push -u origin "$BRANCH" 2>/dev/null || die "git push failed"

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
  return_primary_to_idle
  exit 0
fi

log "Pushing branch $BRANCH..."
git push -u origin "$BRANCH" 2>/dev/null || die "git push failed"
ok "Feature '$SLUG' is pushed and ready for PR."
echo "  Run: gh pr create   (or: bash scripts/agent/finish-feature.sh --pr)"

# --- Generate docs (unless skipped) -----------------------------------------
if [ "$SKIP_DOCS" = false ] && [ -f "$HERE/gen-docs.sh" ]; then
  log "Generating feature docs..."
  if bash "$HERE/gen-docs.sh" "$SLUG" "" 2>/dev/null; then
    ok "Docs generated"
  else
    warn "gen-docs.sh skipped (may need title argument)"
  fi
fi

return_primary_to_idle

echo ""
ok "Feature '$SLUG' processed."
