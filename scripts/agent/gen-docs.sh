#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# gen-docs.sh <feature-slug> "<Human Readable Title>"
#
# Scaffolds docs/features/<slug>.md (if absent) and adds it to the
# mkdocs.yml nav. The agent fills in the prose, then commits.
#
# Prints the doc path on the last line.
# ---------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

[ $# -ge 1 ] || die "usage: gen-docs.sh <feature-slug> \"<Title>\""
SLUG="$(sanitize_proj "$1")"
TITLE="${2:-$SLUG}"
cd "$REPO_ROOT"

DOC="docs/features/$SLUG.md"
mkdir -p docs/features

if [ ! -f "$DOC" ]; then
  DIFFSTAT="$(git diff --stat "$(git merge-base HEAD main 2>/dev/null || echo HEAD)"...HEAD 2>/dev/null | tail -n 20 || true)"
  cat > "$DOC" <<EOF
# $TITLE

> Feature branch: \`$(current_branch)\` · Status: implemented

## Problem
_What user/business problem does this solve? (fill in)_

## Approach
_Architectural approach and key decisions. (fill in)_

## Changes
Files touched (auto from diff — prune/annotate as needed):

\`\`\`
$DIFFSTAT
\`\`\`

## New dependencies
_List any added packages/services, or "none". (fill in)_

## How to test
1. \`bash scripts/start.sh\`
2. _steps to exercise this feature (fill in)_
3. \`bash scripts/test.sh all\`

## Notes / follow-ups
_Known limitations or future work. (fill in)_
EOF
  ok "scaffolded $DOC"
else
  warn "$DOC already exists — leaving content as-is"
fi

# --- Add to mkdocs.yml nav if present ---------------------------------------
MKDOCS="mkdocs.yml"
if [ -f "$MKDOCS" ]; then
  if ! grep -q "features/$SLUG.md" "$MKDOCS"; then
    LAST_FEATURE=$(grep -n "features/" "$MKDOCS" | tail -1)
    if [ -n "$LAST_FEATURE" ]; then
      LINE_NUM=$(echo "$LAST_FEATURE" | cut -d: -f1)
      sed -i "${LINE_NUM}a\\      - $TITLE: features/$SLUG.md" "$MKDOCS"
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
