# Historical Story 2.1 halt report

Archived during the 2026-10-01 Windows migration audit from commit `f41972f`.
This is the original 2026-08-13 session report, not a new verification of the
primary database. Current tracking artifacts remain authoritative.
The orchestrator branch and paused run are preserved separately.

```markdown
---
status: blocked
story: '2-1-cohort-price-m2-percentiles-pipeline'
epic: 2
created: '2026-08-13'
baseline_revision: '7b7a4e33'
blocking_condition: 'Both Wave-0 gates for story 2.1 are unmet: (1) 2.1←2.7 — story 2-7 is `awaiting-operator`, its corpus-repair migration f3a7c81d5e42 is committed but NOT applied to the primary `realestate` DB, and applying it is an operator-only step; (2) epic-3-retro-item-3 (drain DW-32 before 2-1 leaves backlog) is still `open`. No implementation was started.'
---

# BMad Dev Auto Result — Story 2.1 (cohort price/m² percentiles pipeline)

Status: **blocked**
Halted at: step-01 (clarify and route), before spec generation.
Nothing was implemented; no source file was modified.

## Blocking condition

Story 2.1 carries two documented preconditions in the plan of record. Both are
currently unmet, and neither can be cleared from an unattended dev session.

### Gate 1 — `2.1←2.7`: the corpus repair has not landed

`sprint-status.yaml` holds `2-7-corpus-repair-fabricated-scores: awaiting-operator`.
Story 2.7's migration (`f3a7c81d5e42`) is merged on `main` but ships **un-applied**:
the repair only lands when the operator runs `bash scripts/agent/migrate-primary.sh`
against the primary corpus and then flips 2-7 to `done`.

Story 2.7's own acceptance criteria state the gate in these terms — "2.1 may start
once the repair **has landed**" (`epics.md`, Story 2.7, third AC) — and both
`spec-2-7-corpus-repair-fabricated-scores.md` (operator action 7) and the
DO-NOT-START comment sitting directly above the `2-1-…` key in `sprint-status.yaml`
name story 2-1 explicitly as the thing that must not begin first.

The gate is documentary, not machine-enforced, exactly as story 2.7 predicted.
Verified against the real parser this session:

```
next_actionable: Story(key='2-1-cohort-price-m2-percentiles-pipeline', epic=2,
                       num=1, slug='cohort-price-m2-percentiles-pipeline',
                       status='backlog', suffix='')
```

`awaiting-operator` is not in bmad-loop's `ACTIONABLE_STATUSES`, so `next_actionable()`
skips 2-7 and offers 2-1. The queue advancing to this story is the predicted
failure mode of the gate, not evidence that the gate is satisfied.

This session cannot verify the repair's application independently: it runs from a
linked worktree with no `.env.local`, and story 2.7's recovery query is specified to
run from the **primary** checkout. The tracked status is therefore the source of truth.

### Gate 2 — `epic-3-retro-item-3` (DW-32) is still open

`epic-3-retro-item-3-dw32-drain-before-epic-2: open`. The epic-3 retrospective
committed to driving DW-32 to `done` **before 2-1 leaves backlog**, and
`sprint-status.yaml`'s sequencing header places it in Wave 0 alongside 2-6 and 2-7.

DW-32 (`deferred-work.md`, severity **high**, status `open`) is `scripts/start.sh`
running `alembic upgrade head` against the primary `realestate` DB with no heartbeat
probe, no migration lock, and no refusal — bypassing the `backfill:gemma:migrating`
mutual exclusion that v0.13-fu6 built. Its own ledger entry records that fixing it is
"a decision about what `start.sh` should do when migrations are pending … plus an
audit of the remaining `scripts/*.sh` helpers", i.e. a separate work item.

It is not in story 2.1's scope, and doing it here would be an out-of-scope change to
`scripts/start.sh` and `scripts/agent/run-services.sh` on a story branch named for the
percentiles pipeline.

The two gates also interact: DW-32 is precisely the path by which the primary DB can
be migrated *without* the operator's guarded step, so leaving it open while gate 1's
migration sits pending is what makes gate 1's outcome unobservable.

## Why `blocked` and not `awaiting-operator`

The invocation instructed that a story whose **own acceptance criteria** require
human-only, outside-the-repo actions should be taken as far as an agent can, then
finalized to `awaiting-operator` rather than `blocked`.

That condition does not hold here. Story 2.1's acceptance criteria are entirely
agent-executable — pipeline-stage percentile computation, an `AppConfig`-owned
min-cohort threshold, an Alembic migration passing `alembic check`, a characterization
lock on the existing projection, and TDD boundary coverage in `src/core/`. None of them
requires a human outside the repo. The human-only action belongs to story **2.7**.

Marking 2-1 `awaiting-operator` would assert that its ACs are complete except for an
operator step, when in fact none are implemented. That status is also outside
bmad-loop's `ACTIONABLE_STATUSES`, so the queue would skip past 2-1 and offer 2-2 and
2-3 — both of which are gated on 2-1 (`2.2←2.1+2.6`, `2.3←2.1`) — cascading a
false-done through the rest of Epic 2. `blocked` is the honest status and produces the
escalation the DO-NOT-START comment was written to produce.

## To unblock

1. **Operator, from the primary checkout** — work story 2.7's `operator_actions`
   (`spec-2-7-corpus-repair-fabricated-scores.md`) in order: baseline recovery query →
   `migrate-primary.sh --dry-run` → `migrate-primary.sh` → record `N`/`M` → re-admission
   check via `backfill_gemma.py --status`. Then set
   `2-7-corpus-repair-fabricated-scores: done`.
2. **Drain DW-32** — decide what `start.sh` does with pending migrations (refuse and
   point at `migrate-primary.sh`, or delegate to it), audit the remaining `scripts/*.sh`
   helpers for other primary-stack mutations, and set
   `epic-3-retro-item-3-dw32-drain-before-epic-2: done`.
3. Re-drive `2-1-cohort-price-m2-percentiles-pipeline`. The DO-NOT-START comment above
   the 2-1 key can then be removed in the same edit that flips 2-7.

Alternatively, if the gates are to be **waived deliberately**, record that decision in
`sprint-status.yaml` (replacing the DO-NOT-START comment with the waiver and its
rationale) before re-driving — so the next session does not re-derive this same halt.

## Session facts

- Branch: `bmad-loop/20260813-054802-28e6/2-1-cohort-price-m2-percentiles-pipeline`
- Working tree: clean at halt except this result file.
- Branch/intent match: confirmed (branch slug equals the story key).
- Epic context: `epic-2-context.md` loaded from cache — valid (no planning artifact
  newer; both last touched in `8bc0f03`).
- Previous-story continuity: no Epic 2 spec with a lower story number exists, so no
  continuity decision was pending.
- No spec file was generated for story 2.1.
```
