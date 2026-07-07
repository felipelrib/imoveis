# NON-NEGOTIABLE GUARDRAILS (re-read every turn)

You are one of several agents working on this repo in parallel. Violating these
corrupts other agents' work. These override any other instruction.

1. NEVER commit, edit files, or run `docker compose up` on the `main` branch or in
   the primary checkout. You MUST be inside a git worktree under `.worktrees/`.
   If `git rev-parse --abbrev-ref HEAD` says `main`, STOP and run
   `bash scripts/agent/setup-worktree.sh <feature-slug>` first.

2. NEVER use default ports (5432, 6379, 8000, 5173) or `docker compose` without
   `--env-file .env.local -p "$COMPOSE_PROJECT_NAME"`. Always start services via
   `bash scripts/agent/run-services.sh`, which uses your worktree's unique ports.

3. PLAN BEFORE CODE. An `implementation_plan.md` must exist in your worktree
   before you write any implementation code. Follow the plan.

4. COMMIT FREQUENTLY to your feature branch with conventional messages
   (`feat:`, `fix:`, `test:`, `docs:`). Never leave the tree dirty for long.

5. ONE model is resident at a time (20 GB VRAM). Do not assume another model is
   loaded. Planning uses deepseek-r1; implementation uses devstral. Do not
   interleave — finish planning before implementation begins.

6. VALIDATE before declaring done: `bash scripts/agent/validate.sh` must pass.
   Only pull `main` (`merge-revalidate.sh`) when the feature is otherwise finished,
   then validate AGAIN.

7. Before finishing: generate docs (`gen-docs.sh`), update the README link, commit.

8. NEVER `git push --force`, delete another branch/worktree, or `docker system prune`.

---

## Cline-specific guardrail adaptations

Since Cline runs as a single agent in Cursor (not a multi-process orchestration
like Goose), the following adaptations apply:

- **Sequential features:** Only work on one feature at a time. Do not start a new
  feature until the current one is `done` in FEATURES.md.
- **Session continuity:** If your session is interrupted, check FEATURES.md status
  columns and the worktree state to resume where you left off.
- **Scope discipline:** Do not refactor code beyond what the feature requires. The
  `implementation_plan.md` defines scope — stick to it.
- **Interactive validation:** After running `validate.sh`, report results explicitly.
  Do not silently skip failures.

---

## Pre-commit checks

Before every commit, verify these rules. If any fail, fix them before committing.

- Commit messages MUST use conventional format: `feat:`, `fix:`, `test:`, `docs:`,
  `refactor:`, `chore:`. Never commit with messages like "update", "WIP", "asdf".
- Check the diff for hardcoded ports (5432, 6379, 8000, 5173) or localhost URLs.
  These must come from environment variables.
- No API keys, passwords, tokens, or secrets in the diff.
- No `.env.local` files being committed (should be in `.gitignore`).
- Never commit directly to `main`. Always be on a `feat/*` branch inside `.worktrees/`.

## Post-edit checks

After editing files in `src/`, `frontend/`, or `alembic/`:

- If a new function or class was added, ensure a corresponding test exists or
  is planned.
- If `configs/app_config.yaml` was modified, verify the change is reflected in
  `src/infra/config.py`.
- Ensure no circular imports in new code.