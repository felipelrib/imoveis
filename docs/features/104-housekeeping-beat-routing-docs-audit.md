# Housekeeping: beat-routing invariant test, docs/features spot-check, stale milestone-doc refresh

> Feature branch: `feat/housekeeping-beat-routing-docs-audit` · Linear: `BIN-144` · Status: implemented

## Problem

Three small housekeeping items surfaced by the 2026-07-29 technical debt audit (epic BIN-128):

1. **No generic beat-routing invariant test.** `src/tests/unit/test_schedule.py` covered
   `task_routes` by enumerating each beat task name individually
   (`test_beat_maintenance_tasks_routed_to_scrapers_queue` and friends). A *newly added* beat
   task in `build_beat_schedule()` with a forgotten `task_routes` entry would not fail any
   existing test — it would silently land on the unconsumed default `celery` queue and never
   run, reproducing the BIN-76 class of bug (empty Dashboard pipeline history) without any test
   catching it.
2. **`docs/features/` had no spot-check in a while.** 100+ files exist with no CI enforcement
   that new PRs add a matching doc. Needed a manual sanity pass against `_template.md` and
   recent merged PRs to confirm no genuine gap had crept in.
3. **Drift between the Cursor and Claude/root harness docs.** A prior pass had already
   generalized the "Epic completion" milestone-ID guidance in `.cursor/rules/imoveis-core.mdc`
   and `.claude/skills/feature-pipeline/SKILL.md` / `imoveis-planning-bridge/SKILL.md` to derive
   the current milestone from Linear at runtime instead of hardcoding a v-number/epic-ID pair —
   but the equivalent section in the committed root `CLAUDE.md` was missed, so it still read
   `v0.5 epics are Linear parents (BIN-19..23); v0.6 is BIN-85 (BIN-86..95)` as if those were
   still the active milestones (they're both Done; the project is now on v0.10).

## Approach

1. Added `test_every_scheduled_task_has_a_route` to `TestBuildBeatSchedule`
   (`src/tests/unit/test_schedule.py`). It enables every optional beat branch at once (all
   scraping platforms, digest mode, top-deals digest, availability recheck, OSM amenities,
   transit proximity, neighbourhood access, listing-claim-stats), calls the real
   `build_beat_schedule()`/`make_celery()` (only `Celery`, `get_config`, `get_redis` are
   mocked), collects every distinct task name the schedule can produce, and asserts each one
   has a `task_routes` entry pointing at a queue workers actually consume (`scrapers` or `ai`).
   A sanity floor (`>= 10` distinct task names) guards against the maximal config silently
   failing to exercise a branch and the test going quietly toothless.
2. Spot-checked the 20 most recent numbered docs (90–103) against `_template.md`'s required
   sections (`Problem`, `Approach`, `Changes`, `New Dependencies`, `How to Test`,
   `Notes / Follow-ups`, header line) via `grep -L` per section — 100% compliant, no missing
   sections. Read three in full (96, 99, 103) for content-quality/PR-consistency — all
   substantive and accurate. The only irregularity found (duplicate number prefixes: four
   `90-*` and five `91-*` files) is the already-documented, expected artifact of parallel-agent
   PR races (`CLAUDE.md`'s Feature documentation section and the `feature-pipeline` skill both
   already describe this and only require renumbering on active collision, not retroactively).
   No genuine gap found — no follow-up tickets filed, per the ticket's own instruction not to
   blanket-assume proliferation is a problem.
3. Confirmed via `git blame`/`git check-ignore` that `.cursor/rules/imoveis-core.mdc` and the
   gitignored `.claude/skills/feature-pipeline/SKILL.md` / `imoveis-planning-bridge/SKILL.md`
   already carry the generalized, Linear-derived milestone guidance (no stale v0.5/v0.6
   references treated as current). Only the committed root `CLAUDE.md`'s "Epic completion
   (parent issues)" section still had the old hardcoded text — updated it to the same generic
   phrasing already used in `imoveis-core.mdc`, so the two harness copies no longer drift.

## Changes

Files touched:

```
 src/tests/unit/test_schedule.py                              | NEW test — generic beat-task-routed-somewhere invariant
 CLAUDE.md                                                     | Epic completion section: generic Linear-derived milestone guidance instead of hardcoded v0.5/v0.6 IDs
 docs/features/104-housekeeping-beat-routing-docs-audit.md     | NEW — this file
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
```

Targeted:

```bash
PYTHONPATH=src pytest src/tests/unit/test_schedule.py -v -m unit
```

`test_every_scheduled_task_has_a_route` fails if a future beat task is added to
`build_beat_schedule()` without a matching `task_routes` entry (or with one pointing at a queue
no worker consumes) — reverting the `celery_app.py` `task_routes` dict to omit any of the 11
currently-scheduled task names reproduces the failure locally.

## Notes / Follow-ups

- Tracked as part of the BIN-128 tech-debt remediation epic (v0.10 milestone).
- docs/features spot-check found no genuine gaps in the 20 most recent docs; the duplicate
  numbering pattern (`90-*` × 4, `91-*` × 5) is expected/accepted parallel-PR-race behavior,
  already documented elsewhere — not filed as a follow-up.
- Item 3 (stale milestone references) turned out to be *partially* already fixed in a prior,
  uncommitted pass — `.cursor/` and `.claude/skills/` (both gitignored/local) already had the
  generic wording; only the tracked `CLAUDE.md` needed the update landed here.
