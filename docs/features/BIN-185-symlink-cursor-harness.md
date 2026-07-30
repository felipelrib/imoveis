# symlink-cursor-harness — Symlink .cursor harness and harden worktree ports

> Feature branch: `chore/symlink-cursor-harness` · Linear: `BIN-185` · Status: implemented

## Problem

Worktrees previously **copied** `.cursor/` from the primary checkout. Harness retrospect
edits in a worktree were lost on `teardown.sh --remove`, and parallel agents drifted.
Also, `.gitignore` used `.cursor/` (directory-only), so a worktree **symlink** at
`.cursor` appeared as untracked dirt and blocked `finish-feature.sh`. Port allocation
needed clearer `PLAYWRIGHT_PORT` handling separate from Compose frontend ports.

## Approach

- Symlink primary `.cursor` into each worktree (same pattern as `.venv`), with a safe
  legacy-directory replace (`rm -rf` only when the path is exactly that worktree's
  `.cursor` directory).
- Ignore `.cursor` without a trailing slash so both real dirs and symlinks stay local.
- Harden flock-based port registry / `resolve_playwright_port` usage in agent scripts.
- Document the harness symlink in ADR 0004.

## Changes

Files touched:

```
 scripts/agent/setup-worktree.sh              | Symlink .cursor from primary (legacy replace)
 scripts/agent/lib.sh                         | Port / Playwright resolution hardening
 scripts/agent/validate.sh                    | Use shared port helpers
 scripts/agent/finish-feature.sh              | Source env / port helpers
 docs/adr/0004-parallel-agent-workspaces.md   | Document .cursor symlink harness
 .gitignore                                   | Ignore .cursor symlink (not only .cursor/)
 docs/features/BIN-185-symlink-cursor-harness.md   | NEW — this doc
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh fast
# After setup-worktree: .cursor should be a symlink to primary
test -L .cursor && readlink .cursor
git check-ignore -v .cursor
bash scripts/agent/finish-feature.sh --dry-run
```

## Notes / Follow-ups

- Do not commit `.cursor` content; harness stays local on primary.
- Primary must keep a real `.cursor/` directory for worktrees to link to.
