# type-aware-top-deals-digest — Rank digest by rent/sale/primary combined_score

> Feature branch: `feat/bin-107-type-aware-top-deals-digest` · Linear: `BIN-107` · Status: implemented

## Problem

After BIN-83 dual `combined_score_rent` / `combined_score_sale`, the scheduled top-deals digest still filtered and ranked on primary `combined_score` only. Operators who care about rent or sale deals could not target the matching typed score.

## Approach

- Add `alerts.top_deals.score_target: primary|rent|sale` (default `primary`) to AppConfig / YAML.
- Map the target to the matching `ms.combined_score_*` column for `IS NOT NULL`, `>= min_combined_score`, and `ORDER BY`.
- No COALESCE to primary for typed targets — choosing rent/sale means only properties with that typed score are included.
- Celery `send_top_deals_digest` passes the config through; notifier rule string reflects the active column.

## Changes

Files touched:

```
 src/infra/config.py                        | TopDealsDigestConfig.score_target
 configs/app_config.yaml                    | Document score_target under top_deals
 src/core/top_deals_digest.py               | Column allowlist + typed SELECT/ORDER BY
 src/adapters/queue/tasks.py                | Pass score_target; dynamic rule string
 src/tests/unit/test_top_deals_digest.py    | Ranking selection + task wiring tests
 docs/features/BIN-83-dual-stat-score-by-listing-type.md | Close deferred follow-up note
 docs/features/BIN-107-type-aware-top-deals-digest.md | NEW — this doc
```

## New Dependencies

None.

## How to Test

1. Set `alerts.top_deals.enabled: true` and `score_target: rent` (or `sale`) in `configs/app_config.yaml`.
2. Ensure dual scores are populated (Dashboard → Recalculate All Scores).
3. Trigger `tasks.send_top_deals_digest` (or wait for beat); log/email digest should rank by the typed column.
4. Automated:
   ```bash
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- Default remains `primary` for backward-compatible digests.
- Dual columns must be populated (BIN-83 recalculate) before typed digests return rows.
- Related: BIN-83 dual scores, BIN-52 original digest.
