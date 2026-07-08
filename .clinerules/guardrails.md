# NON-NEGOTIABLE GUARDRAILS (re-read every turn)

## Isolation

1. NEVER commit, edit files, or run `docker compose up` on the `main` branch or in
   the primary checkout. You MUST be inside a git worktree under `.worktrees/`.
   If `git rev-parse --abbrev-ref HEAD` says `main`, STOP and run
   `bash scripts/agent/setup-worktree.sh <feature-slug>` first.

2. NEVER use default ports (5432, 6379, 8000, 5173) or `docker compose` without
   `--env-file .env.local -p "$COMPOSE_PROJECT_NAME"`. Always start services via
   `bash scripts/agent/run-services.sh`, which uses your worktree's unique ports.

## Workflow

3. PLAN BEFORE CODE. An `implementation_plan.md` must exist in your worktree
   before you write any implementation code. Follow the plan.

4. COMMIT FREQUENTLY to your feature branch with conventional messages
   (`feat:`, `fix:`, `test:`, `docs:`). Never leave the tree dirty for long.

5. VALIDATE before declaring done: `bash scripts/agent/validate.sh` must pass.
   When the feature is complete, use `bash scripts/agent/finish-feature.sh` to
   merge into main, validate post-merge, tear down the worktree, and clean up.
   Handle exit codes: 0 = done, 1 = fix + re-run, 2 = resolve conflicts + re-run.

6. SCOPE DISCIPLINE — do not refactor code beyond what the feature requires.
   The `implementation_plan.md` defines scope — stick to it.

## Safety

7. NEVER `git push --force`, delete another branch/worktree, or `docker system prune`.

8. Before every commit, verify:
   - Commit messages MUST use conventional format: `feat:`, `fix:`, `test:`, `docs:`,
     `refactor:`, `chore:`. Never commit with messages like "update", "WIP", "asdf".
   - Check the diff for hardcoded ports (5432, 6379, 8000, 5173) or localhost URLs.
     These must come from environment variables.
   - No API keys, passwords, tokens, or secrets in the diff.
   - No `.env.local` files being committed (should be in `.gitignore`).
   - Never commit directly to `main`. Always be on a `feat/*` branch inside `.worktrees/`.

## Post-edit checks

9. After editing files in `src/`, `frontend/`, or `alembic/`:
   - If a new function or class was added, ensure a corresponding test exists or
     is planned.
   - If `configs/app_config.yaml` was modified, verify the change is reflected in
     `src/infra/config.py`.
   - Ensure no circular imports in new code.

## Session continuity

10. If a session is interrupted, check `Linear` status and the
     worktree state to resume where you left off.
