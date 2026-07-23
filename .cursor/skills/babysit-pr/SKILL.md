---
name: babysit-pr
description: >-
  Keep an Imoveis PR merge-ready by fixing CI, triaging comments, and resolving
  conflicts. Use after finish-feature.sh --pr, when the user says "babysit the
  PR", "watch CI", or "get this PR green".
---

# Babysit PR (Imoveis)

Get the current branch's PR to merge-ready: green CI, comments triaged, no blocking conflicts.

## Loop

1. **Identify PR**: `gh pr view --json number,url,statusCheckRollup,mergeable,reviewDecision`
2. **Conflicts**: If behind/conflicting with `main`, merge latest `main` intelligently. If intents conflict, STOP and ask.
3. **Comments**: Fetch unresolved review threads. Act on valid change requests. Validate Bugbot findings before applying; explain when disagreeing.
4. **CI failures**:
   - Reproduce locally when possible: `bash scripts/agent/validate.sh all` (or `fast` / `backend` matching the failed job).
   - Fix only issues caused by this PR's scope.
   - NEVER weaken CI workflows/checks just to pass.
   - If failure looks unrelated and branch is behind `main`, merge `main` and re-push.
   - **Scraper / cassette failures (`scrapers` job or `validate-scrapers.sh`)**:
     1. Read the log — if live HTTP worked but parse/normalize/zero listings → cassettes are **outdated**.
     2. Refresh: `python scripts/dev/record_scraper_cassettes.py`
     3. Adjust `src/tests/unit/test_scraper_cassettes.py` (and parser code if the site schema changed).
     4. Confirm: `bash scripts/agent/validate-scrapers.sh --require-live`
     5. Commit fixtures + tests (+ parser fixes) and push. Repeat until green.
     6. If the site is unreachable/blocked, retry or report the blocker — do not remove the scrapers gate.
5. **Push** scoped fixes (via normal git push after local validate, or re-run `finish-feature.sh --pr` if appropriate).
6. **Re-watch** until checks green + mergeable + comments triaged.

## Done when

- All required checks pass
- No unresolved blocking review comments you agree with
- PR is mergeable (or report the remaining blocker clearly)

## Output

PR URL, check status summary, what you fixed, remaining blockers (if any).
