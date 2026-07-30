# Circuit breaker opens on sustained Cloudflare 403 blocks

> Feature branch: `feat/circuit-breaker-cloudflare-403` · Linear: `BIN-156` · Status: implemented

## Problem

All three scrapers' `_throttled_request` (`olx.py`, `quintoandar.py`, `zapimoveis.py`) only called
`RedisCircuitBreaker.record_failure()` — the counter the breaker's `is_open()` gate watches — for
`>=500`/`429` responses. A platform that Cloudflare fully blocks returns `403` on essentially every
request, so the breaker never opened. The scrape run kept paying its full jitter delay × `max_pages`
budget per price/neighbourhood window for the entire run, even though every single request failed
identically, instead of fast-failing and moving on to the next scheduled platform.

This is **not** about how 403s are classified for metrics — 403 correctly stays `unknown` (never an
`errors` tick, never a soft-deactivation signal; see `availability.py` and `CLAUDE.md`'s scraper
domain-validation-hooks section) — that existing, correct behavior is unchanged and now has a
regression test locking it. This ticket is only about feeding sustained 403 streaks into the circuit
breaker so `_throttled_request` fast-fails once a platform is confirmed blocked.

## Approach

- Extended `RedisCircuitBreaker.record_failure()` with an optional `reason` (default `"default"`,
  matching the pre-existing 5xx/429 bucket byte-for-byte) plus optional `threshold`/`cooldown`
  overrides. Each reason accumulates its own consecutive-failure counter in Redis
  (`circuit_breaker:{platform}:{reason}:failures`), so a streak of 403s can't be diluted by — or
  dilute — a streak of 500s, and a future reason can tune its own open/close timing independently.
- All reasons still trip the **same shared** `circuit_breaker:{platform}:open` flag, so `is_open()`
  (the single gate every `_throttled_request` checks before sleeping/making the live HTTP call) is
  unchanged and still blocks all further requests regardless of which failure mode tripped it.
- `record_success()` now resets the default counter plus every reason bucket the instance has seen
  (tracked in `self._known_reasons`), so a single successful request fully clears prior 403 and 5xx
  streaks alike — matching the existing all-clear semantics.
- Each scraper's `_throttled_request` gained one new branch: `elif response.status_code == 403:
  self._cb.record_failure(reason="cloudflare_403")`, ahead of the existing `>=500 or == 429` branch.
  Used the SAME threshold/cooldown as the default bucket (5 failures / 120s) for now — the ticket
  allows tuning 403 timing separately but no data yet justifies a different number; the `reason`
  parameter makes that a one-line change later without touching `redis_circuit_breaker.py` again.
- Did not touch the per-page-fetch `except Exception: return []` swallowing in
  `_fetch_page_listings`/`_fetch_window` (all three scrapers) — that's what makes fast-fail actually
  fast: `_throttled_request` checks `is_open()` *before* the jitter `sleep()` and before issuing the
  HTTP request, so once the breaker opens, every subsequent page/window attempt in the same run
  returns near-instantly instead of paying the full budget. No `errors`/`skipped` counters change at
  the `tasks.py` level either — a 403 page still yields `[]`, which was already excluded from those
  counters before this change.

## Changes

Files touched:

```
src/adapters/scrapers/redis_circuit_breaker.py | record_failure() takes reason/threshold/cooldown; record_success() clears all seen reason buckets; RECORD_FAILURE_SCRIPT takes an explicit shared open_key
src/adapters/scrapers/olx.py                   | _throttled_request: 403 -> record_failure(reason="cloudflare_403")
src/adapters/scrapers/quintoandar.py           | _throttled_request: 403 -> record_failure(reason="cloudflare_403")
src/adapters/scrapers/zapimoveis.py            | _throttled_request: 403 -> record_failure(reason="cloudflare_403")
src/tests/unit/test_cb.py                      | fake_script updated for 2-key signature; new tests: sustained-403-reason opens breaker, independent counters, independent threshold/cooldown, reset-on-success
src/tests/unit/test_olx.py                     | new tests: 403 uses separate reason bucket; end-to-end sustained-403 opens a REAL RedisCircuitBreaker + fast-fails without further sleep/HTTP; 403 page fetch still yields [] without raising
src/tests/unit/test_quintoandar.py             | new test: 403 uses separate reason bucket
src/tests/unit/test_zapimoveis.py              | new test: 403 uses separate reason bucket
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
bash scripts/agent/validate-scrapers.sh --require-live
```

Targeted:

```bash
PYTHONPATH=src pytest src/tests/unit/test_cb.py src/tests/unit/test_olx.py src/tests/unit/test_quintoandar.py src/tests/unit/test_zapimoveis.py -v
```

The key regression is `test_throttled_request_sustained_403_opens_real_circuit_breaker` in
`test_olx.py`: it wires a real (fake-Redis-backed) `RedisCircuitBreaker` into the scraper, drives 5
consecutive 403 responses through `_throttled_request`, asserts `is_open()` flips to `True` on the
5th, and then asserts a 6th call raises `CircuitBreakerOpenError` **without** calling
`session.get` again — i.e. no further sleep/HTTP budget is spent. Reverting the `elif
response.status_code == 403` branch in any of the three scrapers fails that file's corresponding
`..._records_403_as_separate_reason` test.

## Notes / Follow-ups

- Tracked as part of the BIN-128 tech-debt remediation epic (v0.10 milestone).
- If live traffic later shows 403 streaks need different open/close timing than 5xx/429 (e.g. open
  faster since a real Cloudflare block is near-100% consistent from the first request), tune via the
  `threshold=`/`cooldown=` kwargs already threaded through `record_failure(reason="cloudflare_403",
  ...)` — no further `redis_circuit_breaker.py` changes needed.
- Did not add an integration-level (`tasks.py`/`scrape_listings`) test asserting `errors` stays 0 on a
  403 streak — there is no existing test harness for that Celery task, and the relevant behavior
  (403 → `_fetch_page_listings` returns `[]` without raising) is already covered at the scraper unit
  level plus the pre-existing `availability.py` classification tests. Per `CLAUDE.md`'s risk-tiered
  testing table, `tasks.py` is thin glue — no new test theater added here.
