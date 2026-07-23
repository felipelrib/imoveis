# appconfig-proxy-settings — Typed YAML proxy block on AppConfig

> Feature branch: `feat/bin-47-appconfig-proxy-settings` · Linear: `BIN-47` · Status: implemented

## Problem

`configs/app_config.yaml` already documented a `proxy:` section (`enabled`, `url`,
`rotation_strategy`, `pool`), but `AppConfig` ignored it. Operators could not turn
proxy enablement on via config (AD-2); scrapers had no typed source of truth for
FR-20 before Story 3.2 wires the HTTP layer.

## Approach

- Add a frozen Pydantic `ProxyConfig` with `enabled`, `url`, `rotation_strategy`
  (`round_robin` | `random`), and `pool`, matching the existing YAML shape.
- Attach `proxy: ProxyConfig` on `AppConfig` so `load_config` / `get_config` expose
  the block; invalid strategies fail validation as `ConfigError`.
- Keep sample YAML credential-free (null URL, empty pool, commented examples only).
- Scraper HTTP rotation remains out of scope (BIN-48 / Story 3.2).

## Changes

Files touched:

```
 src/infra/config.py                                      | ADD — ProxyConfig model + AppConfig.proxy field
 src/tests/unit/test_config.py                            | ADD — disabled / single-url / pool / invalid strategy / env override tests
 docs/features/32-appconfig-proxy-settings.md             | NEW — this doc
 _bmad-output/implementation-artifacts/sprint-status.yaml | UPDATE — 3-1 done, epic-3 in-progress
```

## New Dependencies

None.

## How to Test

1. Confirm defaults from the real YAML:
   ```bash
   python -c "from src.infra.config import get_config; print(get_config().proxy)"
   ```
   Expect `enabled=False`, `url=None`, `rotation_strategy='round_robin'`, `pool=[]`.
2. Or run the config unit suite via the agent gate:
   ```bash
   bash scripts/agent/validate.sh fast
   ```

## Notes / Follow-ups

- Related: BIN-48 (rotating proxy in scraper HTTP layer) — **done**
  (`docs/features/35-rotating-proxy-scraper-http.md`); BIN-49 (operator enablement /
  observability) — **done** (`docs/features/37-operator-proxy-observability.md`).
- Platform `extra.proxy` override vs global pool: non-null override wins; null
  defers to global (Story 3.2).
