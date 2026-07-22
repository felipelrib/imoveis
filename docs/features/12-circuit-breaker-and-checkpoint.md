# circuit-breaker-and-checkpoint — Fault-tolerant scraping with distributed circuit breaker and per-platform resumption

> Feature branch: `feat/circuit-breaker` · Linear: `BIN-XX` · Status: implemented

## Problem

Two reliability gaps in the scraper layer:

1. **Cascade failures**: A platform returning errors (rate-limit 429, timeouts, 5xx) would
   cause Celery to retry in a tight loop, hammering the target site and burning retry budget.
2. **No resumption**: If a scrape task failed mid-run, the next attempt started from page 1,
   re-processing all already-seen listings and wasting bandwidth.

## Approach

### Circuit Breaker (two implementations)

- **`CircuitBreaker`** (`adapters/scrapers/circuit_breaker.py`) — In-memory, per-process.
  Fast with zero external dependencies. Resets state on any success.
- **`RedisCircuitBreaker`** (`adapters/scrapers/redis_circuit_breaker.py`) — Distributed
  state stored in Redis under `circuit_breaker:<platform>`. Survives process restarts
  and is shared across multiple Celery worker processes on the same task queue.
  Uses `setex` with `cooldown_seconds * 2` TTL to prevent stale open circuits if Redis
  restarts while a platform is broken.

Both implement the same three-method interface:
- `is_open() → bool` — checks current state; auto-resets if cooldown has expired.
- `record_failure()` — increments counter; opens circuit when `failure_threshold` reached.
- `record_success()` — resets all state unconditionally.

The `scrape_listings` Celery task catches `CircuitBreakerOpenError` and breaks the
inner loop, letting Celery's own exponential backoff handle the retry cadence.

### Checkpoint Store

- **`CheckpointStore`** (`adapters/scrapers/checkpoint_store.py`) persists a per-platform
  `dict` into the `platform_checkpoints` DB table (JSON column).
- Checkpoints are saved after **every successfully processed listing**, so a task failure
  mid-run resumes from the last-saved page/cursor rather than from scratch.
- Uses SQLAlchemy ORM with explicit `rollback()` + `raise` on save errors to ensure
  checkpoint integrity isn't silently lost.

## Changes

Files touched:

```
 src/adapters/scrapers/circuit_breaker.py         | NEW — in-memory circuit breaker
 src/adapters/scrapers/redis_circuit_breaker.py   | NEW — Redis-backed distributed circuit breaker
 src/adapters/scrapers/checkpoint_store.py        | NEW — per-platform DB-backed checkpoint persistence
 src/adapters/db/models.py                        | NEW model PlatformCheckpoint (platform_checkpoints table)
 src/adapters/queue/tasks.py                      | Integrated CheckpointStore + CircuitBreakerOpenError handling
 src/core/exceptions.py                           | NEW — CircuitBreakerOpenError exception class
```

## New Dependencies

None.

## How to Test

1. Trigger a scrape and interrupt the process mid-run:
   ```bash
   curl -X POST http://localhost:8000/scrape -d '{"platform":"olx"}'
   # kill -9 <worker_pid> after a few listings are processed
   ```
2. Re-trigger the scrape — it should resume from the last checkpoint (check logs for
   `checkpoint_loaded` with non-empty data).
3. Force 5 consecutive scraper errors to verify the circuit opens and
   `CircuitBreakerOpenError` is logged, stopping further retries.

## Notes / Follow-ups

- ~~**BUG (Race Condition — `RedisCircuitBreaker`)**~~ — **FIXED**: Replaced `record_failure` with an atomic Lua script.
- ~~**`CircuitBreaker` (in-memory) is not useful for Celery**~~ — **FIXED**: Added prominent `IN-MEMORY CIRCUIT BREAKER — FOR TESTING ONLY` docstring.
- ~~**Checkpoint `data` column has no schema validation**~~ — **FIXED**: Implemented `OLXCheckpoint` and `QuintoAndarCheckpoint` Pydantic models in `checkpoint_store.py` for schema validation.
- ~~**`CheckpointStore.set()` rolls back on error but re-raises**~~ — **FIXED**: Added a `try/except` block to cleanly log checkpoint save failures in the error handler in `tasks.py`.
