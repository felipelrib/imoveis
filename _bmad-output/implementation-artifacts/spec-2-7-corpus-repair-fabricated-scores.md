---
title: 'Story 2.7 — Corpus repair: rows poisoned with fabricated scores before s3.2'
type: 'bugfix'
created: '2026-08-13'
status: 'awaiting-operator'
baseline_revision: '8bc0f03c1e01c62417b9837e8cc6fa35b6bfc414'
final_revision: '218364d8cdada1c34b6ec20b9c62f7bbefaac9c0'
review_loop_iteration: 0
followup_review_recommended: true
operator_actions:
  - 'Run the read-only baseline count FIRST, from the primary checkout, before applying anything: the recovery query in `docs/features/v0.13-s2.7-corpus-repair-fabricated-scores.md` (Operator procedure). Its `still_poisoned` column is the `N` the migration should report. If it already reads 0, the migration has ALREADY been applied incidentally by `scripts/start.sh` / `run-services.sh` (DW-32 — both run `alembic upgrade head` against the primary with no lock, and `start.sh` prints migration output only on failure, so the count line was swallowed); in that case skip the apply and go straight to the re-admission check.'
  - 'Apply the repair to the PRIMARY `realestate` DB — the one thing this session must never do. From the PRIMARY checkout (never a worktree; the script''s refusal only fires when a `.env.local` exists and names a non-primary project, so it will NOT stop you from the wrong checkout): (1) `PYTHONPATH=src python scripts/dev/backfill_gemma.py --status` and note `enriched`/`remaining`; (2) `bash scripts/agent/migrate-primary.sh --dry-run` to probe the guard keys without touching anything — if it reports a live `backfill:gemma:active` heartbeat, stop the runner first and re-check, and never delete either guard key by hand (both self-clear on their TTLs); (3) `bash scripts/agent/migrate-primary.sh` to take `backfill:gemma:migrating` and run `alembic upgrade head`.'
  - 'Read the repaired count off the upgrade output. Migration `f3a7c81d5e42` logs at INFO on the `alembic` logger: `v0.13-s2.7 corpus repair: nulled N fabricated ai_score metrics rows (M of them sat on the 0.5 doubly-fabricated blend)`. `M < N` is expected and correct — the difference is the half-fabricated population a blend-value predicate would have missed. Both are metrics-row counts, not property counts. Record N and M; the repair writes no per-row marker, so these two numbers plus the recovery query are the story''s only outcome evidence.'
  - 'Verify re-admission: re-run `PYTHONPATH=src python scripts/dev/backfill_gemma.py --status` and confirm `remaining` grew, then `--dry-run` to confirm the repaired rows are planned. Expect growth of LESS than N — the candidate path is `active_only` and photo-gated, so inactive and photo-less repaired rows are re-admitted to the SQL predicate but not to the work queue. No process restart and no code change are needed; the candidate push-down is already `ai_score IS NULL OR ai_score = 0`. Restart the backfill and let it re-enrich them.'
  - 'Check the attempt ledger AFTER applying, not before: retirement is Redis-side (`<prefix>:attempts`, `backfill.max_attempts` 3) and is not cleared on success. Poisoned rows are expected to sit at `attempts == 1` and need nothing; only if `--status` shows repaired rows quarantined should you run `backfill_gemma.py --reset-quarantine`.'
  - 'Let the bmad-loop orchestrator merge this branch. `finish-feature.sh` refuses every `bmad-loop/<run>/<story>` branch by design (v0.13-fu11) — do not merge by hand.'
  - 'After the merge lands on `main` and is pushed AND the repair has actually been applied, set `2-7-corpus-repair-fabricated-scores: done` in `_bmad-output/implementation-artifacts/sprint-status.yaml` (it is `awaiting-operator` now). Do NOT let story 2-1 start before that flip: `awaiting-operator` is not in bmad-loop''s ACTIONABLE_STATUSES, so `next_actionable()` skips 2-7 and offers `2-1-cohort-price-m2-percentiles-pipeline` — the 2.1←2.7 gate is documentary, not machine-enforced. A DO-NOT-START comment now sits above the 2-1 key.'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
warnings: ['oversized']
---

<intent-contract>

## Intent

**Problem:** Before story 3.2 landed, every AI client exception fallback persisted a fabricated `condition_score`/`sentiment_score` of `0.5` with `analysis="Error"` into `metrics_scoring.meta`, and `ai_score` was blended from those fabrications. `mode_is_missing_ai` is literally `not score` (`src/core/enrichment_rerun.py:85-91`), so a truthy fabricated score puts the row **permanently** outside the enrichment candidate set — nothing re-queues it, ever. Story 3.2 stopped new fabrication but repaired nothing retroactively; these rows are the missing half of the Epic 3 → Epic 2 gate.

**Approach:** Ship a one-off, data-only Alembic migration that nulls `ai_score` on exactly the rows carrying the fabrication marker, so `mode=missing` re-admits them and the running backfill re-enriches them on its next census. The forensic predicate (`meta->'visual'->>'analysis' = 'Error'` and the sentiment twin) lives **only** inside that migration file; an integration test imports it from there and locks its include/exclude boundary against a seeded matrix. Application to the primary `realestate` DB is the operator's guarded step (`scripts/agent/migrate-primary.sh`), never an agent action and never an unguarded script.

## Boundaries & Constraints

**Always:**
- The forensic predicate exists in exactly ONE place: the new `alembic/versions/*.py` file. The test imports it from that module rather than restating it.
- `metrics_scoring.meta` is Postgres `json`, **not `jsonb`** — never cast to `jsonb` (it rejects NUL unicode escapes that scraped free text legitimately carries). Extract with `->`/`->>` and guard every extraction with a nested `CASE WHEN json_typeof(...) = 'object'`, because `json -> text` is undefined for scalars and `AND` is not guaranteed to short-circuit (precedent: `src/adapters/db/enrichment_coverage_queries.py:87-131`).
- The repair is a single set-based `UPDATE … WHERE <predicate>` — never read-then-write — so a row honestly re-scored between planning and execution is not clobbered.
- `neutral_sentiment_no_description()`'s honest `0.5` sentiment (`analysis=""`, `reasoning="No listing description available; sentiment skipped."`) must be left untouched. This is the exclusion the characterization test exists to protect.
- The migration reports the count it touched, on the `alembic` logger at INFO (`alembic.ini:23-24` sets `logger_alembic level = INFO`), so `migrate-primary.sh` output carries it.
- `down_revision` is the current head `b65411932ef9`.

**Block If:**
- The repair would require any schema change (new column, new table) — it must not.
- The predicate cannot be expressed without touching rows that `neutral_sentiment_no_description()` produced.

**Never:**
- Never run `migrate-primary.sh`, `alembic upgrade` against the primary DB, or any mutation of the primary `realestate` corpus from this session — that is the operator's step, and `migrate-primary.sh` refuses to run from a linked worktree by design (`scripts/agent/migrate-primary.sh:48-56`).
- Never put the `analysis == "Error"` string test into `src/` — story 3.2's contract forbids it as a runtime signal; `degraded: bool` (`src/adapters/ai/client.py:328-340`) is the runtime marker and stays the only one.
- Never deliver this as a `scripts/dev/` script (it would have to re-implement the `backfill:gemma:migrating` mutual-exclusion that `migrate-primary.sh` already owns — a second, divergent copy of v0.13-fu6) or as an admin endpoint (that puts the forensic predicate in feature code).
- Never touch `combined_score`/`combined_score_rent`/`combined_score_sale` — see Design Notes.
- No new config keys, no changes to `src/core/enrichment_rerun.py`, `src/core/backfill_runner.py`, or `scripts/dev/backfill_gemma.py`.

## I/O & Edge-Case Matrix

Seeded `metrics_scoring` row → does the repair predicate select it?

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Canonical poison | `meta.visual.analysis='Error'` + `meta.sentiment.analysis='Error'`, `ai_score=0.5` | SELECTED; `ai_score` → NULL | No error expected |
| Visual-only poison, blend lands on 0.5 | `meta.visual.analysis='Error'`, honest sentiment `0.5`, `ai_score=0.5` | SELECTED; `ai_score` → NULL | No error expected |
| Sentiment-only poison, blend lands on 0.5 | honest visual `0.5`, `meta.sentiment.analysis='Error'`, `ai_score=0.5` | SELECTED; `ai_score` → NULL | No error expected |
| Half-poisoned, blend off 0.5 | `meta.visual.analysis='Error'`, honest sentiment `0.8`, `ai_score=0.59` | SELECTED; `ai_score` → NULL (marker, not the blend value, is the signature) | No error expected |
| Honest neutral sentiment | real visual prose + `meta.sentiment` from `neutral_sentiment_no_description()` (`analysis=''`, sentinel `reasoning`), `ai_score=0.5` | NOT selected; row untouched | No error expected |
| Fully honest, coincidental 0.5 | real prose in both, `ai_score=0.5` | NOT selected; row untouched | No error expected |
| Post-3.2 shaped honest row | real prose, `degraded: false` present on both blobs | NOT selected | No error expected |
| Already repaired / never scored | marker present, `ai_score IS NULL` | NOT selected (nothing to null; keeps the reported count honest) | No error expected |
| `meta` is SQL NULL | `meta IS NULL`, `ai_score=0.5` | NOT selected | No error expected |
| `meta` is a JSON scalar | `meta = '"broken"'::json` or `'null'::json`, `ai_score=0.5` | NOT selected | Must NOT raise `cannot extract element from a scalar` |
| `meta.visual` is a JSON scalar | `meta = '{"visual": 3}'::json` | NOT selected | Must NOT raise |
| `meta` object without the keys | `meta = '{"stat_analysis": "x"}'::json` | NOT selected | No error expected |
| Repaired row re-admitted | after repair, `mode_is_missing_ai(metrics)` for a selected row | `True` (was `False` before) | No error expected |
| Empty corpus | no matching rows | `UPDATE` affects 0 rows; migration logs `0`; no failure | No error expected |

</intent-contract>

## Code Map

- `alembic/versions/b65411932ef9_add_indexes_properties_active_metrics_.py:30` -- current head; the new migration's `down_revision`.
- `src/adapters/db/models.py:154-188` -- `MetricsScoring`: `ai_score = Column(Float)` (`:164`), `meta = Column(JSON)` (`:187`). No unique constraint on `property_id`. `ai_score` is **not** on `properties`.
- `src/adapters/queue/tasks.py:766-783` -- the blend (`condition_score * ai.visual_weight + sentiment_score * ai.text_weight`) and `meta["visual"] = v_res.model_dump()` / `meta["sentiment"] = s_res.model_dump()` — the exact persisted shape.
- `src/adapters/ai/client.py:683,712,870,906` -- the pre-3.2 exception fallbacks that wrote `analysis="Error"` with `0.5`; `:328-340` the post-3.2 `degraded: bool` marker; `:247` `AIResultDegradedError`.
- `src/adapters/queue/tasks.py:760-765` -- post-3.2 refusal: a degraded result raises *before* `SessionLocal()`, so no honest row written after 3.2 can carry the marker.
- `src/adapters/ai/enrich_pipeline.py:16-30` -- `neutral_sentiment_no_description()`, the honest `0.5` that must survive.
- `src/core/enrichment_rerun.py:85-91` -- `mode_is_missing_ai` = `not score`; `:279-286` the SQL candidate push-down (`ai_score IS NULL OR ai_score = 0`).
- `src/adapters/db/enrichment_coverage_queries.py:87-131` -- the `json`-not-`jsonb` rationale and the `CASE WHEN json_typeof(...)` scalar guard to mirror.
- `scripts/agent/migrate-primary.sh:262-340` -- takes `backfill:gemma:migrating`, refuses on a live `backfill:gemma:active`, then `alembic upgrade head`; `--dry-run` at `:33-39`.
- `src/tests/integration/conftest.py:15-42` -- `wipe_safe_db_session` + the primary-DB refusal guard.
- `src/tests/integration/test_scoring_sql_assembly.py:49-80` -- `_neighborhood` / `_property` seeding helpers to mirror.
- `docs/features/_template.md` -- mandatory feature-doc sections.

## Tasks & Acceptance

**Execution:**
- [x] `alembic/versions/f3a7c81d5e42_repair_fabricated_ai_scores.py` -- new data-only migration: module-level `FABRICATION_PREDICATE_SQL` (the guarded `json` predicate), `apply_repair(connection) -> dict[str, int]` returning `{"repaired": n, "on_blend": m}` and logging both, `upgrade()` calling it via `op.get_bind()`, `downgrade()` a deliberate logged no-op (see Design Notes). Docstring records the delivery-mechanism rationale (why migration, not script, not endpoint) -- the one-off repair artifact; nothing in `src/` may import it.
- [x] `src/tests/integration/test_corpus_repair_fabricated_scores.py` -- new `@pytest.mark.integration` suite: imports the migration module by path, seeds the full I/O matrix, asserts the predicate's include/exclude boundary, runs `apply_repair`, asserts only included rows were nulled, asserts the returned counts, and asserts `mode_is_missing_ai` flips `False → True` for repaired rows and stays `False` for the honest-neutral row -- the characterization lock required before the repair is applied.
- [x] `docs/features/v0.13-s2.7-corpus-repair-fabricated-scores.md` -- feature doc from `_template.md` verbatim; records the delivery-mechanism decision + rationale, the operator apply/verify procedure, and the `combined_score` residual.
- [x] `_bmad-output/implementation-artifacts/sprint-status.yaml` -- set `2-7-corpus-repair-fabricated-scores` to `awaiting-operator` (the orchestrator's confirm flips it to `done`, matching stories 3-2…3-5).

**Acceptance Criteria:**
- Given a corpus with the seeded matrix, when the repair runs, then only marker-carrying rows with a non-NULL `ai_score` are nulled, every other row is byte-identical, and the reported count equals the number nulled.
- Given the repair has run, when the backfill takes its next census, then the repaired rows appear as candidates with no process restart and no code change (they satisfy `ai_score IS NULL`, which is already the candidate push-down).
- Given `validate.sh backend` runs `alembic upgrade head` against the ephemeral test DB (`scripts/agent/ensure-test-db.sh:90-93`), when the new migration is applied to an empty schema, then it succeeds, affects 0 rows and does not change `alembic check`'s verdict.
- Given the story is code-complete, when the session ends, then the spec is `awaiting-operator` with a non-empty `operator_actions` list covering the primary-DB apply and its verification — the agent never mutates the primary corpus.

## Spec Change Log

## Review Triage Log

### 2026-08-13 — Review pass 1 (Blind Hunter + Edge Case Hunter, parallel)

- intent_gap: 0
- bad_spec: 0
- patch: 13: (high 2, medium 6, low 5)
- defer: 3: (high 0, medium 3, low 0)
- reject: 7: (high 0, medium 3, low 4)
- addressed_findings:
  - `[high]` `[patch]` `DOUBLY_FABRICATED_BLEND` was computed from `get_config()` at module import. Verified failure: `python3 -m alembic history` without `src/` on `PYTHONPATH` raised `ModuleNotFoundError: No module named 'infra'` — alembic imports every version script to build its revision map and `history`/`heads`/`branches` never run `env.py`. It was also backwards on its own terms (poisoned rows are frozen history; a weight retune would move the constant off every one of them and report `on_blend = 0`) and made the test tautological, since it seeded `ai_score = BLEND` from the same source. Pinned at `0.5`, dropped the `infra.config` import, added `test_blend_constant_is_pinned_history_not_live_config`. `alembic history` now succeeds with `PYTHONPATH` unset.
  - `[high]` `[patch]` The `2.1←2.7` gate is not machine-enforced: `awaiting-operator` is not in bmad-loop's `ACTIONABLE_STATUSES`, so `next_actionable()` skips 2-7 and returns `2-1-cohort-price-m2-percentiles-pipeline` (verified against the real parser) — handing 2.1 to the next loop iteration before the operator has applied anything. Added an explicit DO-NOT-START block comment above the `2-1` key in `sprint-status.yaml`, plus notes in the feature doc and `operator_actions`.
  - `[medium]` `[patch]` `on_blend` was counted in a separate statement before the `UPDATE`, so a row re-enriched between the two could be counted and then not repaired, yielding `on_blend > repaired`. Rewritten as one statement: a `targets` CTE plus a data-modifying `repaired` CTE joined back, both on the same snapshot, so `on_blend <= repaired` holds by construction — and the join is also the only way to read the pre-update `ai_score` (`UPDATE ... RETURNING` hands back the new value, always NULL).
  - `[medium]` `[patch]` The predicate was three-valued: a `meta -> 'visual'` object carrying no `analysis` key gives `NULL = 'Error'` → NULL, so the whole expression was NULL rather than false. Harmless in `WHERE`, wrong when projected as a boolean or reused under `NOT (...)`, and it is the shape `test_properties_ai_scores.py` already seeds. Wrapped both branches in `COALESCE(..., false)` and added two matrix rows for it (beyond the frozen matrix in the read-only intent contract).
  - `[medium]` `[patch]` The seeding fixture relied on `wipe_safe_db_session`, which wipes on *teardown* only, while the marker projection and `apply_repair` scan the whole table under exact-equality count assertions. Now empties `metrics_scoring` before seeding, matching the precedent `test_enrichment_coverage_sql.py` documents for the same hazard.
  - `[medium]` `[patch]` The "inherits the backfill mutual exclusion for free" rationale held only for the `migrate-primary.sh` entry point. `scripts/start.sh:63` and `scripts/agent/run-services.sh:42` run `alembic upgrade head` against the primary project with no lock and no heartbeat probe (DW-32, open/high, same wave), and `start.sh` prints migration output only on failure, so an incidental apply swallows the `N`/`M` line. Documented in the migration docstring, the spec and the feature doc, with a read-only recovery query that reconstructs the population at any time.
  - `[medium]` `[patch]` The marker-only predicate is a deliberate *widening* of the AC's written Given (which names the marker plus `ai_score` on the 0.5 blend), not a reading of it. Now stated as a recorded deviation in the migration docstring, the spec and the feature doc instead of being presented as satisfying the AC.
  - `[medium]` `[patch]` Both artifacts claimed `migrate-primary.sh` refuses to run from a linked worktree. Its guard fires only when a `.env.local` exists *and* names a non-primary project; a worktree with none falls through to the primary defaults. Corrected to "run it from the primary checkout deliberately" (the intent contract's copy of the claim is read-only, so the correction is recorded in Design Notes) and ledgered.
  - `[low]` `[patch]` "The repair itself guarantees the row will be touched again" is false for the ~494 inactive un-enriched rows (`active_only` census) and for photo-gated rows. Scoped the self-healing claim and documented both populations.
  - `[low]` `[patch]` Log line and operator doc implied property counts and said "sat **exactly** on the blend" over a tolerance comparison. Now says "metrics rows" (`property_id` has no unique constraint) and drops "exactly".
  - `[low]` `[patch]` The Verification grep was quote-sensitive (`"'Error'"` against a double-quoted literal) and already hit on this branch. Replaced with a scoped `git grep -nE "[\"']Error[\"']" src/adapters src/core src/api`, plus an `alembic history` check that proves no version script imports from `src/`.
  - `[low]` `[patch]` Feature-doc header said `Status: implemented` for work whose value depends on an un-applied operator step; now `implemented, awaiting operator apply`. "leaves `alembic check` clean" corrected to "does not change its verdict" (that check is informational-only here).
  - `[low]` `[patch]` Added the pinned-constant regression test (counted above with the blend fix; listed separately because it is new coverage, not a correction).

Deferred (3, all ledgered in `deferred-work.md`): the still-live third fabricated-`0.5` tap in `client.py`'s non-exception `build()` paths, which carries neither the marker nor `degraded: true`; the fabricated `meta` blobs that survive the repair, which a `stages=verdict_only` rerun would launder into a non-degraded `deal_verdict` and which the coverage card counts as covered; and `migrate-primary.sh`'s worktree guard falling through when no `.env.local` exists.

Rejected (7): an env-var assert in `upgrade()` to force the `migrate-primary.sh` entry point (would hard-break `scripts/start.sh` for everyone); offline `--sql` mode handling (no consumer in this repo, and it would add an untested branch); batching the `UPDATE` with a `lock_timeout` (corpus is small and the migration lock is already held); "photo-gated rows lose their score permanently" (an honest NULL is the correct outcome and strictly better than the fabricated value — documented, not fixed); "`upgrade()` is untested" (`validate.sh backend` runs `alembic upgrade head` against the ephemeral DB, which exercises it); duplicate metrics rows skewing `N` (addressed by wording rather than a `DISTINCT` the repair should not have); and the frontmatter/`oversized`-warning hygiene notes (protocol-correct as written).

## Design Notes

**Why a data-only Alembic migration.** Three mechanisms were considered; the AC requires the choice and rationale on record.
- *Migration (chosen).* Runs exactly once by construction (`alembic_version`), so it cannot become a recurring path. The forensic predicate sits in a versioned one-off artifact, outside `src/`. `migrate-primary.sh` is already the sanctioned guarded path and gives the backfill mutual exclusion (`backfill:gemma:migrating` + refusal on a live `:active`) for free — no new guard code, no second copy of v0.13-fu6.
- *`scripts/dev/` script (rejected).* Matches the one-off-surgery precedent and has a nicer dry-run, but the AC forbids "an unguarded script against a live backfill", so it would have to re-implement the migration-lock handshake — a divergent second copy of exactly the machinery fu6 centralized.
- *Admin endpoint (rejected).* Puts `analysis == "Error"` inside feature code on a re-runnable route, which story 3.2's contract explicitly forbids.

**Why the marker, not the 0.5 blend, is the predicate.** With `visual_weight=0.7`/`text_weight=0.3`, a doubly-fabricated row lands on exactly `0.5` (`0.35 + 0.15 == 0.5`, no float dust). But a row with a fabricated visual beside an honest sentiment of `0.8` lands on `0.59` — still half-fabricated, still permanently uncandidatable. Keying on `ai_score ≈ 0.5` alone would knowingly leave that population poisoned forever, while keying on the marker cannot produce a false positive: no honest path writes `analysis = 'Error'` (`neutral_sentiment_no_description()` writes `""`), and post-3.2 no degraded result is persisted at all (`tasks.py:760-765`), so the marker is a closed, pre-3.2-only population. The asymmetry decides it — over-repair self-heals through one re-enrichment, under-repair is permanent. The migration still reports the on-blend sub-count separately so the operator sees both populations.

**`combined_score` is deliberately not touched.** It blends `ai_score` (`src/adapters/metrics/scoring.py:98-107`) and therefore carries the fabricated term until the row is re-scored — but `blend_combined_score` reads `float(ai_score or 0.0)`, so both the re-enrichment path (`tasks.py:704`) and the stat-scoring path (`scoring.py:164`) recompute it honestly the moment they next touch the row, which the repair itself guarantees will happen. It is also off story 2.1's path entirely: 2.1's percentiles are price/m²-based, not score-based. Nulling it would drop the rows out of the top-deals digest (`src/core/top_deals_digest.py:31-32` filters `combined_score IS NOT NULL`) for a window, for no gate benefit. Recorded as a bounded, self-healing residual in the feature doc rather than minted as ledger noise.

**The predicate is a recorded widening of the AC, not a reading of it.** The epic's written Given names the marker *"with `ai_score` sitting on the configured blend of 0.5"* (`epics.md:551`). Repairing on the marker alone touches a strictly larger population — a fabricated visual beside an honest 0.9 sentiment sits at 0.62 and is now nulled. The rationale above stands, but it is stated as a deviation in both the migration docstring and the feature doc so the wider blast radius is on record rather than implied.

**The blend constant is pinned at `0.5`, not read from `get_config()`.** Poisoned rows are frozen history — blended with the weights of the day — so a later retune would move a config-derived constant off every poisoned row's value and report `on_blend = 0` with no signal, while making a test that seeds `ai_score = BLEND` from the same source pass for any weights. Pinning also keeps `alembic/versions/` free of `src/` imports: alembic imports every version script to build its revision map, and `alembic history` / `heads` / `branches` do **not** run `env.py` first, so an `infra.config` import there fails outright whenever `src/` is not already on `PYTHONPATH` (verified: `ModuleNotFoundError: No module named 'infra'`), and a bad `IMOVEIS_*` override would abort `upgrade head` before any migration in the chain ran.

**Correction to the intent contract's `migrate-primary.sh` claim** (recorded here because `<intent-contract>` is read-only): the script does *not* refuse every linked worktree. Its guard (`scripts/agent/migrate-primary.sh:51-57`) fires only when a `.env.local` exists **and** names a non-primary `COMPOSE_PROJECT_NAME`; a worktree with no `.env.local` falls through to the primary defaults. The operator step is therefore "run it from the primary checkout deliberately", not "the script will stop you". Ledgered.

**`migrate-primary.sh` is not the only path to `upgrade head`.** `scripts/start.sh:63` and `scripts/agent/run-services.sh:42` run `alembic upgrade head` in the `api` container against the primary project with no lock and no heartbeat probe — that is DW-32, open/high, scheduled in this same Wave 0, and this story is what turns it from a no-op into a data mutation. `start.sh` also prints migration output only on failure, so an incidental apply swallows the `N`/`M` line. Not fixable here (DW-32 owns it, and hard-failing `upgrade()` outside the lock would break `start.sh` for everyone); mitigated with a read-only recovery query in the feature doc and a note in the migration docstring.

**`downgrade()` is a deliberate no-op.** The pre-image is not faithfully recoverable: doubly-fabricated rows sat on exactly the blend constant, but half-fabricated rows sat on an arbitrary value derived from the honest half. Restoring the constant to all of them would *invent* data — the exact failure this story repairs. Downgrading therefore leaves the rows as honest nulls, which the candidate path already handles; the migration logs that fact rather than failing silently.

**Attempt ledger.** Retirement is Redis-side (`<prefix>:attempts`, `is_quarantined` at `src/core/backfill_runner.py:1346-1347`, `max_attempts` 3, 30-day TTL) and is *not* cleared on success. A pre-3.2 poisoned row left the candidate set after its one successful-looking attempt, so it should sit at `attempts == 1` and needs nothing. This is not guaranteed, so the operator checklist includes reading `--status` after the repair and only then considering `--reset-quarantine`; the migration must not touch Redis.

**Predicate shape** (mirrors the coverage-query guard):

```sql
UPDATE metrics_scoring SET ai_score = NULL
 WHERE ai_score IS NOT NULL
   AND CASE WHEN json_typeof(meta) = 'object' THEN
         CASE WHEN json_typeof(meta -> 'visual')    = 'object'
              THEN meta -> 'visual'    ->> 'analysis' = 'Error' ELSE false END
      OR CASE WHEN json_typeof(meta -> 'sentiment') = 'object'
              THEN meta -> 'sentiment' ->> 'analysis' = 'Error' ELSE false END
       ELSE false END
```

## Verification

**Commands:**
- `bash scripts/agent/validate.sh backend` -- expected: lint + unit + integration + contract green; the new integration suite passes; `alembic upgrade head` applies the migration to the ephemeral test DB without error.
- `bash scripts/agent/validate.sh all` -- expected: full gate green before the branch is handed back to the orchestrator.
- `git grep -nE "[\"']Error[\"']" src/adapters src/core src/api` -- expected: only the five pre-existing `src/adapters/ai/client.py` hits (the fallback writers plus 3.2's explanatory comment); no new occurrence, i.e. the forensic string never enters production code. Scoped to those three trees on purpose: the new integration test legitimately contains the literal because it seeds poisoned rows.
- `(unset PYTHONPATH; python3 -m alembic history)` -- expected: succeeds and lists `b65411932ef9 -> f3a7c81d5e42 (head)`; proves no version script imports from `src/`.

**Manual checks (if no CLI):**
- The migration file is the only place the predicate string appears outside the test that imports it.
- `docs/features/v0.13-s2.7-corpus-repair-fabricated-scores.md` carries every `_template.md` section and records the delivery-mechanism rationale.

## Auto Run Result

**Status:** `awaiting-operator` — every part an agent can do is implemented, reviewed, patched, committed and verified. What remains is outside the repo and outside this session's authority: the repair must be applied to the **primary `realestate` corpus**, which is an explicit operator step (`scripts/agent/migrate-primary.sh`, from the primary checkout, guarded against a live backfill). See frontmatter `operator_actions`. Merge-back belongs to the bmad-loop orchestrator.

**Change:** a one-off, data-only Alembic migration (`f3a7c81d5e42`) that nulls `metrics_scoring.ai_score` on every row carrying the pre-3.2 fabrication marker (`meta->'visual'->>'analysis' = 'Error'` or the sentiment twin), so `mode_is_missing_ai` — literally `not score` — re-admits them to the enrichment candidate set and the backfill re-enriches them on its next census. No schema change, no `src/` change, no new config.

**Files:**

- `alembic/versions/f3a7c81d5e42_repair_fabricated_ai_scores.py` — the one-off repair artifact: `FABRICATION_PREDICATE_SQL` (total, `json`-safe, nested `json_typeof` scalar guards), `apply_repair()` as a single CTE statement returning `{"repaired", "on_blend"}` and logging both on the `alembic` channel, `upgrade()`, and a logged no-op `downgrade()`.
- `src/tests/integration/test_corpus_repair_fabricated_scores.py` — 5 tests: the 15-row include/exclude matrix (incl. every JSON-scalar shape), count honesty, empty-corpus, the pinned-blend lock, and the `mode_is_missing_ai` `False → True` characterization lock.
- `docs/features/v0.13-s2.7-corpus-repair-fabricated-scores.md` — delivery-mechanism decision table, the AC-widening deviation, the operator apply/verify procedure with a read-only recovery query, the DW-32 caveat, and the residuals.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `2-7` → `awaiting-operator`, plus a DO-NOT-START gate comment above `2-1`.
- `_bmad-output/implementation-artifacts/deferred-work.md` — 3 new entries.

**Review:** one pass, two reviewers in parallel. 0 intent gaps, 0 spec loopbacks, 13 patches applied (2 high, 6 medium, 5 low), 3 findings deferred to the ledger, 7 rejected. Full breakdown in the Review Triage Log.

**Verification:** `bash scripts/agent/validate.sh backend` → **exit 0, VALIDATION PASSED** (pre-commit OK, eslint OK, 2125 unit passed / 1 skipped, 119 integration passed — including all 5 new tests, 51 contract passed). `alembic upgrade head` applied the migration to the ephemeral test DB cleanly. The `alembic check` line is the pre-existing informational PostGIS warning; nothing about `metrics_scoring` appears in it. `python3 -m alembic history` with `PYTHONPATH` unset now succeeds (it did not before the patch). `git grep -nE "[\"']Error[\"']" src/adapters src/core src/api` returns only the 5 pre-existing `client.py` hits — the forensic string never entered production code.

**Residual risks:**

1. **The repair is not applied.** Everything here is inert until the operator runs the migration against the primary corpus. `combined_score` is untouched by design and heals on the row's next scoring pass.
2. **The `2.1←2.7` gate is documentary, not machine-enforced.** `next_actionable()` skips an `awaiting-operator` story and offers `2-1`. Mitigated with a DO-NOT-START comment and an `operator_actions` item; it is not a hard stop.
3. **DW-32 can apply this migration outside the guarded path.** `scripts/start.sh` / `run-services.sh` run `alembic upgrade head` against the primary with no lock and discard the output on success. Not corrupting for this migration (poisoned rows are outside any running pass's candidate snapshot), but it loses the outcome evidence — hence the read-only recovery query.
4. **The mutating SQL was rewritten during the review pass** (separate count + `UPDATE` → one CTE statement) and has not been seen by an independent reviewer since. That, plus the breadth of the review-driven changes, is why `followup_review_recommended` is `true`.
