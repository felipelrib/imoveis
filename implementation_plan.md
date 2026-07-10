# Implementation Plan: Pipeline Resilience (BIN-17)

## Goal

Wire the existing but unused circuit breaker code into both scrapers and add "noop" detection to the deduplication engine so that re-scraping unchanged data skips AI enrichment entirely. This saves GPU time and makes the pipeline robust enough to run unattended.

## Affected Areas

| File | Change |
|------|--------|
| `src/core/dedupe.py` | Add noop detection in exact-platform-match path |
| `src/core/exceptions.py` | Add `CircuitBreakerOpenError` |
| `src/adapters/scrapers/quintoandar.py` | Wire `RedisCircuitBreaker` into `_throttled_request()` |
| `src/adapters/scrapers/olx.py` | Wire `RedisCircuitBreaker` into `_throttled_request()` |
| `src/adapters/queue/tasks.py` | Catch `CircuitBreakerOpenError` for graceful retry |
| `src/tests/unit/test_dedupe.py` | Add noop tests |
| `src/tests/unit/test_cb.py` | Add RedisCircuitBreaker tests |

## Step-by-Step Implementation

### Step 1: Add `CircuitBreakerOpenError` to `src/core/exceptions.py`

Add a new exception class for clean try/except in scrapers and tasks.

### Step 2: Add noop detection to `src/core/dedupe.py`

In `match_or_create_property()`, the exact-platform-match block (Step 1) currently always returns `"updated"`. Add a comparison of key fields (price, title, description, image_urls, listings) against the existing property. If nothing changed, return `DeduMatchResult(action="noop")`.

The fuzzy-match block (Step 2) always represents new data from a different platform and should remain "updated".

### Step 3: Wire `RedisCircuitBreaker` into `quintoandar.py`

- Instantiate `RedisCircuitBreaker(platform="quintoandar")` in `start()`
- In `_throttled_request()`: check `is_open()` before calling — if open, raise `CircuitBreakerOpenError`
- On HTTP 2xx: `record_success()`
- On HTTP 5xx / 429 / connection error: `record_failure()`

### Step 4: Wire `RedisCircuitBreaker` into `olx.py`

Same pattern as quintoandar. Instantiate in `start()`, guard `_throttled_request()`.

### Step 5: Handle `CircuitBreakerOpenError` in `tasks.py`

Catch `CircuitBreakerOpenError` in `scrape_listings()` — log warning and re-raise so Celery retries with backoff.

### Step 6: Write tests

- Noop tests in `test_dedupe.py`: unchanged property → noop, changed price → updated, changed images → updated
- RedisCircuitBreaker tests in `test_cb.py`: threshold opens circuit, cooldown resets, mock Redis
- Scraper CB tests: verify scrapers respect circuit breaker (mock Redis)

### Step 7: Commit and validate

Commit after each step with conventional messages, then run `validate.sh backend`.

## Data / Schema Changes

None. All changes are behavioral.

## Validation Plan

- `pytest src/tests/unit/test_dedupe.py -v` — noop logic
- `pytest src/tests/unit/test_cb.py -v` — circuit breaker logic
- `pytest src/tests/unit/ -v` — all unit tests
- `validate.sh backend` — full gate

## Risks

- **Accidental noop suppression**: Mitigated by comparing exact values (price, images) not fuzzy thresholds.
- **Redis dependency in tests**: Mock `get_redis()` for unit tests; Redis is available in CI.
- **Existing test breakage**: Must verify all existing dedupe/scraper tests pass.
