"""Suite-wide environment guard (DW-33).

``.env.local`` is dual-purpose: it is this workspace's compose/port identity
*and* the ``EnvironmentFile=`` of the host-side cloud backfill runner (ADR 0006,
story ``v0.13-s3.1``). The sanctioned way to enable that runner is a per-host
config override — ``IMOVEIS_AI__ENRICHMENT_ROUTING__{VISUAL,SENTIMENT,DEAL_VERDICT}=gemma``
— because the committed ``configs/app_config.yaml`` must stay all-local (NFR-1,
pinned by ``test_config.py::test_enrichment_routing_default_all_local``).

Those overrides are read by ``infra.config._apply_env_overrides`` for *every*
``load_config()`` call, including calls against a minimal fixture YAML. An
operator override therefore injects a **partial** ``ai.enrichment_routing`` map
into an unrelated test's fixture and trips ``AIConfig``'s totality validator —
observed 2026-08-12 as a Redis test failing with a routing error (DW-33).

``scripts/agent/lib.sh::load_workspace_env`` is the primary fix: the gate scripts
read only an allowlist of workspace-identity keys *out of that file*, so an
override written there never enters the pytest process to begin with. It filters
a file, though — it cannot unset what a developer exported in their own shell.
This fixture is the second layer, and the only one that covers every origin: it
makes the suite deterministic no matter how it was invoked (a bare ``pytest`` in
a shell that sourced ``.env.local``, an IDE runner, an exported shell variable)
— and it is where the former per-module guards fold, instead of every module
growing its own copy.

Scope is the **whole** ``IMOVEIS_*`` prefix, minus a short named denylist.
``_apply_env_overrides`` applies every variable carrying the prefix, not only the
``__``-nested ones: ``IMOVEIS_AI=x`` sets the top-level ``ai`` key to the string
``"x"`` and breaks ``load_config()`` for every test that follows. Default-deny is
therefore the only rule that actually protects the suite; the exceptions are the
suite's own destructive-action escape hatches (``IMOVEIS_ALLOW_PRIMARY_DB_WIPE``
/ ``IMOVEIS_ALLOW_PRIMARY_REDIS_WIPE`` — BIN-71 / BIN-117), which are read by
scripts and fixtures, never by the config loader.
"""

from __future__ import annotations

import os

import pytest

#: Prefix of the generic config-override channel (``infra.config._ENV_PREFIX``).
CONFIG_ENV_PREFIX = "IMOVEIS_"

#: The only ``IMOVEIS_*`` names the suite keeps. Both are destructive-action
#: consent flags the suite/scripts set for themselves (BIN-71 / BIN-117); neither
#: is read by ``infra.config``. Adding a name here is a deliberate act — it
#: re-opens the DW-33 channel for that variable.
PRESERVED_ENV_VARS = frozenset(
    {
        "IMOVEIS_ALLOW_PRIMARY_DB_WIPE",
        "IMOVEIS_ALLOW_PRIMARY_REDIS_WIPE",
    }
)


def should_strip_env_var(name: str) -> bool:
    """True when *name* is an ``IMOVEIS_*`` variable the suite must not inherit.

    ``_apply_env_overrides`` walks **every** variable whose name starts with the
    prefix and writes it into the loaded config: ``IMOVEIS_A__B__C`` addresses
    the nested leaf ``a.b.c``, while a prefixed name *without* ``__``
    (``IMOVEIS_AI=x``) addresses the top-level key ``ai`` — replacing a whole
    config section with a string. Both break tests, so the rule is default-deny
    over the prefix with :data:`PRESERVED_ENV_VARS` as the only exceptions.
    """
    if not name.startswith(CONFIG_ENV_PREFIX):
        return False
    return name not in PRESERVED_ENV_VARS


@pytest.fixture(autouse=True)
def _strip_config_override_env(monkeypatch: pytest.MonkeyPatch):
    """Remove operator config overrides from ``os.environ`` for every test.

    Runs at setup, before the test body, so a test that deliberately sets its
    own ``IMOVEIS_<SECTION>__<KEY>`` via ``monkeypatch.setenv`` is unaffected.
    """
    for name in [key for key in os.environ if should_strip_env_var(key)]:
        monkeypatch.delenv(name, raising=False)
