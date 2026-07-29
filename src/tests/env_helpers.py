"""Shared env-var accessors for test fixtures (BIN-142).

Several integration/unit test modules independently read the same handful of
environment variables (``REDIS_URL``, ``API_KEY``, ``OLLAMA_HOST``) via
copy-pasted ``os.environ.get(name, default)`` calls. Centralizing the reads
here means the variable names and their defaults only need to change in one
place if they ever drift.

Note: the destructive-action guard reads in ``tests.db_isolation`` /
``tests.redis_isolation`` (``IMOVEIS_ALLOW_PRIMARY_DB_WIPE`` /
``IMOVEIS_ALLOW_PRIMARY_REDIS_WIPE``) are an intentional exception and are
NOT routed through this module — see the comments at those call sites.
"""

from __future__ import annotations

import os

DEFAULT_OLLAMA_HOST = "http://localhost:11434"


def get_redis_url() -> str | None:
    """Return ``REDIS_URL`` from the environment, or ``None`` if unset."""
    return os.environ.get("REDIS_URL")


def get_api_key(default: str = "") -> str:
    """Return ``API_KEY`` from the environment, or *default* if unset."""
    return os.environ.get("API_KEY", default)


def get_ollama_host(default: str = DEFAULT_OLLAMA_HOST) -> str:
    """Return ``OLLAMA_HOST`` from the environment, or *default* if unset."""
    return os.environ.get("OLLAMA_HOST", default)
