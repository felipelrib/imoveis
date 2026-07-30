# Tighten fuzzy dedup matching to prevent merging distinct units in the same building

> Feature branch: `feat/tighten-fuzzy-dedup-matching` · Linear: `BIN-146` · Status: implemented

## Problem

`_find_fuzzy_match` (`src/core/dedupe.py`) matched candidates against nearby properties using only geo radius (50m), area tolerance (±2m², `configs/app_config.yaml` `dedup.area_tolerance_m2`), and title similarity (Jaro-Winkler ≥ 0.65) — it ignored `bedrooms`/`bathrooms`/`parking`, already available on `PropertyCandidate` and on the `Property` model.

Brazilian towers commonly repeat an identical floor plan on multiple floors, with platform-templated titles (e.g. "Apartamento 2 quartos para alugar, Savassi"). Two genuinely distinct units — different floors, same floor plan, same building — could clear all three existing thresholds and get fuzzy-merged into a single `Property` record. That corrupts price history (each unit's independent price changes interleave as if they were one unit's timeline) and hides one of the two units entirely from the dashboard.

## Approach

- Added a `_room_count_close(candidate_value, row_value)` gate: permissive when either side has no data (older rows, or a scraper that hasn't extracted the field), but a **required equality** check when both sides report a value — mirroring the existing area-tolerance pattern (`not (both present) or equal`) rather than a full weighted-score model, so the fix stays minimal and consistent with the surrounding code style.
- `_find_fuzzy_match`'s SQL now selects `bedrooms`, `bathrooms`, `parking` alongside the existing `id`, `title`, `area_m2`, and the match loop requires `rooms_match` (all three room-count gates) in addition to the existing `area_close` and title-similarity checks before accepting a fuzzy match.
- Used `getattr(row, "bedrooms", None)` (etc.) rather than direct attribute access defensively, since raw SQL `Row` results always carry the new columns in production, but this keeps the function robust for any caller passing a partial row-like object.
- Testing discipline (brownfield dedupe invariant, per project convention): added a **characterization test** (`test_characterization_fuzzy_match_ignores_room_counts_pre_bin146`, in `TestFindFuzzyMatch`) as a separate commit *before* the code change, locking today's (buggy) behaviour — a 2-bedroom candidate matching a 3-bedroom/2-bathroom/1-parking existing property purely on geo+area+title. The following commit implements the gate, flips that test's assertion to the new (non-matching) behaviour, and adds a new `TestFuzzyMatchRoomCounts` class covering: differing bedrooms/bathrooms/parking each independently blocking a match, the legitimate all-criteria-match case still matching, and missing room data on both sides still falling back to the permissive area-tolerance-style behaviour.

## Changes

Files touched:

```
src/core/dedupe.py                          | _find_fuzzy_match: added bedrooms/bathrooms/parking to SELECT and as a required-match gate via new _room_count_close helper
src/tests/unit/test_dedupe_orchestration.py | NEW characterization test (locks pre-fix behaviour) + TestFuzzyMatchRoomCounts (5 regression tests) + updated test_match_by_title_and_area row fixture compatibility
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
```

Targeted:

```bash
PYTHONPATH=src .venv/bin/python -m pytest src/tests/unit/test_dedupe_orchestration.py -v -k "FuzzyMatch or characterization"
```

To confirm the regression tests actually catch the bug, check out the commit before the fix (`test: characterize current fuzzy-match ignoring room counts (BIN-146)`) and re-run — `TestFuzzyMatchRoomCounts` doesn't exist yet at that point, but the characterization test's assertion (`result == "x"`) is what the un-fixed code produces; after the fix commit, the same scenario returns `None`.

## Notes / Follow-ups

- Tracked as part of the BIN-128 tech-debt remediation epic (v0.10 milestone).
- **BUG (Medium)**: `_update_fuzzy_match` (`src/core/dedupe.py`) unconditionally overwrites `image_urls`/`props_json` on every scrape cycle with no unchanged-check, unlike the exact-match path's `_is_unchanged` guard. If a fuzzy match is ever wrong (e.g. a floor plan repeated across buildings with no room-count data to disambiguate), this silently discards the other unit's photos each cycle with no error signal. Out of scope for this ticket per its acceptance criteria (only "Consider gating..." in the problem description, not a required criterion) — fix hint: mirror `_is_unchanged`'s blank-guard pattern (`_description_effectively_unchanged`) for `image_urls`/`props_json` before overwriting in `_update_fuzzy_match`.
- The room-count gate is permissive when either side lacks bedroom/bathroom/parking data, so a scraper that never extracts these fields would not benefit from the new protection for its listings. All 3 current scrapers (QuintoAndar, OLX, ZapImóveis) populate these fields from listing pages, so this is not expected to be a practical gap today.
