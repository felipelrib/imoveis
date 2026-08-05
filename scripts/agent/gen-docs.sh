#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# gen-docs.sh <feature-slug> "<Human Readable Title>" [story-key]
#
# Scaffolds docs/features/<story-key>-<slug>.md (if absent) — named after the
# BMad story key from epics.md / sprint-status.yaml (e.g. v0.13-s1.1; unique by
# construction, so parallel PRs never collide) — and adds it to the mkdocs.yml
# Features nav. The agent fills in the prose, then commits.
#
# The story key may be passed as the 3rd arg; otherwise it is derived from the
# current branch name (e.g. `feat/v0.13-s1.1-...` -> v0.13-s1.1). Legacy
# `bin-147-...` branches still resolve to BIN-147 (pre-v0.13 docs keep their
# Linear-era names). If nothing can be derived, a vX.Y-sX.X placeholder is used
# and the agent is warned to rename the doc to the real story key before
# committing.
#
# Prints the doc path on the last line.
# ---------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

[ $# -ge 1 ] || die "usage: gen-docs.sh <feature-slug> \"<Title>\" [story-key]"
SLUG="$(sanitize_proj "$1")"
TITLE="${2:-$SLUG}"
KEY_ARG="${3:-}"
cd "$REPO_ROOT"

mkdir -p docs/features

# Resolve the story key (or legacy Linear ID) for the filename prefix.
BRANCH="$(current_branch)"
if [ -n "$KEY_ARG" ]; then
  STORY_KEY="$(printf '%s' "$KEY_ARG" | grep -oiE '(v[0-9]+\.[0-9]+-(s|fu)[0-9]+(\.[0-9]+)?|BIN-[0-9]+)' | head -1 || true)"
else
  # derive from branch: feat/v0.13-s1.1-... -> v0.13-s1.1 (legacy: bin-147 -> BIN-147)
  STORY_KEY="$(printf '%s' "$BRANCH" | grep -oiE 'v[0-9]+\.[0-9]+-(s|fu)[0-9]+(\.[0-9]+)?' | head -1 || true)"
  if [ -z "$STORY_KEY" ]; then
    STORY_KEY="$(printf '%s' "$BRANCH" | grep -oiE 'bin-[0-9]+' | head -1 | tr 'a-z' 'A-Z' || true)"
  fi
fi
if [ -z "$STORY_KEY" ]; then
  STORY_KEY="vX.Y-sX.X"
  warn "could not resolve story key (arg or branch) — using placeholder $STORY_KEY; RENAME the doc to the real key from epics.md/sprint-status.yaml before committing"
fi

DOC="docs/features/${STORY_KEY}-${SLUG}.md"

if [ ! -f "$DOC" ]; then
  DIFFSTAT="$(git diff --stat "$(git merge-base HEAD main 2>/dev/null || echo HEAD)"...HEAD 2>/dev/null | tail -n 20 || true)"
  cat > "$DOC" <<EOF
# $TITLE — <one-line description>

> Feature branch: \`$BRANCH\` · Story: \`$STORY_KEY\` · Status: implemented

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
  REL="features/${STORY_KEY}-${SLUG}.md"
  if ! grep -q "$REL" "$MKDOCS"; then
    LAST_FEATURE=$(grep -nE "features/(v[0-9]+\.[0-9]+-|BIN-[0-9]+|[0-9])" "$MKDOCS" | tail -1 || true)
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
