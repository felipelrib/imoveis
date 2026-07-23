#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# finish-feature.sh [feature-slug]
#
# Validates the current feature branch, pushes it, and optionally opens a PR.
# Run from INSIDE the feature workspace (primary solo branch or a worktree).
#
# With --pr: after required checks are green, SQUASH-MERGES the PR into main, then
# cleans up the workspace (worktree teardown --remove, or primary → main).
# Merge-ready is NOT finished — squash-merged to main is finished.
#
# Docs-only branches (prose under docs/, *.md, _bmad-output/, etc.):
#   - Local gate is mkdocs build --strict (not validate.sh all)
#   - GitHub full CI is paths-ignored; Docs workflow (`docs` check) is the gate
#   - If no checks attach but the PR is MERGEABLE, merge proceeds after a short wait
#
# Idle invariant: after a successful finish on the PRIMARY checkout, checks out
# main so the next agent sees primary_is_idle and can use solo mode.
#
# Exit codes:
#   0  pushed, validated — PR merged (with --pr) / ready for PR
#   1  validation failed — fix, commit, re-run
#
# Flags:
#   --dry-run        Show what would happen without doing it
#   --skip-docs      Skip the gen-docs step
#   --skip-validate  Skip validation (use for rules/docs-only changes)
#   --validate-only  Only validate, don't push
#   --pr             Push, open/reuse PR, watch CI, merge, cleanup workspace
#   --no-merge       With --pr: stop after CI green (do not merge / teardown)
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
NO_MERGE=false
KEEP_BRANCH=false

for arg in "$@"; do
  case "$arg" in
    --dry-run)        DRY_RUN=true ;;
    --skip-docs)      SKIP_DOCS=true ;;
    --skip-validate)  SKIP_VALIDATE=true ;;
    --validate-only)  VALIDATE_ONLY=true ;;
    --pr)             PR_MODE=true ;;
    --no-merge)       NO_MERGE=true ;;
    --keep-branch)    KEEP_BRANCH=true ;;
  esac
done

return_primary_to_idle() {
  if [ "$KEEP_BRANCH" = true ]; then
    warn "skipping return-to-main (--keep-branch)"
    return 0
  fi
  if in_linked_worktree; then
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

cleanup_after_merge() {
  if [ "$KEEP_BRANCH" = true ]; then
    warn "skipping workspace cleanup (--keep-branch)"
    return 0
  fi
  if in_linked_worktree; then
    log "Merged from worktree — tearing down worktree (teardown.sh --remove)..."
    # teardown cds to PRIMARY_ROOT and removes this worktree; run in subshell-safe path
    bash "$HERE/teardown.sh" --remove || warn "teardown.sh --remove failed — remove worktree manually"
    return 0
  fi
  return_primary_to_idle
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
  if [ "$PR_MODE" = true ]; then
    log "  3. Open/reuse PR + watch CI"
    if [ "$NO_MERGE" = true ]; then
      log "  4. Stop after CI green (--no-merge)"
    else
      log "  4. Merge PR into main"
      log "  5. Cleanup workspace (teardown --remove if worktree, else checkout main)"
    fi
  else
    log "  3. Return primary to main (unless worktree / --keep-branch)"
  fi
  exit 0
fi

# --- Sync with main before validation ---------------------------------------
log "Syncing with latest main before validation..."
git fetch origin --quiet 2>/dev/null || true

DOCS_ONLY=false
if is_docs_only_vs_main; then
  DOCS_ONLY=true
  ok "Detected docs-only change vs origin/main (heavy CI will be skipped by paths-ignore)"
fi

# --- Validation -------------------------------------------------------------
if [ "$SKIP_VALIDATE" = true ]; then
  warn "Skipping validation (--skip-validate)"
elif [ "$DOCS_ONLY" = true ]; then
  if validate_docs_only; then
    ok "DOCS VALIDATION PASSED"
  else
    warn "DOCS VALIDATION FAILED"
    exit 1
  fi
else
  log "Running validation..."
  if bash "$HERE/validate.sh" all; then
    ok "VALIDATION PASSED"
  else
    warn "VALIDATION FAILED"
    exit 1
  fi
fi

# Wait for PR checks. Docs-only: tolerate "no checks yet", prefer Docs workflow.
wait_for_pr_checks() {
  local attempts=0
  local max_attempts=90   # ~15 min at 10s
  local out rc

  if [ "$DOCS_ONLY" = true ]; then
    log "Docs-only PR — waiting for Docs workflow (full CI is path-ignored)..."
  else
    log "Waiting for CI checks to pass (this may take a few minutes)..."
  fi

  # Brief settle so GitHub can attach the pull_request workflow run
  sleep 8

  while [ "$attempts" -lt "$max_attempts" ]; do
    attempts=$((attempts + 1))
    out="$(gh pr checks 2>&1)" || true
    rc=0
    gh pr checks >/dev/null 2>&1 || rc=$?

    if echo "$out" | grep -qiE 'no checks reported'; then
      if [ "$DOCS_ONLY" = true ] && [ "$attempts" -ge 6 ]; then
        # After ~1 min with no checks: ruleset does not require status checks —
        # allow merge for docs-only if the PR is still mergeable.
        local mergeable
        mergeable="$(gh pr view --json mergeable -q .mergeable 2>/dev/null || echo UNKNOWN)"
        if [ "$mergeable" = "MERGEABLE" ]; then
          warn "No checks attached after wait — docs-only + MERGEABLE; proceeding to merge"
          return 0
        fi
      fi
      sleep 10
      continue
    fi

    if echo "$out" | grep -qiE '\b(fail|failure|cancelled|timed out)\b'; then
      printf '%s\n' "$out"
      return 1
    fi

    # Any pending/queued → keep waiting
    if echo "$out" | grep -qiE '\b(pending|queued|in_progress|expected)\b'; then
      sleep 10
      continue
    fi

    # All reported checks look done and gh pr checks exit 0
    if [ "$rc" -eq 0 ]; then
      printf '%s\n' "$out"
      return 0
    fi

    # Fallback: use --watch once checks exist
    if gh pr checks --watch 2>/dev/null; then
      return 0
    fi
    sleep 10
  done

  warn "Timed out waiting for PR checks"
  return 1
}

# --- Open PR, wait for CI, merge (--pr mode) --------------------------------
if [ "$PR_MODE" = true ]; then
  log "Pushing branch $BRANCH..."
  git push -u origin "$BRANCH" 2>/dev/null || die "git push failed"

  EXISTING_PR="$(gh pr view --json url,state -q 'if .state == "OPEN" then .url else empty end' 2>/dev/null || true)"
  if [ -n "$EXISTING_PR" ]; then
    PR_URL="$EXISTING_PR"
    ok "Reusing open PR: $PR_URL"
  else
    log "Opening pull request..."
    PR_TITLE="$(git log -1 --pretty=%s "$BRANCH" 2>/dev/null || echo "Feature: $SLUG")"
    CREATE_OUT=$(gh pr create \
      --base main \
      --head "$BRANCH" \
      --title "$PR_TITLE" \
      --body "$(printf '## Changes\n\n%s\n\n## Validation\n\n- [ ] CI must pass (lint, unit, integration, contract, E2E)\n- [ ] validate.sh all must pass locally' \
        "$(git log main.."$BRANCH" --oneline --no-merges 2>/dev/null | sed 's/^/- /' || echo "- $PR_TITLE")")" \
      2>&1) || {
        # Race: PR may have been opened between view and create
        EXISTING_PR="$(gh pr view --json url,state -q 'if .state == "OPEN" then .url else empty end' 2>/dev/null || true)"
        if [ -n "$EXISTING_PR" ]; then
          PR_URL="$EXISTING_PR"
          warn "gh pr create failed but open PR exists — reusing $PR_URL"
        else
          die "gh pr create failed: $CREATE_OUT"
        fi
      }
    if [ -z "${PR_URL:-}" ]; then
      PR_URL="$CREATE_OUT"
      ok "PR created: $PR_URL"
    fi
  fi

  log "Waiting for required checks..."
  if ! wait_for_pr_checks; then
    warn "CI checks failed or timed out."
    warn "Fix issues, push fixes, and re-run: bash scripts/agent/finish-feature.sh --pr"
    warn "If checks are still queued, babysit with: gh pr checks --watch"
    exit 1
  fi
  ok "Required checks passed (or docs-only merge allowed)"

  if [ "$NO_MERGE" = true ]; then
    warn "Stopping after CI green (--no-merge). Merge manually, then cleanup workspace."
    exit 0
  fi

  log "Squash-merging PR into main (merge-ready is not finished)..."
  # Always squash into main — keeps history linear (one commit per PR).
  # Do NOT use gh --delete-branch: it tries to checkout main locally and can
  # steal/switch the primary checkout when main is locked in another worktree.
  gh pr merge --squash || die "gh pr merge failed — resolve blockers and re-run"
  ok "PR merged: $PR_URL"
  if git push origin --delete "$BRANCH" 2>/dev/null; then
    ok "Deleted remote branch $BRANCH"
  else
    warn "could not delete remote branch $BRANCH (may already be gone)"
  fi

  cleanup_after_merge
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
