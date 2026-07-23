#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# gen-docs.sh <feature-slug> "<Human Readable Title>"
#
# Scaffolds docs/features/<NN>-<slug>.md (if absent) from the next free
# number and adds it to the mkdocs.yml Features nav. The agent fills in
# the prose, then commits.
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

mkdir -p docs/features

# Next NN from existing numbered docs (01, 02, …)
LAST_NN="$(
  find docs/features -maxdepth 1 -name '[0-9][0-9]-*.md' -printf '%f\n' 2>/dev/null \
    | sed -n 's/^\([0-9][0-9]\)-.*/\1/p' \
    | sort -n \
    | tail -1
)"
if [ -z "$LAST_NN" ]; then
  NEXT_NN=1
else
  NEXT_NN=$((10#$LAST_NN + 1))
fi
NN="$(printf '%02d' "$NEXT_NN")"

DOC="docs/features/${NN}-${SLUG}.md"

if [ ! -f "$DOC" ]; then
  DIFFSTAT="$(git diff --stat "$(git merge-base HEAD main 2>/dev/null || echo HEAD)"...HEAD 2>/dev/null | tail -n 20 || true)"
  cat > "$DOC" <<EOF
# $TITLE — <one-line description>

> Feature branch: \`$(current_branch)\` · Linear: \`BIN-XX\` · Status: implemented

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
  REL="features/${NN}-${SLUG}.md"
  if ! grep -q "$REL" "$MKDOCS"; then
    LAST_FEATURE=$(grep -n "features/[0-9]" "$MKDOCS" | tail -1 || true)
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
