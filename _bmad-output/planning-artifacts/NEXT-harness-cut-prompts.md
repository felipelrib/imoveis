# Harness-cut prompts for the sibling projects (and the next imoveis step)

Written 2026-10-07 after the imoveis harness cut (ADR 0007). Each block is a paste-ready intent for a **fresh** Claude Code session in that project. They reference the imoveis implementation as the template; copy from `C:\Workfolder\imoveis` rather than re-inventing.

Template files in imoveis: `scripts/agent/validate.py` (tiered gate + stamps + `--check-stamp`), `scripts/agent/ship.py`, `.claude/hooks/guard.py`, `.claude/hooks/auto_push.py`, `.claude/hooks/session_start.py`, `.claude/settings.json`, `src/tests/unit/test_claude_guard.py` (mutation probe), `AGENTS.md` + thin `CLAUDE.md`, `docs/adr/0007-tiered-gate-and-hook-enforced-push.md`, and the review `_bmad-output/planning-artifacts/research/harness-review-2026-10-07.md`.

---

## 1. nala-assistant (`C:\Workfolder\nala-assistant`)

```
Apply the imoveis harness cut to this repo (template: C:\Workfolder\imoveis, ADR 0007 and
_bmad-output/planning-artifacts/research/harness-review-2026-10-07.md there). Read those first,
then this repo's CLAUDE.md, AGENTS.md, .claude/settings.json, .bmad-loop/policy.toml,
scripts/validate.mjs, scripts/verify-gates.mjs, package.json. Do not run bmad-loop. Work on main
with small conventional commits; push only after npm run validate && npm run test:electron &&
npm run verify:gates are green.

Deliver, in this order:
1. Instruction files. Cut CLAUDE.md (713 lines, ~85% dated session log) to a thin file that
   imports AGENTS.md (`@AGENTS.md`) plus Claude-only mechanics. Rewrite AGENTS.md to <= 120
   lines of rules only (stack, layout, the enforced rules, the gate commands with measured
   timings, conventions); move the dated "Discovery intake / V1 decisions / Story 4.2 ..."
   narrative into docs/history/ (one file per dated section, verbatim) and link it. Fix the
   stale rules: the repo is NOT single-branch/no-gates — bmad-loop uses
   bmad-loop/<date>-manual/<story> branches and [verify] runs three commands.
2. Hooks (enforcement, not prose). Copy imoveis' .claude/hooks/guard.py pattern: deny git push
   to main without a validation stamp, deny any force push, deny edits to .env* and to the
   untracked discovery transcript / audio folders, deny `git add -A` (the repo relies on never
   running it). Add a Node-free stamp: scripts/validate.mjs writes
   .run/validated/<git tree sha>.<tier> on success; guard.py checks it (`node -e` or a tiny
   .mjs `--check-stamp`). Add session_start.py printing branch/dirty/stamp. Switch every hook
   command from bare `python3` to `uv run --no-project python` (the Store alias broke event
   writes before). Commit .claude/settings.json and .claude/hooks/ (un-ignore them; keep
   .claude/skills and settings.local.json ignored).
3. Gate tiers. Give scripts/validate.mjs a `--tier auto|docs|fast|full` mode chosen from
   `git diff --name-only origin/main...HEAD` + working tree (docs-only -> nothing but a link
   check; TS/renderer changes -> typecheck+lint+unit; electron/main-process or preload changes
   -> + test:electron). Measure each tier on this machine and write the numbers into AGENTS.md.
   Keep verify-gates.mjs (the mutation probe) and extend it with a case per new hook rule.
4. bmad-loop policy: keep [verify] as is but make the three commands call the tiered entry
   (`npm run validate -- --tier full`); add a post-run push via a Stop hook like imoveis'
   auto_push.py (push only when main is clean, ahead, not behind, stamped, and not inside a
   BMAD_LOOP_RUN_DIR session).
5. Write docs/adr/000N-harness-cut.md (same shape as imoveis ADR 0007) and update any doc
   that names the old flow. Finish with: files changed, measured tier timings, and the list of
   rules now enforced by hooks vs still prose.
```

## 2. personal-assistant (`C:\Workfolder\personal-assistant`)

```
Apply the imoveis harness cut to this repo (template: C:\Workfolder\imoveis, ADR 0007 and
_bmad-output/planning-artifacts/research/harness-review-2026-10-07.md). Read those, then this
repo's CLAUDE.md, AGENTS.md, .claude/settings.json, .bmad-loop/policy.toml, scripts/loop.sh,
scripts/git-autopush.sh, package.json and the lint checkers under scripts/. Keep the "commit
straight to main" model; the goal is one validate entrypoint, a stamp-gated push, and
bmad-loop verifying before it merges.

Deliver, in this order:
1. One gate: scripts/validate.mjs (or .py) with tiers chosen from the diff — docs (nothing),
   fast (typecheck + expo lint + the three checkers), full (+ jest with maxWorkers 50%);
   Kotlin changes additionally run the offline Kotlin gate. On success with a clean tree write
   .run/validated/<git tree sha>.<tier>. Measure each tier and record the numbers in AGENTS.md.
   Wire `npm run validate` to it.
2. Make the existing Stop hook scripts/git-autopush.sh stamp-aware: push only when the stamp
   for HEAD's tree exists (call the gate's --check-stamp). Add a PreToolUse guard.py (copy
   imoveis) denying push without stamp, force push, edits to .env* / credentials/, and
   `supabase db reset`-style destructive commands. Switch hook commands from bare python3 to
   `uv run --no-project python`. Commit .claude/settings.json and hooks.
3. bmad-loop: set [verify] commands to the fast tier (currently empty, so the orchestrator
   merges on review alone and the Stop hook then auto-pushes it). Keep scripts/loop.sh's
   post-run push but route it through the stamp check.
4. Instruction files: AGENTS.md <= 120 lines of rules; CLAUDE.md = `@AGENTS.md` + Claude-only
   lines; move the seven dated "validated lessons" into docs/lessons.md and link them; delete
   WSL-era paths (/home/felipe/..., ~/.zshrc) now that the host is native Windows.
5. ADR + doc sweep as in imoveis. Report files changed, measured timings, enforced-by-hook vs
   prose rules.
```

## 3. bmad-fanout (`C:\Workfolder\bmad-fanout`)

```
Apply the harness-cut recommendations from the imoveis review to this repo (template:
C:\Workfolder\imoveis ADR 0007 + research/harness-review-2026-10-07.md). This repo already has
the right gate shape (tiered scripts/validate.py with measured timings) — do not restructure
it. Add only what is missing:
1. Push guard + stamp: have scripts/validate.py write .run/validated/<git tree sha>.<tier> on
   success with a clean tree and expose `--check-stamp`; add .claude/hooks/guard.py (copy
   from imoveis) denying push to main without a stamp for the tier the diff needs (docs ->
   any stamp; src/ -> at least the `not engine` tier; engine/ changes -> full), any force
   push, and edits to .bmad-loop/policy.toml secrets or .env*. Add session_start.py. Commit
   .claude/settings.json + hooks (un-ignore).
2. Mutation probe: tests/test_claude_guard.py (copy the imoveis shape) — every rule gets a
   planted violation that must be denied and a benign neighbour that must pass.
3. bmad-loop [verify] commands: currently [] — set to the fast tier so the orchestrator never
   merges unverified work; keep the `implementation_handoff` partition.
4. AGENTS.md: cut the dated session narrative (lines ~145-236) into docs/history/ and keep
   AGENTS.md to rules + the tier table; make CLAUDE.md `@AGENTS.md` + Claude-only lines.
5. Fix the sprint-status drift: epics 1-4 are fully done but their epic keys still read
   backlog — set them to done with a dated comment; close the deferred-work entries that are
   already resolved.
Report files changed and the enforced-by-hook list. Do not touch engine/bmad-loop.lock.json
or the fork pin.
```

## 4. BMAD / bmad-loop upgrades (operator, per project)

```
# BMAD-METHOD 6.10 -> latest (non-interactive, keeps shims so create-story/dev-story still resolve)
npx --yes bmad-method@latest install -y --action update --shims
# then: ensure `uv` is on PATH (bmad-build halts without it); rename/copy overrides:
#   _bmad/custom/bmad-quick-dev.toml -> bmad-build.toml ; bmad-dev-auto.toml -> COPY to bmad-build-auto.toml
# bmad-loop: the installed tool is Felipe's fork (felipelrib/bmad-loop @ 2bbbd89, v0.10.0) that
# bmad-fanout pins — do NOT `uv tool upgrade bmad-loop` to upstream 0.13.1 until the fork is rebased;
# after any bmad-loop change run `bmad-loop init` and `bmad-loop validate --json` in each project.
```

## 5. Next step in imoveis

The next deliverable is the v0.14 epics. Paste `_bmad-output/planning-artifacts/NEXT-bmad-create-epics-prompt.md` into a fresh session (`bmad-create-epics-and-stories`), then `bmad-sprint-planning` to regenerate sprint-status.yaml. Both notes already reflect the new gate: stories validate with `python scripts/agent/validate.py` and ship with `python scripts/agent/ship.py`; bmad-loop runs the backend tier as `[verify]`.
