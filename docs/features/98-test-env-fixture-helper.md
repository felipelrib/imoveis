# Test env fixture helper — centralize shared env-var reads across integration/unit tests

> Feature branch: `feat/test-env-fixture-helper` · Linear: `BIN-142` · Status: implemented

## Problem

`REDIS_URL`, `API_KEY`, and `OLLAMA_HOST` were each read independently via
copy-pasted `os.environ.get(name, default)` calls across five test-fixture
call sites in four files (`test_e2e.py`, `test_owner_scoped_personalization.py`,
`test_properties_ai_scores.py`, `test_ai_quality.py`). This wasn't a
convention violation — tests are an explicitly exempted context for
`os.getenv()` in `CLAUDE.md` — but the duplicated logic (env var name +
default value baked into each call site) would silently drift if any of
those names or defaults ever changed centrally, since there was nothing
forcing the copies to stay in sync.

Separately, two other files (`db_isolation.py`, `redis_isolation.py`) read
`IMOVEIS_ALLOW_PRIMARY_DB_WIPE` / `IMOVEIS_ALLOW_PRIMARY_REDIS_WIPE`
directly for destructive-action guards. Those reads are legitimate and
should **not** be swept into the same centralization — they gate a safety
check at the call site, not shared fixture setup — so this feature adds an
explicit comment marking them as an intentional exception instead.

## Approach

- Added `src/tests/env_helpers.py` exposing three small accessors:
  `get_redis_url()`, `get_api_key(default="")`, `get_ollama_host(default=...)`.
  Each wraps a single `os.environ.get(...)` call so the variable name and
  default live in exactly one place.
- Updated all five listed call sites to import from `tests.env_helpers`
  instead of reading `os.environ` directly. `test_properties_ai_scores.py`
  keeps its own `os.environ.get("DATABASE_URL")` read (out of scope for this
  ticket — different variable, different concern) so `import os` stays there.
  `test_e2e.py`, `test_owner_scoped_personalization.py`, and
  `test_ai_quality.py` no longer need `import os` at all after the swap.
- Left `db_isolation.py` / `redis_isolation.py` untouched behaviorally, only
  adding a one-line comment at each destructive-guard read explaining why it
  is intentionally *not* routed through `env_helpers`.
- New unit tests (`test_env_helpers.py`) cover set/unset/custom-default for
  all three accessors via `monkeypatch.setenv`/`delenv` — this is a small
  pure helper, so plain TDD-style unit coverage was the right tier (no
  integration services needed).

## Changes

Files touched:

```
 src/tests/env_helpers.py                                 | NEW — shared REDIS_URL/API_KEY/OLLAMA_HOST accessors
 src/tests/unit/test_env_helpers.py                        | NEW — unit tests for env_helpers accessors
 src/tests/integration/test_e2e.py                         | Route REDIS_URL/API_KEY reads through env_helpers; drop unused `import os`
 src/tests/integration/test_owner_scoped_personalization.py| Route API_KEY read through env_helpers; drop unused `import os`
 src/tests/integration/test_properties_ai_scores.py        | Route API_KEY read through env_helpers (DATABASE_URL read unchanged)
 src/tests/unit/test_ai_quality.py                         | Route OLLAMA_HOST reads through env_helpers; drop unused `import os`
 src/tests/db_isolation.py                                 | Comment noting IMOVEIS_ALLOW_PRIMARY_DB_WIPE is an intentional exception
 src/tests/redis_isolation.py                              | Comment noting IMOVEIS_ALLOW_PRIMARY_REDIS_WIPE is an intentional exception
```

## New Dependencies

None.

## How to Test

1. Unit tests for the new helper:
   ```bash
   PYTHONPATH=src pytest src/tests/unit/test_env_helpers.py -v
   ```
2. Full gate:
   ```bash
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- Scope was deliberately limited to the five call sites named in BIN-142
  (`REDIS_URL`/`API_KEY`/`OLLAMA_HOST`). `DATABASE_URL` reads (e.g. in
  `test_properties_ai_scores.py`, `integration/conftest.py`) were left as-is
  — out of scope for this ticket, and a reasonable follow-up if the same
  drift risk is ever flagged for that variable.
- Parent epic: BIN-128.
