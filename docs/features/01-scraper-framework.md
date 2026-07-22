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

## Notes / Follow-ups

### Bugs Found

- **BUG (Critical): `await` in sync context — `BaseScraper.__exit__`** (base.py L26-42): The sync `__exit__` tries to schedule an async `close()` but uses `get_event_loop()` which is deprecated and may not find a running loop in Celery workers. This can silently leak HTTP connections (httpx sessions not closed). **Fix**: Either make the scraper an async context manager or call `self.session.close()` synchronously in `__exit__`.

- **BUG (Moderate): OLX `__init__` signature mismatch** (olx.py L46): `OLXScraper.__init__(self, config)` only accepts `config` but `BaseScraper.__init__` expects `(platform_name, config)`. The `super().__init__("olx", config)` call is correct, but `ScraperRegistry.get()` calls `scraper_cls(platform_name, platform_config)` with TWO args, so instantiation will fail with `TypeError: __init__() takes 2 positional arguments but 3 were given`.

- **BUG (Moderate): `scrape_listings` task references `cfg.platforms`** (tasks.py L67): The task does `cfg.platforms.get(platform_name)` but `AppConfig` has no `.platforms` attribute — platforms are under `cfg.scraping.platforms`. This will raise `AttributeError` at runtime. Furthermore, `PlatformConfig` is a frozen Pydantic model, not a dataclass, so `dataclasses.asdict()` (L70) will fail.

- **BUG (Minor): `start()` is sync but declared `async` in QuintoAndar** — `quintoandar.py` has `def start(self)` (sync), while `BaseScraper` also has `async def start()`. The `tasks.py` calls `scraper.start()` without `await`, so the async version would silently return a coroutine object. Currently works only because both scrapers define sync `start()`.

- **BUG (Minor): `fetch_pages` is sync but declared `async` in BaseScraper** — Both OLX and QuintoAndar implement `fetch_pages` as sync generators, but the ABC declares it as `async def`. The `tasks.py` iterates synchronously (`for raw in scraper.fetch_pages(cp)`), which works only because the concrete implementations are sync.

### Tech Debt

- **In-process `CircuitBreaker` is dead code** — `circuit_breaker.py` exists but is never used; both scrapers use `RedisCircuitBreaker`. Should be removed.
- **OLX import not auto-registered** — `tasks.py` imports `quintoandar` but not `olx` for registry registration. OLX scraper will not appear in the registry unless imported elsewhere. The `/scrape` endpoint also only imports `quintoandar`. OLX is effectively unreachable.
- **No proxy support implemented** — Config defines `proxy` section but no scraper uses it.
- **Hardcoded BH region** — Both scrapers are hardcoded to Belo Horizonte. Should be configurable.
- **No `close()` called on httpx sessions** — Both scrapers create `httpx.Client()` in `start()` but never explicitly close them (due to the `__exit__` bug above).
