# Goose to Cline Migration

This document records the migration from Goose (AI agent framework) to Cline
for the Imoveis project's agent workflow.

## What migrated

| Goose artifact | Replaced by |
|---|---|
| `.goosehints` | `.clinerules/project.md` |
| `.goose/guardrails.md` | `.clinerules/guardrails.md` |
| `recipes/feature-pipeline.yaml` | `.cline/skills/feature-pipeline/SKILL.md` |
| `recipes/plan-feature.yaml` | `.clinerules/planner.md` |
| `recipes/implement-feature.yaml` | `.clinerules/coder.md` |
| `.agents/agents/orchestrator.md` | `.clinerules/feature-workflow.md` |
| `.agents/agents/planner.md` | `.clinerules/planner.md` |
| `.agents/agents/coder.md` | `.clinerules/coder.md` |
| `.agents/agents/reviewer.md` | `.clinerules/reviewer.md` |
| `.cursor/hooks/on-save.md` | Merged into `.clinerules/guardrails.md` |
| `llms.txt` | Not needed (Cline manages its own context) |

## What stayed the same

- `scripts/agent/*.sh` — All 7 shell scripts are framework-agnostic bash.
  They work with any agent (Goose, Cline, or manual invocation).
- `FEATURES.md` — Enhanced with a `Depends on` column and Cline dispatch
  instructions. The tier system, feature specs, and dependency graph are intact.
- `configs/app_config.yaml` — Unchanged.
- All source code, tests, migrations, and frontend — unchanged.

## Key differences

### Goose was multi-agent parallel; Cline is single-agent sequential

Goose could run multiple agents simultaneously (1 orchestrator + 2 coders + planner),
each in their own isolated worktree, coordinating through the registry and port
allocation system. Cline operates as a single agent in one session.

**Adaptation:** Cline works on one feature at a time. The same worktree isolation
and port allocation still work (same scripts), but you dispatch features sequentially.
The two-phase "Plan All, then Implement All" model is preserved — it keeps one model
resident at a time on your 20 GB VRAM box.

### Goose had recipes; Cline has rules + skills

Goose recipes were YAML files with parameters, sub_recipes, model pinning, and
retry configs. Cline uses:
- **Rules** (`.clinerules/*.md`) — persistent instructions loaded based on file
  path matching via `paths:` frontmatter, or always-active without frontmatter.
- **Skills** (`.cline/skills/*/SKILL.md`) — on-demand instruction sets triggered
  by description matching or slash commands.

### Goose injected guardrails every turn; Cline loads rules via path matching

Goose's `.goose/guardrails.md` was injected into every agent turn via the framework.
Cline loads rules based on the `paths:` conditional in YAML frontmatter — rules
without frontmatter are always active.

**Adaptation:** The guardrails and project rules have no frontmatter (always active).
Persona rules (planner, coder, reviewer) use `paths:` to activate when relevant
files are in context.

## How to use

### Quick start

1. Open the project in your IDE with Cline
2. Say: `"What's next in FEATURES.md?"` — Cline will read the queue and suggest
   the next feature to work on based on tier/priority/dependencies
3. Say: `"Plan feature config-yaml-loader from FEATURES.md"` — triggers planner mode
4. Say: `"Implement feature config-yaml-loader from FEATURES.md"` — triggers coder mode
5. Say: `"Run feature config-yaml-loader from FEATURES.md"` — triggers the full pipeline skill
6. Use `/feature-pipeline` or `/validate-feature` slash commands for direct skill invocation

### Batch workflow (recommended for GPU efficiency)

1. Plan all pending features first (keeps deepseek-r1 resident):
   - `"Plan all pending features from FEATURES.md"`
2. Then implement them one by one (keeps devstral resident):
   - `"Implement the next feature from FEATURES.md"`

### Manual workflow (using scripts directly)

The shell scripts still work without any agent framework:
```bash
bash scripts/agent/setup-worktree.sh config-yaml-loader
cd .worktrees/config-yaml-loader
bash scripts/agent/run-services.sh
# ... implement manually ...
bash scripts/agent/validate.sh all
bash scripts/agent/merge-revalidate.sh
bash scripts/agent/gen-docs.sh config-yaml-loader "Wire app_config.yaml"
bash scripts/agent/teardown.sh --remove
```

## File structure

```
.clinerules/                    # Cline workspace rules
  project.md                    # Project context + lifecycle (always active, no frontmatter)
  guardrails.md                 # Hard rules + pre-commit checks (always active)
  feature-workflow.md           # Orchestrator logic (activates on FEATURES.md, docs/features/*)
  planner.md                    # Planner persona (activates on implementation_plan.md)
  coder.md                      # Coder persona (activates on src/**, frontend/**, alembic/**)
  reviewer.md                   # Reviewer persona (activates on docs/features/*)

.cline/skills/                  # Cline skills (on-demand)
  feature-pipeline/
    SKILL.md                    # Full pipeline: plan -> implement -> validate -> merge -> docs
  validate-feature/
    SKILL.md                    # Standalone validation skill

scripts/agent/                  # Framework-agnostic bash tooling (shared by all agents)
FEATURES.md                     # Feature queue with tiers, dependencies, and specs

# Legacy Goose configs (superseded, kept for reference)
.goosehints
.goose/guardrails.md
.agents/agents/
recipes/
llms.txt
```

## Notes

- The Goose configs (`.goosehints`, `.goose/`, `.agents/`, `recipes/`) are still
  in the repo as untracked files. They can be deleted once the Cline workflow
  is proven.
- The `.cline/` directory is in `.gitignore` (local to each developer).
  The `.clinerules/` directory is committed and shared via version control.
- The `scripts/agent/` scripts are the canonical tooling — both Goose and Cline
  workflows depend on them.
- Cline also supports `.cursorrules`, `.windsurfrules`, and `AGENTS.md` formats
  for cross-tool compatibility. See https://docs.cline.bot/customization/cline-rules.