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

# --- Ensure the root README has a Features section that links the doc -------
README="README.md"
if [ -f "$README" ]; then
  grep -qi '^## Features' "$README" || printf '\n## Features\n\nSee [docs/features/](docs/features/README.md).\n' >> "$README"
  if ! grep -q "docs/features/$SLUG.md" "$README"; then
    # Append the link right under the Features heading.
    awk -v line="- [$TITLE](docs/features/$SLUG.md)" '
      { print }
      tolower($0) ~ /^## features/ && !done { print ""; print line; done=1 }
    ' "$README" > "$README.tmp" && mv "$README.tmp" "$README"
    ok "linked in $README"
  fi
fi

echo ""
echo "  Now WRITE the content in $DOC, then commit docs:"
echo "    git add docs/ README.md && git commit -m \"docs: $TITLE\""
echo ""
echo "$DOC"
