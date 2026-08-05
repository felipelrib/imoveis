# Skill dispositions, docs pruning targets, CLAUDE.md inversions

## The 7 non-BMad skills (CAP-3)

| Skill | Load-bearing behavior worth keeping | Disposition |
|---|---|---|
| `feature-pipeline` | Plan→implement→validate→PR→merge→docs sequence; STOP-at-3-unexpected-files; story-key branch naming; feature-doc requirement | Delete. Sequence lives in bmad-loop story cycle + `scripts/agent` gates; discipline rules move into rewritten CLAUDE.md (CAP-4) and `_bmad/custom` overrides (CAP-6) |
| `babysit-pr` | CI-watch → fix-own-failures → re-run → merge → cleanup loop; "merged ≠ merge-ready" | Delete with **no absorption** — PR and remote CI are retired (CAP-8/9); nothing left to babysit |
| `code-review` | Generic diff review checklist | Delete. Superseded by `bmad-code-review` (adversarial layers) already installed |
| `epic-completion` | §A fresh re-read of sprint-status+epics before closing; §B leftovers checklist; §C close gate; never trust kickoff "not last" | Delete skill; the discipline is tracker-logic, not tooling — encode in rewritten CLAUDE.md tracking section (CAP-4) |
| `harness-retrospect` | Post-task rule-folding habit | Delete. `bmad-retrospective` covers epic-level; per-session rule-folding stays a CLAUDE.md habit line |
| `imoveis-planning-bridge` | BMad↔execution handoff map | Delete. Obsolete — BMad *is* the execution regime after this surgery |
| `security-scan` | Secret/injection scan patterns | Delete. Secret-scan one-liner already lives in CLAUDE.md commit rules; CI security workflow unchanged |

Also delete the global legacy `bmad-linear-bridge` reference from `~/.claude/CLAUDE.md` (OQ-3 resolved: global + Cursor surfaces in scope).

## GitHub surface dispositions (CAP-8/9)

| Surface | Disposition |
|---|---|
| `ci.yml` | Delete — merge gate moves fully local (`validate.sh` + pre-commit all-files parity) |
| `sonar-project.properties` (+ Sonar gate) | Delete — solo project; risk-tiered testing discipline remains the coverage policy |
| `docs.yml` | Keep — MkDocs Pages deploy is publishing, not a gate |
| `nightly.yml` | Trim to the scraper drift-canary job only — full-suite + dependency-audit jobs deleted (redundant with local gates) |
| `dependabot.yml` | Keep, advisory-only — bumps validated locally via `validate.sh` before merge; no CI checks on them |
| Branch protection / PR flow | Retire — finish gate = validate → local squash-merge → mandatory `push origin main` (origin = backup only) |

## Docs pruning targets (CAP-5)

| Doc | Action |
|---|---|
| `docs/harness-troubleshooting.md` | Keep incident-derived domain gotchas (BIN-77/79/82, task_routes, 0-processed…); rewrite the workflow sections that assume feature-pipeline/Linear; update the "validate recreates primary" guidance to the new invariant |
| `docs/development-guide.md`, `docs/deployment-guide.md` | Replace feature-pipeline/finish-feature narratives with BMad + bmad-loop + gates flow |
| `docs/source-tree-analysis.md` | Refresh `.claude/skills` inventory section |
| ADRs 0001–0004 | Do **not** rewrite history; add a superseded-by/amended note where 0005 + this surgery invalidate guidance (e.g. 0003 planning-bridge) |
| `docs/features/BIN-*`, `docs/chats_history/` | Untouched (history) |

## CLAUDE.md inversions (CAP-4)

| Current rule | Post-surgery rule |
|---|---|
| "Ticket → ship is ALWAYS feature-pipeline — never a BMad dev-side skill" | Ticket → ship is the bmad-loop story cycle (`bmad-create-story` → `bmad-dev-story` → `bmad-code-review`), which MUST call `scripts/agent` gates (validate → finish → merge) |
| "Do not let bmad-dev-story… run for ticket delivery" | BMad dev skills are the sanctioned executors, constrained by `_bmad/custom` overrides (CAP-6) |
| Session-end steps naming babysit-pr / epic-completion skills | Same discipline, stated inline (fresh sprint-status re-read, merge-then-done, docker-cleanup), no skill links |
| "finish-feature.sh --pr → squash-merge after CI green; babysit CI" | Finish = validate.sh all → local squash-merge → `git push origin main` → cleanup; no PR, no CI watch |
| Global `~/.claude/CLAUDE.md` PR-babysitting / bmad-linear-bridge passages; Cursor mirror equivalents | Rewritten in the same pass (OQ-3: yes) — zero Linear/PR/CI instructions on any surface |
| "validate.sh recreates primary Postgres — never run concurrently" (also project-context.md:82) | validate.sh never touches primary; concurrent backfills are safe (CAP-1 invariant) |
| Preserved unchanged | Branch discipline, conventional commits, secret rules, scoping STOP rule, domain validation hooks, feature-doc-per-story requirement, milestone ordering |
