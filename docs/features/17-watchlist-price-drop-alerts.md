# watchlist-price-drop-alerts — Configurable per-property price-drop watchlist with pluggable notification channels

> Feature branch: `feat/watchlist` · Linear: `BIN-XX` · Status: implemented

## Problem

Users who find a property priced above their budget need a way to be notified when the
price drops enough to become interesting, without having to manually revisit the site.
The price-history table already tracked price changes, but no alert mechanism existed to
act on those changes.

## Approach

- **`watchlist` table** stores `(property_id, min_drop_pct, last_notified_price)`.
  `min_drop_pct` is user-configurable (default 5%, validated 0.1–100).
  `last_notified_price` records the price at which the last alert was sent, preventing
  repeated alerts for the same price point.

- **`/watchlist` REST API** (`src/api/watchlist.py`):
  - `GET /watchlist` — list all watched properties with created_at ordering.
  - `POST /watchlist` — add a property (checks property exists, prevents duplicates, returns 409 on conflict).
  - `DELETE /watchlist/{property_id}` — remove by `property_id` (not internal watchlist ID).
  - `GET /watchlist/check/{property_id}` — fast boolean check used by `PropertyModal`.

- **Pluggable notifier system** (`src/adapters/notify/`):
  - `Notifier` ABC with a single `send(alert: PriceDropAlert) → None` method.
  - `LogNotifier` — always-on fallback; writes a structured log line.
  - `RedisNotifier` — pushes a JSON payload to `alerts:price_drops` Redis list
    (capped at 200 entries, 7-day TTL) for frontend polling.
  - `get_notifiers()` reads `cfg.alerts.channels` and constructs the list once,
    cached in a module-level variable. `reset_notifiers()` clears the cache for tests.
  - **Evaluation Loop (`adapters/queue/tasks.py`)**: A periodic Celery beat task (`evaluate_watchlist_alerts`) 
    runs every 5 minutes. It compares the current `property_listings.price` against `watchlist.last_notified_price`
    (or the original price if never notified). If the drop exceeds the configured `min_drop_pct`,
    it generates an alert and updates the `last_notified_price`.
- **TOCTOU Protection**: Concurrent additions to the watchlist use an atomic `INSERT ... ON CONFLICT DO NOTHING`
  with a unique constraint on `property_id`.
- **API and UI Improvements**: Watchlist endpoints accept and return a `user_id` (in preparation for
  auth), and the frontend `PropertyModal` provides an input field to configure the `min_drop_pct`.

- **`PriceDropAlert` dataclass** is frozen and immutable — safe to pass between threads.

- **Frontend**: `PropertyModal` shows a 🔔/☆ watchlist toggle button fetched via
  `checkWatchlist()` on modal open.

## Changes

Files touched:

```
 src/api/watchlist.py                     | NEW — CRUD REST API (list, add, remove, check)
 src/adapters/db/models.py                | NEW Watchlist ORM model (watchlist table)
 src/adapters/notify/__init__.py          | NEW — notifier registry; get_notifiers(), reset_notifiers()
 src/adapters/notify/base.py              | NEW — Notifier ABC + PriceDropAlert frozen dataclass
 src/adapters/notify/log_notifier.py     | NEW — LogNotifier (always-on structured log)
 src/adapters/notify/redis_notifier.py   | NEW — RedisNotifier (pushes to alerts:price_drops list)
 src/api/main.py                          | Registered watchlist router
 frontend/src/api.js                      | fetchWatchlist, addToWatchlist, removeFromWatchlist, checkWatchlist
 frontend/src/components/PropertyModal.jsx | Watchlist toggle button (🔔/☆)
```

## New Dependencies

None.

## How to Test

1. Add a property to the watchlist:
   ```bash
   curl -X POST http://localhost:8000/watchlist \
     -H 'Content-Type: application/json' \
     -d '{"property_id": "<UUID>", "min_drop_pct": 7.5}'
   ```
2. Verify it appears:
   ```bash
   curl http://localhost:8000/watchlist
   ```
3. Check a specific property:
   ```bash
   curl http://localhost:8000/watchlist/check/<UUID>
   # {"watched": true, "id": "...", "min_drop_pct": 7.5, ...}
   ```
4. Remove it:
   ```bash
   curl -X DELETE http://localhost:8000/watchlist/<UUID>
   ```
5. Frontend: open a property modal → 🔔 button should toggle and persist.

## Notes / Follow-ups

- **`DELETE /watchlist/{property_id}` — parameter semantics**: The path parameter is
  `property_id`, not the watchlist row's own `id`. This is consistent but non-RESTful.
  Document clearly in the OpenAPI schema.
