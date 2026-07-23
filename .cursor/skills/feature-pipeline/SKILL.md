---
name: feature-pipeline
description: >-
  Run the full feature pipeline (plan, implement, validate, PR, babysit CI, docs)
  for a Linear issue. Use when the user says "work on the next ticket",
  "run feature X", or "do the full pipeline".
---

# Full Feature Pipeline

End-to-end lifecycle for delivering a feature from Linear. One agent plans and implements (no dual-model handoff).

## Input

- `feature_slug`: kebab-case branch identifier
- `linear_issue_id`: e.g. `BIN-7`

If not provided, detect via milestone ordering in `.cursor/rules/imoveis-core.mdc`.

## Steps

### 1 — Select the next issue

1. List Linear milestones for project `2b293958-ee46-48f1-98aa-6d54abba468d`.
2. Earliest uncompleted milestone (lowest `sortOrder`, `status != done`).
3. Highest-priority unfinished issue in that milestone.

### 2 — Mark In Progress

Update issue state to `7de50ed1-0de6-4f06-89f6-6816991f106f`.

### 3 — Setup branch

```bash
bash scripts/agent/setup-branch.sh "<feature_slug>"
```

### 4 — Plan

Use Cursor Plan mode for non-trivial scope. Optionally write `implementation_plan.md` for long tasks. Then continue implementing in the same session.

### 5 — Start services

```bash
docker compose up -d
```

### 6 — Implement (TDD)

- Write failing tests first, then implement.
- Conventional commits after meaningful steps.
- If unclear or >3 unexpected files needed, STOP and ask.

### 7 — Validate

```bash
bash scripts/agent/validate.sh all
bash scripts/agent/validate-scrapers.sh --require-live
```

Must pass before proceeding. If live scraper validation fails due to HTML drift, refresh cassettes (see babysit-pr / testing rule) — do not skip the gate.

Fix failures, commit, re-validate until exit 0.

### 8 — Push & PR

```bash
bash scripts/agent/finish-feature.sh --pr
```

### 9 — Babysit PR

Read and follow [`.cursor/skills/babysit-pr/SKILL.md`](../babysit-pr/SKILL.md) until CI green and comments triaged.

### 10 — Linear Done

Update issue state to `fa058318-6dde-441e-91cb-5939c33e4fb1`.

### 11 — Feature documentation

Create `docs/features/<NN>-<feature-slug>.md` from `docs/features/_template.md` (all sections mandatory). Next number:

```bash
ls docs/features/ | grep -E '^[0-9]' | sort | tail -1
```

Commit and push the doc.

## Output

Report: branch name, PR URL, validation status, babysit outcome, Linear status, docs path.
