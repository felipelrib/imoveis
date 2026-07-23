# Price-Drop Alerts — Watchlist-driven notifications for tracked property price decreases

> Feature branch: `feat/price-alerts` · Linear: `BIN-XX` · Status: implemented

## Problem

Users want to be notified when a watched property drops in price by a significant percentage. This requires tracking price history per-listing, comparing old vs. new prices during each scrape, and dispatching notifications through configurable channels.

## Approach

- **Watchlist model**: Users add properties to a `watchlist` table with a configurable `min_drop_pct` (default 5%) and optional `last_notified_price` to prevent duplicate alerts.
- **Detection during dedup**: `_check_watchlist_alerts()` is called from `_record_price_change()` whenever a price change is detected. This runs inline within the scrape transaction.
- **Pluggable notifiers**: `adapters/notify/` implements a `Notifier` ABC with:
  - `LogNotifier` — Always active, writes structured log entries.
  - `RedisNotifier` — Pushes alert payloads to a Redis list (`alerts:price_drops`) for frontend polling, with 7-day TTL and 200-item cap.
- **Configuration-driven**: `alerts.channels` in `app_config.yaml` controls which notifiers are active.

## Changes

Files touched:

```
 src/adapters/notify/__init__.py       | Notifier factory with caching
 src/adapters/notify/base.py           | Notifier ABC and PriceDropAlert dataclass
 src/adapters/notify/log_notifier.py   | Structured log-based notifier
 src/adapters/notify/redis_notifier.py | Redis list-based notifier for frontend
 src/core/dedupe.py                    | _check_watchlist_alerts integration
 src/adapters/db/models.py             | Watchlist ORM model
 src/api/watchlist.py                  | CRUD API for watchlist management
 configs/app_config.yaml               | alerts section configuration
```

## New Dependencies

None.

## How to Test

1. Add a property to the watchlist:
   ```bash
   curl -X POST http://localhost:8000/watchlist \
     -H 'Content-Type: application/json' \
     -d '{"property_id": "UUID_HERE", "min_drop_pct": 5.0}'
   ```
2. Simulate a price drop by manually updating the property price in the database.
3. Re-run the scraper — the alert should appear in logs and Redis:
   ```bash
   redis-cli LRANGE alerts:price_drops 0 -1
   ```
