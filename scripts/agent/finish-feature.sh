#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# finish-feature.sh [feature-slug]
#
# The LOCAL finish gate (no PR, no remote CI — CAP-8): validates the current
# feature branch, squash-merges it into main locally, pushes main to origin
# (mandatory — origin is the backup, not a gate), and cleans up the workspace.
# Run from INSIDE the feature workspace (primary solo branch or a worktree).
#
# Flow:
#   1. Feature-doc gate (docs/features/<story-key>-*.md must exist)
#   2. validate.sh all (docs-only branches: mkdocs build --strict)
#      — a red validation BLOCKS the merge; nothing proceeds past it
#   3. Local squash-merge into main (one commit per feature, linear history)
#   4. git push origin main (immediately — every local merge is pushed)
#   5. Cleanup: worktree teardown --remove, or primary stays on main;
#      ephemeral test stack down; docker-cleanup.sh (never volumes)
#
# The primary stack is never touched (validation runs on the ephemeral
# test stack — see test-stack.sh / validate.sh).
#
# Exit codes:
#   0  merged into main and pushed (or --validate-only/--no-merge success)
#   1  validation failed — fix, commit, re-run
#   2  sync/merge conflict or main moved — reconcile manually, re-run
#
# Flags:
#   --dry-run        Show what would happen without doing it
#   --skip-docs      Skip the feature-doc gate
#   --skip-validate  Docs-only branches only: skip the heavy gate (the mkdocs
#                    gate still runs — there is NO zero-gate path to main)
#   --validate-only  Only validate, don't merge
#   --no-merge       Stop after validation (do not merge / push / teardown)
#   --keep-branch    Keep the feature branch/workspace after merge (rare);
#                    test-stack down + docker-cleanup still run
# ---------------------------------------------------------------------------
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

# Conflict-class failures exit 2 (die() is the generic exit-1 path).
die2() { printf '\033[31m  [FAIL] %s\033[0m\n' "$*" >&2; exit 2; }

# Worktree ports / PLAYWRIGHT_PORT (validate.sh also sources this).
if [ -f "$REPO_ROOT/.env.local" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env.local"
  set +a
fi

# --- Parse flags -------------------------------------------------------------
DRY_RUN=false
SKIP_DOCS=false
VALIDATE_ONLY=false
SKIP_VALIDATE=false
NO_MERGE=false
KEEP_BRANCH=false

for arg in "$@"; do
  case "$arg" in
    --dry-run)        DRY_RUN=true ;;
    --skip-docs)      SKIP_DOCS=true ;;
    --skip-validate)  SKIP_VALIDATE=true ;;
    --validate-only)  VALIDATE_ONLY=true ;;
    --no-merge)       NO_MERGE=true ;;
    --keep-branch)    KEEP_BRANCH=true ;;
  esac
done

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

# --- Feature-doc gate --------------------------------------------------------
# Every story ships with docs/features/<story-key>-<slug>.md. Derive the key
# from the branch name (feat/v0.13-s1.1-… → v0.13-s1.1; feat/v0.13-fu1-… →
# v0.13-fu1; legacy bin-147-… → BIN-147).
derive_story_key() {
  local desc="${BRANCH#*/}"
  case "$desc" in
    v[0-9]*.[0-9]*-s[0-9]*.[0-9]*)
      printf '%s' "$desc" | grep -oE '^v[0-9]+\.[0-9]+-s[0-9]+\.[0-9]+' ;;
    v[0-9]*.[0-9]*-fu[0-9]*)
      printf '%s' "$desc" | grep -oE '^v[0-9]+\.[0-9]+-fu[0-9]+' ;;
    [Bb][Ii][Nn]-[0-9]*)
      printf '%s' "$desc" | grep -oiE '^bin-[0-9]+' | tr 'a-z' 'A-Z' ;;
    *) return 1 ;;
  esac
}

if [ "$SKIP_DOCS" = false ]; then
  STORY_KEY="$(derive_story_key || true)"
  if [ -n "${STORY_KEY:-}" ]; then
    if ! ls "$REPO_ROOT/docs/features/${STORY_KEY}-"*.md >/dev/null 2>&1; then
      if [ "$DRY_RUN" = true ]; then
        warn "no feature doc for ${STORY_KEY} yet — a real run would refuse here"
      else
        die "no feature doc found for ${STORY_KEY} (docs/features/${STORY_KEY}-*.md). Create it (bash scripts/agent/gen-docs.sh <slug> \"<Title>\" ${STORY_KEY}), commit, and re-run — or pass --skip-docs."
      fi
    else
      ok "feature doc present for ${STORY_KEY}"
    fi
  else
    warn "could not derive a story key from branch '$BRANCH' — skipping feature-doc gate"
  fi
fi

# --- Sync with main before validation ---------------------------------------
log "Syncing with latest main before validation..."
git fetch origin --quiet 2>/dev/null || warn "git fetch failed — merging against local main"

DOCS_ONLY=false
if is_docs_only_vs_main; then
  DOCS_ONLY=true
  ok "Detected docs-only change vs main (heavy validation skipped; mkdocs gate applies)"
fi

if [ "$DRY_RUN" = true ]; then
  log "DRY RUN — would do:"
  if [ "$DOCS_ONLY" = true ]; then
    log "  1. mkdocs build --strict (docs-only gate)"
  else
    log "  1. Run validate.sh all (ephemeral test stack; primary untouched)"
  fi
  log "  2. Squash-merge $BRANCH into main locally"
  log "  3. git push origin main (mandatory)"
  log "  4. Cleanup (worktree teardown --remove, or primary stays on main; test stack down; docker-cleanup.sh)"
  exit 0
fi

# --- Validation (THE merge gate — red blocks the merge) ----------------------
# There is deliberately NO zero-gate path to main: --skip-validate only swaps
# the heavy gate for the docs gate, and only on docs-only branches.
if [ "$SKIP_VALIDATE" = true ] && [ "$DOCS_ONLY" != true ]; then
  die "--skip-validate is only allowed for docs-only branches — this branch touches code, run the full gate"
fi
if [ "$SKIP_VALIDATE" = true ] || [ "$DOCS_ONLY" = true ]; then
  if validate_docs_only; then
    ok "DOCS VALIDATION PASSED"
  else
    warn "DOCS VALIDATION FAILED — merge blocked"
    exit 1
  fi
else
  log "Running validation..."
  if bash "$HERE/validate.sh" all; then
    ok "VALIDATION PASSED"
  else
    warn "VALIDATION FAILED — merge blocked. Fix, commit, re-run."
    exit 1
  fi
fi

if [ "$NO_MERGE" = true ]; then
  warn "Stopping after validation (--no-merge). Merge with: bash scripts/agent/finish-feature.sh"
  exit 0
fi

# --- Local squash-merge into main --------------------------------------------
MERGE_TITLE="$(git log -1 --pretty=%s "$BRANCH" 2>/dev/null || echo "feat: $SLUG")"
MERGE_BODY="$(git log main.."$BRANCH" --oneline --no-merges 2>/dev/null | sed 's/^/- /' || true)"
ALEMBIC_TOUCHED=false
if git diff --name-only main.."$BRANCH" 2>/dev/null | grep -q '^alembic/versions/'; then
  ALEMBIC_TOUCHED=true
fi

if in_linked_worktree; then
  MERGE_DIR="$PRIMARY_ROOT"
  # NEVER commandeer a busy primary: another agent may be mid-task there.
  # Only merge in the primary when it already sits idle on main.
  if [ "$(git -C "$MERGE_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null)" != "main" ]; then
    die "primary checkout is on '$(git -C "$MERGE_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null)', not main — another agent may be using it. Wait for it to return to main (idle invariant), or finish from the primary checkout."
  fi
  if [ -n "$(git -C "$MERGE_DIR" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    die "primary checkout is dirty — cannot squash-merge there. Clean it up and re-run."
  fi
else
  MERGE_DIR="$REPO_ROOT"
  git checkout main || die "could not checkout main (held by a worktree?) — resolve and re-run"
fi

restore_workspace_branch() {
  # Undo a half-done merge and put the primary-checkout case back on its branch.
  git -C "$MERGE_DIR" reset --merge 2>/dev/null || true
  [ "$MERGE_DIR" = "$REPO_ROOT" ] && git checkout "$BRANCH" 2>/dev/null
}

log "Updating local main from origin (ff-only)..."
if ! git -C "$MERGE_DIR" pull --ff-only origin main 2>/dev/null; then
  # Offline is tolerable (push will fail loudly later); divergence is not.
  if git -C "$MERGE_DIR" fetch origin main --quiet 2>/dev/null; then
    restore_workspace_branch
    die2 "local main and origin/main diverged — reconcile manually, then re-run"
  fi
  warn "origin unreachable — merging on local main (push will be retried below)"
fi

# main must not have moved past what validation saw — a squash of branch+newer
# main is a combination no gate ever validated.
if [ "$(git -C "$MERGE_DIR" rev-parse main)" != "$(git -C "$MERGE_DIR" merge-base main "$BRANCH")" ]; then
  restore_workspace_branch
  die2 "main moved since this branch was validated — merge main into '$BRANCH', re-validate, re-run"
fi

log "Squash-merging $BRANCH into main (one commit, linear history)..."
if ! git -C "$MERGE_DIR" merge --squash "$BRANCH"; then
  git -C "$MERGE_DIR" merge --abort 2>/dev/null || true
  restore_workspace_branch
  die2 "squash-merge conflict — merge main into '$BRANCH', resolve, validate, re-run"
fi
if git -C "$MERGE_DIR" diff --cached --quiet; then
  warn "nothing to merge — '$BRANCH' adds no changes on top of main (already merged?); skipping commit"
elif [ -n "$MERGE_BODY" ]; then
  git -C "$MERGE_DIR" commit -m "$MERGE_TITLE" -m "$MERGE_BODY" \
    || { restore_workspace_branch; die "merge commit failed — workspace restored to '$BRANCH'"; }
  ok "Squash-merged into main: $MERGE_TITLE"
else
  git -C "$MERGE_DIR" commit -m "$MERGE_TITLE" \
    || { restore_workspace_branch; die "merge commit failed — workspace restored to '$BRANCH'"; }
  ok "Squash-merged into main: $MERGE_TITLE"
fi

# --- Push (mandatory — origin/main is the backup of record) ------------------
log "Pushing main to origin..."
if git -C "$MERGE_DIR" push origin main; then
  ok "origin/main updated (equals local main)"
else
  die "git push origin main FAILED — the merge exists only locally. Re-run 'git push origin main' before doing anything else."
fi

# Legacy remote feature branches (pre-surgery pushes): best-effort removal.
git push origin --delete "$BRANCH" 2>/dev/null || true

if [ "$ALEMBIC_TOUCHED" = true ]; then
  warn "This merge includes Alembic migrations. The PRIMARY realestate DB is NOT migrated by any gate —"
  warn "run 'bash scripts/agent/migrate-primary.sh' when the backfill is idle to bring primary to head."
fi

# --- Cleanup ------------------------------------------------------------------
if [ "$KEEP_BRANCH" = true ]; then
  warn "keeping branch/workspace (--keep-branch) — still pruning docker temps"
  bash "$HERE/test-stack.sh" down || warn "test-stack down had issues"
  bash "$HERE/docker-cleanup.sh" || warn "docker-cleanup.sh had issues"
  exit 0
fi

if in_linked_worktree; then
  log "Merged from worktree — tearing down worktree (teardown.sh --remove)..."
  # teardown downs this worktree's stacks (incl. ephemeral test stack), runs
  # docker-cleanup.sh, and removes the worktree + registry entry.
  bash "$HERE/teardown.sh" --remove || warn "teardown.sh --remove failed — remove worktree manually"
  git -C "$PRIMARY_ROOT" branch -D "$BRANCH" 2>/dev/null && ok "deleted merged branch $BRANCH" || true
else
  # Primary checkout: we are already on main (idle invariant for parallel agents).
  git branch -D "$BRANCH" 2>/dev/null && ok "deleted merged branch $BRANCH" || true
  bash "$HERE/test-stack.sh" down || warn "test-stack down had issues"
  bash "$HERE/docker-cleanup.sh" || warn "docker-cleanup.sh had issues"
fi

echo ""
ok "Feature '$SLUG' merged into main and pushed."
