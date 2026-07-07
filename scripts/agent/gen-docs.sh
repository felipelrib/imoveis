#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# gen-docs.sh <feature-slug> "<Human Readable Title>"
#
# Scaffolds docs/features/<slug>.md (if absent) and wires links into
# docs/features/README.md (the index) and the root README "Features" section.
# It does the deterministic plumbing; the AGENT fills in the prose, then commits.
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
1. \`bash scripts/agent/run-services.sh\`
2. _steps to exercise this feature (fill in)_
3. \`bash scripts/agent/validate.sh\`

## Notes / follow-ups
_Known limitations or future work. (fill in)_
EOF
  ok "scaffolded $DOC"
else
  warn "$DOC already exists — leaving content as-is"
fi

# --- Ensure the features index exists and links this doc --------------------
INDEX="docs/features/README.md"
[ -f "$INDEX" ] || printf '# Features\n\nImplementation notes for each shipped feature.\n\n' > "$INDEX"
if ! grep -q "($SLUG.md)" "$INDEX"; then
  printf -- '- [%s](%s.md)\n' "$TITLE" "$SLUG" >> "$INDEX"
  ok "linked in $INDEX"
fi

# --- Add to mkdocs.yml nav if present ---------------------------------------
MKDOCS="mkdocs.yml"
if [ -f "$MKDOCS" ]; then
  # Add entry under "Features:" nav section if not already present
  if ! grep -q "features/$SLUG.md" "$MKDOCS"; then
    # Find the line with "- Config YAML Loader:" (last feature entry) and append after it
    if grep -q "features/config-yaml-loader.md" "$MKDOCS"; then
      sed -i "/features\/config-yaml-loader.md/a\\      - $TITLE: features/$SLUG.md" "$MKDOCS"
      ok "added to $MKDOCS nav"
    else
      # Fallback: append to the Features nav section
      awk -v slug="$SLUG" -v title="$TITLE" '
        /features\/README\.md/ && !done { print; printf "      - %s: features/%s.md\n", title, slug; done=1; next }
        { print }
      ' "$MKDOCS" > "$MKDOCS.tmp" && mv "$MKDOCS.tmp" "$MKDOCS"
      ok "added to $MKDOCS nav (fallback)"
    fi
  fi
fi

echo ""
echo "  Now WRITE the content in $DOC, then commit docs:"
echo "    git add docs/ mkdocs.yml README.md && git commit -m \"docs: $TITLE\""
echo ""
echo "$DOC"
