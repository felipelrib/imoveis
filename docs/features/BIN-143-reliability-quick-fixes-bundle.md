# Reliability Quick-Fixes Bundle — swallowed errors, fail-open semaphore, stale lint suppressions, per-request AI client

> Feature branch: `feat/reliability-quick-fixes-bundle` · Linear: `BIN-143` · Status: implemented

## Problem

Four small, independent Low-severity findings from the 2026-07-29 technical debt audit (epic BIN-128), bundled into one ticket since each was too small to justify its own PR review cycle:

1. **Silently dropped malformed alert JSON.** `send_daily_digest`'s batch loop parsed each queued Redis alert with `except Exception: pass` — a corrupted/malformed entry vanished from the digest with zero trace.
2. **GPU semaphore fails open on Redis errors.** `GPUSemaphore.acquire()` returns `True` on any Redis exception, silently granting the slot. Plausible on purpose (a flaky Redis shouldn't halt AI enrichment), but undocumented as such — a future reader could easily "fix" it into a fail-closed bug.
3. **Stale `# noqa: BLE001` comments.** Nine occurrences referenced `flake8-blind-except`'s `BLE001` rule, but neither `ruff` nor `flake8-blind-except` appear anywhere in `requirements.txt`, `.pre-commit-config.yaml`, or CI — the comments were misleading dead weight (a fresh grep found two more than the seven listed in the ticket, since scrapers moved during BIN-133's shared-base extraction and `zapimoveis.py`/`client.py` had additional untracked occurrences).
4. **Per-request `asyncio.run()` + fresh AI client for semantic search.** `_embed_query_literal` (used by `GET /properties?q=`) constructed a brand-new event loop and a brand-new `create_ai_client()` (with its own aiohttp `ClientSession`/TCP connection) on every single semantic-search request.

## Approach

1. **Alert JSON logging** — `except Exception as exc:` now logs `send_daily_digest_bad_alert_json` at `warning` via `infra.logging.get_logger` (module already had one), including the offending raw item (decoded from Redis bytes, `errors="replace"`) and the exception string. The malformed item is still skipped — behavior for the batch is unchanged, only observability improved.
2. **GPU semaphore fail-open** — judgment call: **kept fail-open, documented as intentional** rather than made configurable. Making it configurable now would overlap with BIN-147 (already-scoped semaphore TTL/timeout hardening) and BIN-159 (broader semaphore reliability follow-ups); this is a single-GPU local-dev pipeline where blocking all AI enrichment on a Redis blip is worse than occasional bounded oversubscription. Added a comment above the `return True` in `acquire()`'s except block explaining the trade-off and pointing at BIN-147 for future hardening.
3. **Stale noqa comments** — dropped the `# noqa: BLE001` marker from all nine occurrences found by a fresh `grep -rn "noqa: BLE001" src/` (two more than the ticket's list: `src/adapters/ai/client.py:305` and `src/adapters/scrapers/zapimoveis.py:432`, plus the ticket's listed `zapimoveis.py:289` broad-except-comment). Where the comment carried a real explanation after the marker (e.g. "— never abort scrape for detail enrich"), the explanation was kept as a plain comment; only the misleading linter-directive prefix was removed. Adding `ruff`/`flake8-blind-except` to the pipeline to make these meaningful again is out of scope for this ticket (bigger scope decision).
4. **Per-request AI client** — replaced the per-request `asyncio.run()` + fresh `create_ai_client()` with a **per-worker-thread cached client** plus the existing thread-local event-loop bridge (`adapters.queue.async_bridge.run_coro`, built for BIN-122's Celery use case). A single process-wide client/session was considered but rejected: aiohttp's `ClientSession` is bound to the event loop that created it, and FastAPI executes sync route handlers across a bounded worker threadpool with one event loop per thread (via `run_coro`) — sharing one session across threads/loops would raise cross-loop errors. The cache is keyed by `threading.get_ident()` in a plain module-level `dict` (not `threading.local()`) specifically so tests can clear every thread's cached client from the main test thread via `_reset_embedding_clients()` — `threading.local()` storage is not reachable across threads, which would have made test isolation impossible. `LocalAIClient.embed()` already calls `self._ensure_session()` internally, so the `async with client:` context manager (which used to open+close a session every call) was dropped entirely; the session persists and is reused across requests on the same worker thread instead of a fresh TCP connection per request.

## Changes

Files touched:

```
src/adapters/queue/tasks.py                          | send_daily_digest: except Exception: pass -> logger.warning with raw item + error; dropped stale noqa: BLE001 (line ~111)
src/adapters/queue/gpu_semaphore.py                   | documented fail-open Redis-error behavior in acquire() as intentional (BIN-143), pointer to BIN-147
src/adapters/ai/client.py                             | dropped stale noqa: BLE001 (line 305)
src/core/olx_location.py                              | dropped stale noqa: BLE001, kept explanatory comment
src/adapters/scrapers/olx.py                          | dropped stale noqa: BLE001, kept explanatory comment
src/adapters/scrapers/quintoandar.py                  | dropped stale noqa: BLE001, kept explanatory comment
src/adapters/scrapers/zapimoveis.py                   | dropped stale noqa: BLE001 (x2), kept explanatory comment where present
src/adapters/scrapers/listing_description.py          | dropped stale noqa: BLE001, kept explanatory comment
src/infra/ui_locale.py                                | dropped stale noqa: BLE001, kept explanatory comment
src/api/properties.py                                 | _embed_query_literal reuses a per-thread cached AI client (_get_embedding_client) + async_bridge.run_coro instead of asyncio.run() + create_ai_client() per request; added _reset_embedding_clients() test hook
src/tests/unit/test_send_daily_digest.py              | NEW — malformed-JSON logs warning + batch continues; all-valid batch logs nothing
src/tests/integration/test_semantic_search.py         | autouse fixture resets the new per-thread embedding client cache before/after each test
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
```

- `src/tests/unit/test_send_daily_digest.py` — regression coverage for item 1: a malformed alert entry logs `send_daily_digest_bad_alert_json` (raw item + error) and does not abort the batch; a fully-valid batch logs no warning.
- `src/tests/integration/test_semantic_search.py::test_semantic_search_orders_by_cosine` — exercises the full `_embed_query_literal` path against real PostGIS + pgvector, confirming the per-thread cached-client + `run_coro` refactor still returns correctly-ordered results (unchanged from before, since it was purely a reuse/perf change).
- Manual sanity check: called `_get_embedding_client()` twice under a mocked `create_ai_client` and confirmed the second call reuses the cached instance (no second construction), then confirmed `_reset_embedding_clients()` clears it for a fresh client on the next call.

## Notes / Follow-ups

- Item 2 (GPU semaphore fail-open) is deliberately left as a documented trade-off, not a config flag — see BIN-147 (semaphore TTL/timeout conflation) and BIN-159 (broader semaphore reliability follow-ups) for related hardening that might revisit this.
- Item 3 found 9 stale `noqa: BLE001` occurrences via fresh grep, 2 more than the 7 listed in the ticket (scrapers had moved during BIN-133's shared-base extraction, and `client.py`/`zapimoveis.py` had extra untracked occurrences) — all were removed.
- Adding `ruff`/`flake8-blind-except` to the lint pipeline (to make broad-except suppressions meaningful again) is explicitly out of scope here; if picked up later, re-add targeted `# noqa: BLE001` only where the exception is genuinely intended to be broad.
