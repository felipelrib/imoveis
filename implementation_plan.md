# BIN-10: Watchlist Price-Drop Alerts

## Overview

Add a watchlist feature that lets users track properties and receive notifications when prices drop. This is the core payoff of the price-history tracking shipped in v0.1.

## Scope (this iteration)

1. **Watchlist model + migration** — DB table to track watched properties
2. **Notifier module** — pluggable alert interface (log channel + optional webhook)
3. **Price-drop detection** — fire alert when a watched property's price decreases past a threshold
4. **API endpoints** — CRUD for the watchlist
5. **Frontend toggle** — star/notify button on PropertyCard and PropertyModal

## Implementation Steps

### Step 1: Watchlist model + migration

**File:** `src/adapters/db/models.py`

Add `Watchlist` model:
```python
class Watchlist(Base):
    __tablename__ = "watchlist"
    id = Column(UUID, primary_key=True, server_default=...)
    property_id = Column(UUID, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    min_drop_pct = Column(Float, default=5.0)  # alert when price drops ≥ 5%
    last_notified_price = Column(Float)  # suppress repeated alerts
    created_at = Column(DateTime, server_default=now())
```

**Migration:** Alembic revision to create `watchlist` table with upgrade + downgrade.

### Step 2: Notifier module

**New directory:** `src/adapters/notify/`

- `__init__.py` — exports `get_notifier()`
- `base.py` — abstract `Notifier` class with `send(property_id, old_price, new_price, platform, listing_type)` 
- `log_notifier.py` — `LogNotifier` — logs the alert (always available)
- `redis_notifier.py` — `RedisNotifier` — pushes alert to Redis list `alerts:price_drops` for frontend consumption

Config reads from `app_config.yaml`:
```yaml
alerts:
  enabled: true
  min_drop_pct: 5.0
  channels:
    - type: log
    - type: redis  # for frontend polling
```

### Step 3: Price-drop detection in dedupe.py

**File:** `src/core/dedupe.py`

In `_record_price_change()`, after closing an open interval (price changed):
1. Query `watchlist` for properties matching `property_id`
2. For each watcher, check if `old_price - new_price >= old_price * (min_drop_pct / 100)`
3. If yes and `last_notified_price != new_price`, fire the notifier and update `last_notified_price`

This keeps detection inline with the write transaction — no separate consumer needed initially.

### Step 4: API endpoints

**New file:** `src/api/watchlist.py`

| Method | Path | Description |
|--------|------|-------------|
| `GET /watchlist` | List all watched property IDs |
| `POST /watchlist` | Add property to watchlist (body: `{property_id, min_drop_pct?}`) |
| `DELETE /watchlist/{property_id}` | Remove property from watchlist |
| `GET /watchlist/check/{property_id}` | Check if a specific property is watched |

**Wire in:** `src/api/main.py` — `app.include_router(watchlist_router)`

### Step 5: Frontend watchlist toggle

**Files:** `frontend/src/pages/Properties.jsx`, `frontend/src/components/PropertyModal.jsx`, `frontend/src/api.js`

- `api.js`: `fetchWatchlist()`, `addToWatchlist(propertyId)`, `removeFromWatchlist(propertyId)`, `checkWatchlist(propertyId)`
- PropertyCard: small star/🔔 icon that toggles watchlist status
- PropertyModal: watchlist toggle button in the header area
- Load watchlist set on page mount for bulk status check

### Step 6: Config additions

**File:** `configs/app_config.yaml`

Add `alerts` block under the existing config structure.

## Files to Modify

| File | Change |
|------|--------|
| `src/adapters/db/models.py` | Add `Watchlist` model |
| `alembic/versions/` | New migration for watchlist table |
| `src/adapters/notify/` (new) | Notifier module (base + log + redis) |
| `src/core/dedupe.py` | Price-drop detection in `_record_price_change` |
| `src/api/watchlist.py` (new) | CRUD API endpoints |
| `src/api/main.py` | Register watchlist router |
| `configs/app_config.yaml` | Add alerts config block |
| `src/infra/config.py` | Parse alerts config |
| `frontend/src/api.js` | Watchlist API functions |
| `frontend/src/pages/Properties.jsx` | Watchlist toggle on cards |
| `frontend/src/components/PropertyModal.jsx` | Watchlist toggle in modal |
| `frontend/src/index.css` | Star/toggle styles |

## Testing Strategy

- **Unit tests:** `test_watchlist.py` — notifier logic, price-drop threshold detection
- **Integration tests:** `test_watchlist_e2e.py` — full flow: add to watchlist → ingest price drop → verify alert
- **Contract tests:** API response shapes for watchlist endpoints
- **Frontend:** Manual verification of toggle behavior
- **validate.sh backend** must pass

## Risks

- Alert suppression: `last_notified_price` prevents duplicate alerts for the same drop
- Single-user for now: `owner` column is nullable, ready for future auth
- The notifier module is pluggable — can add Telegram/email later without changing detection logic