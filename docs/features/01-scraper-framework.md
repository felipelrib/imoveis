# Scraper Framework — Pluggable platform scraper system with registry, circuit breakers, and checkpointing

> Feature branch: `feat/scraper-framework` · Linear: `BIN-XX` · Status: implemented

## Problem

Ingesting real-estate listings from multiple platforms (OLX, QuintoAndar) requires a consistent interface that handles rate limiting, anti-bot detection, circuit breaking on failures, and checkpoint-based resumption. Without a unified framework, each scraper would duplicate boilerplate for throttling, error handling, and persistence.

## Approach

- **Registry pattern** (`ScraperRegistry`): Scrapers self-register via `@ScraperRegistry.register("name")` decorator at import time; callers use `ScraperRegistry.get(name, config)` to obtain instances.
- **Abstract base** (`BaseScraper`): Defines `fetch_pages(checkpoint)`, `normalize(raw)`, `start()`, and `close()` as the contract. Each scraper is checkpoint-aware and idempotent.
- **QuintoAndar scraper**: Parses `__NEXT_DATA__` JSON from server-rendered pages. Uses a **sliding price window** strategy to bypass QuintoAndar's 12-result pagination cap — recursively splits price ranges when ≥12 results are found.
- **OLX scraper**: Also parses `__NEXT_DATA__`, iterating over predefined rent/sale URL paths with page-based pagination (`?o=N`). Supports configurable `max_pages`.
- **Redis-backed circuit breaker**: Both scrapers use `RedisCircuitBreaker` to track consecutive failures and halt scraping when a platform is returning 5xx/429 errors (threshold: 5 failures, cooldown: 120s).
- **Checkpoint store**: Uses a `platform_checkpoints` DB table to persist scrape state, allowing resumption after crashes.
- **Rate limiting via jitter**: Each scraper sleeps a random interval (configurable `jitter_min`/`jitter_max`) between requests.

## Changes

Files touched:

```
 src/adapters/scrapers/base.py            | Base scraper ABC with sync context manager
 src/adapters/scrapers/registry.py        | ScraperRegistry class-level registry with register/get/available
 src/adapters/scrapers/quintoandar.py     | QuintoAndar scraper — sliding price window approach
 src/adapters/scrapers/olx.py             | OLX Brazil scraper — page-based __NEXT_DATA__ parsing
 src/adapters/scrapers/circuit_breaker.py | In-process circuit breaker (unused — superseded by Redis version)
 src/adapters/scrapers/redis_circuit_breaker.py | Redis-backed circuit breaker for cross-process state
 src/adapters/scrapers/checkpoint_store.py | DB-backed checkpoint persistence per platform
 src/adapters/scrapers/__init__.py        | Package exports
 configs/app_config.yaml                  | Per-platform config (base_url, rate_limit, jitter, extra)
```

## New Dependencies

- `beautifulsoup4` — HTML parsing for `__NEXT_DATA__` extraction
- `httpx` — HTTP client (sync for scrapers, async for AI/image)
- `jellyfish` — Jaro-Winkler similarity for dedup (used downstream)

## How to Test

1. Start the stack: `./scripts/start.sh`
2. Trigger a scrape via the API:
   ```bash
   curl -X POST http://localhost:8000/scrape \
     -H 'Content-Type: application/json' \
     -d '{"platform": "quintoandar", "scrape_type": "rent"}'
   ```
3. Monitor the Celery worker logs for `scrape_completed` events.
4. Run unit tests:
   ```bash
   pytest src/tests/unit/test_olx.py src/tests/unit/test_registry.py -v
   ```
