# Eliminate f-string-built SQL fragments — enum/allow-listed column selection + CI lint gate

> Feature branch: `feat/eliminate-fstring-sql` · Linear: `BIN-135` · Status: implemented

## Problem

`src/api/properties.py`, `src/adapters/metrics/scoring.py`, `src/core/top_deals_digest.py`, `src/core/property_projection.py`, and `src/api/saved_searches.py` all built their final SQL text by interpolating column names/fragments via Python f-strings into `text(f"""...""")`, contradicting `CLAUDE.md`'s "NEVER f-string SQL — parameterize" rule.

This was **not currently exploitable** — every interpolated fragment came from an internal allow-list (e.g. `sort_col_map`, `_SCORE_COLUMNS`) or a hardcoded column-name literal; all user-supplied *values* were already bound via `:param` placeholders. But the pattern itself was fragile and unenforced: no lint rule caught it. A future contributor extending one of these f-string-built WHERE/ORDER/SELECT clauses with an insufficiently-validated value (e.g. skipping the pydantic `pattern=` constraint used for `sort_by`) would reintroduce real SQL injection with nothing to catch it before review.

## Approach

- Audited every call site (`git grep -nP '(\btext\(\s*f[\x27"]|\bf[\x27"][^\x27"]*\b(SELECT|INSERT|UPDATE|DELETE|WHERE|FROM|ORDER BY)\b)' -- 'src/*.py'`) — found 12 production sites (the ticket's cited line numbers had shifted after BIN-134 moved `property_projection.py` into `core/`, plus two additional sites the ticket didn't enumerate: `properties.py`'s price-history query and `saved_searches.py`'s dynamic UPDATE).
- Replaced every `text(f"""...""")` / f-string-embedded fragment with **plain string concatenation** (`+`) of the same already-safe pieces (allow-listed column expressions, hardcoded literals, or fixed module constants) plus `:bind` params for values. This keeps 100% of existing behavior — no query semantics changed — while removing every f-string/`.format()`/`%`-style interpolation from SQL text assembly project-wide.
- Left the existing per-fragment builders alone (`_append_neighborhood_filters`, `_append_city_filters`, `_append_bbox_filter`, `sort_col_map`, `_SCORE_COLUMNS`) — the ticket explicitly notes these already parameterize user values correctly via bind params; only the *outer* f-string assembly of the final query text was in scope.
- Added a grep-based CI/pre-commit gate (`forbid-fstring-sql` in `.pre-commit-config.yaml`, mirrored in `scripts/agent/validate.sh`'s `run_lint`) that fails on any new `text(f"...")` or f-string SQL-keyword fragment under `src/` (excluding `src/tests/`, where assertions on generated SQL text are expected to contain SQL keywords). Verified it fires on an injected violation and stays clean on the current tree.
- Testing discipline: `compute_neighborhood_stats`/`select_top_deals`/`list_properties`/`export_properties`/`get_property`/`get_price_history`/saved-search-update already had real integration/unit coverage exercising the rewritten SQL against Postgres — that coverage passed unchanged, serving as the characterization lock. Two functions (`recalculate_all_combined_scores`, `get_neighborhood_stats_cached`) had **zero** DB-level coverage before this change despite having the most complex multi-splice rewrites; added `src/tests/integration/test_scoring_sql_assembly.py` to lock their behavior against real PostGIS + Redis. Added `src/tests/unit/test_no_fstring_sql_lint.py` to lock the new lint gate itself (clean-tree assertion + synthetic-violation detection + config/validate.sh wiring checks).

## Changes

Files touched:

```
src/api/properties.py                         | 7 call sites: text(f"""...""") -> text("..." + where/order/column + "...")
src/adapters/metrics/scoring.py                | 3 call sites (+ where_clause builder): same f-string -> concatenation rewrite
src/core/top_deals_digest.py                   | select_top_deals() query rewritten as concatenation
src/core/property_projection.py                | LIST_SELECT_COLUMNS constant: f-string -> concatenation with LISTINGS_JSON_AGG
src/api/saved_searches.py                      | update_search() UPDATE statement: f-string -> concatenation
.pre-commit-config.yaml                        | NEW hook forbid-fstring-sql — greps src/ (excl. tests/) for text(f"...") / f-string SQL-keyword fragments
scripts/agent/validate.sh                      | run_lint: mirrors the same grep for fast local feedback + CI parity
src/tests/unit/test_no_fstring_sql_lint.py     | NEW — locks the lint pattern: clean tree, catches injected violations, ignores test assertions, checks both wiring points stay in sync
src/tests/integration/test_scoring_sql_assembly.py | NEW — characterization lock for recalculate_all_combined_scores() and get_neighborhood_stats_cached() (previously untested against real Postgres/Redis)
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
```

Targeted:

```bash
PYTHONPATH=src pytest src/tests/unit/test_no_fstring_sql_lint.py src/tests/integration/test_scoring_sql_assembly.py -v
```

Confirm the gate itself fires on a violation:

```bash
echo 'sql = text(f"""SELECT * FROM x""")' > src/api/_tmp_probe.py
pre-commit run forbid-fstring-sql --all-files   # should report Failed, naming _tmp_probe.py
rm src/api/_tmp_probe.py
```

## Notes / Follow-ups

- Tracked as part of the BIN-128 tech-debt remediation epic (v0.10 milestone).
- Epic parent: BIN-128. Depended on BIN-134 (core/api layering fix) landing first since both touch `top_deals_digest.py` — confirmed merged before starting this ticket.
- The new lint pattern is duplicated (pre-commit hook + `validate.sh`) rather than factored into a shared script; `test_no_fstring_sql_lint.py` asserts both copies exist so they can't silently drift apart. A future cleanup could extract both into one `scripts/agent/lint-sql-fstrings.sh` if a third call site appears.
