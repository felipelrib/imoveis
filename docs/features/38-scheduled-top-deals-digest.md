# Scheduled top-deals digest — optional weekly digest of top new deals

> Feature branch: `feat/bin-52-top-deals-digest` · Linear: `BIN-52` · Status: implemented

## Problem

House-hunters miss good listings unless they open the app daily. Price-drop `send_daily_digest` only batches watchlist price-drop emails — it does not surface newly scored high-deal properties. FR-21 requires an optional scheduled “top new deals” digest delivered through the same notifier registry as alerts (AD-9), using the AD-12 property projection and the Epic 2 principal (AD-11).

## Approach

- Gate delivery with `alerts.top_deals.enabled` (unsubscribe = `enabled: false`); subscriber is `auth.principal_id`.
- Selection rule: `first_seen` within `lookback_hours`, `combined_score IS NOT NULL` and `>= min_combined_score`, order by score then recency, limit N; serialize via `map_property_list_item`.
- New Celery task `tasks.send_top_deals_digest` + beat entry — distinct from `digest_mode` / `send_daily_digest` / `alerts:email_digest`.
- Extend `Notifier` with `send_digest()` so Log / Redis / Email share one channel registry; email is optional and never queues into the price-drop digest list.
- Share `LIST_SELECT_COLUMNS` from `property_projection` so list / export / digest stay on one SQL shape.

## Changes

Files touched:

```
 src/infra/config.py                          | ADD TopDealsDigestConfig under AlertsConfig
 configs/app_config.yaml                      | ADD alerts.top_deals block (default enabled: false)
 src/adapters/notify/base.py                  | ADD TopDealsDigest + Notifier.send_digest
 src/adapters/notify/log_notifier.py          | ADD send_digest structured log
 src/adapters/notify/redis_notifier.py        | ADD send_digest → alerts:top_deals_digest
 src/adapters/notify/email_notifier.py        | ADD send_digest SMTP (no price-drop queue)
 src/api/property_projection.py               | ADD LIST_SELECT_COLUMNS / LISTINGS_JSON_AGG
 src/api/properties.py                        | IMPORT shared list SQL constants
 src/core/top_deals_digest.py                 | NEW — selection helper + TOP_DEALS_RULE
 src/adapters/queue/tasks.py                  | ADD send_top_deals_digest task
 src/adapters/queue/celery_app.py             | ADD beat entry when top_deals.enabled
 src/tests/unit/test_top_deals_digest.py      | NEW — selection, gate, empty, no SMTP
 src/tests/unit/test_schedule.py              | ADD top_deals beat coverage
 docs/features/38-scheduled-top-deals-digest.md | NEW — this doc
 _bmad-output/.../sprint-status.yaml          | 4-3 → done; epic-4 → done (on merge)
```

## New Dependencies

None.

## How to Test

1. Unit (no SMTP / no live Redis required for selection tests):
   ```bash
   bash scripts/agent/validate.sh fast
   ```
2. Enable locally in `configs/app_config.yaml` (or override):
   ```yaml
   alerts:
     top_deals:
       enabled: true
       limit: 10
       lookback_hours: 168
   ```
3. Restart Celery beat/worker; confirm beat has `send-top-deals-digest`, or invoke:
   ```bash
   celery -A adapters.queue.tasks call tasks.send_top_deals_digest
   ```
4. With `enabled: false`, the task returns `{"status": "skipped"}` and does not notify.

## Notes / Follow-ups

- Multi-tenant `DigestSubscription` table (architecture ER) deferred; config + `principal_id` is enough for single-tenant AD-11.
- No UI subscribe/unsubscribe or in-app digest panel in this story.
- Distinct from price-drop digest: do not reuse `digest_mode` or `alerts:email_digest`.
- Epic 4 closing story (BIN-22 / FR-21).
