#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# gen-docs.sh <feature-slug> "<Human Readable Title>" [BIN-id]
#
# Scaffolds docs/features/BIN-<id>-<slug>.md (if absent) — named after the
# Linear issue ID (unique, so parallel PRs never collide) — and adds it to the
# mkdocs.yml Features nav. The agent fills in the prose, then commits.
#
# The BIN id may be passed as the 3rd arg; otherwise it is derived from the
# current branch name (e.g. `bin-147-...` or `feat/bin-147-...` -> BIN-147).
# If it cannot be derived, a BIN-XXX placeholder is used and the agent is
# warned to rename the doc to the real Linear ID before committing.
#
# Prints the doc path on the last line.
# ---------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

[ $# -ge 1 ] || die "usage: gen-docs.sh <feature-slug> \"<Title>\" [BIN-id]"
SLUG="$(sanitize_proj "$1")"
TITLE="${2:-$SLUG}"
BIN_ARG="${3:-}"
cd "$REPO_ROOT"

mkdir -p docs/features

# Resolve the Linear issue ID for the filename prefix.
BRANCH="$(current_branch)"
if [ -n "$BIN_ARG" ]; then
  BIN_ID="$(printf '%s' "$BIN_ARG" | grep -oiE 'BIN-[0-9]+' | head -1 || true)"
else
  # derive from branch: bin-147-... / feat/bin-147-... -> BIN-147
  BIN_ID="$(printf '%s' "$BRANCH" | grep -oiE 'bin-[0-9]+' | head -1 | tr 'a-z' 'A-Z' || true)"
fi
if [ -z "$BIN_ID" ]; then
  BIN_ID="BIN-XXX"
  warn "could not resolve Linear ID (arg or branch) — using placeholder $BIN_ID; RENAME the doc to the real BIN-<id> before committing"
fi

DOC="docs/features/${BIN_ID}-${SLUG}.md"

if [ ! -f "$DOC" ]; then
  DIFFSTAT="$(git diff --stat "$(git merge-base HEAD main 2>/dev/null || echo HEAD)"...HEAD 2>/dev/null | tail -n 20 || true)"
  cat > "$DOC" <<EOF
# $TITLE — <one-line description>

> Feature branch: \`$BRANCH\` · Linear: \`$BIN_ID\` · Status: implemented

## Problem
_What user/business problem does this solve? (fill in)_

## Approach
_Architectural approach and key decisions. (fill in)_

## Changes
Files touched (auto from diff — prune/annotate as needed):

\`\`\`
$DIFFSTAT
\`\`\`

## New Dependencies
_List any added packages/services, or "None"._

## How to Test
1. \`bash scripts/agent/validate.sh backend\`
2. _steps to exercise this feature (fill in)_

## Notes / Follow-ups
_Known limitations or future work. (fill in)_
EOF
  ok "scaffolded $DOC"
else
  warn "$DOC already exists — leaving content as-is"
fi

# --- Add to mkdocs.yml Features nav if present --------------------------------
MKDOCS="mkdocs.yml"
if [ -f "$MKDOCS" ]; then
  REL="features/${BIN_ID}-${SLUG}.md"
  if ! grep -q "$REL" "$MKDOCS"; then
    LAST_FEATURE=$(grep -nE "features/(BIN-[0-9]+|[0-9])" "$MKDOCS" | tail -1 || true)
    if [ -n "$LAST_FEATURE" ]; then
      LINE_NUM=$(echo "$LAST_FEATURE" | cut -d: -f1)
      sed -i "${LINE_NUM}a\\      - $TITLE: $REL" "$MKDOCS"
      ok "added to $MKDOCS nav"
    else
      warn "could not find Features nav section in $MKDOCS"
    fi
  fi
fi

echo ""
echo "  Now WRITE the content in $DOC, then commit docs:"
echo "    git add docs/ mkdocs.yml && git commit -m \"docs: $TITLE\""
echo ""
echo "$DOC"
