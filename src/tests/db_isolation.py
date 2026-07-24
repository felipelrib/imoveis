"""Helpers to keep destructive integration tests off the scraped primary DB (BIN-71)."""

from __future__ import annotations

import os
from urllib.parse import urlparse

# Primary Compose / scraper database name. Integration wipe fixtures must not
# target this DB unless IMOVEIS_ALLOW_PRIMARY_DB_WIPE=1 (emergency only).
PRIMARY_DB_NAMES = frozenset({"realestate"})
DEFAULT_TEST_DB_NAME = "realestate_test"


def database_name_from_url(url: str) -> str:
    """Return the database name from a SQLAlchemy / libpq URL."""
    parsed = urlparse(url)
    name = (parsed.path or "").lstrip("/")
    # Drop query string fragments if path somehow includes them.
    return name.split("?", 1)[0]


def is_wipe_safe_database_url(
    url: str | None,
    *,
    allow_primary_wipe: bool | None = None,
) -> bool:
    """True when truncating all tables on this URL is allowed."""
    if not url:
        return False
    if allow_primary_wipe is None:
        allow_primary_wipe = os.environ.get("IMOVEIS_ALLOW_PRIMARY_DB_WIPE", "") == "1"
    if allow_primary_wipe:
        return True
    name = database_name_from_url(url)
    if not name:
        return False
    return name not in PRIMARY_DB_NAMES


def assert_wipe_safe_database_url(url: str | None) -> None:
    """Raise RuntimeError if *url* points at the primary scraped database."""
    if is_wipe_safe_database_url(url):
        return
    name = database_name_from_url(url or "") or "(missing)"
    raise RuntimeError(
        f"Refusing to wipe database {name!r}: integration tests must use "
        f"{DEFAULT_TEST_DB_NAME!r} (set via validate.sh / TEST_DATABASE_URL). "
        "Override only with IMOVEIS_ALLOW_PRIMARY_DB_WIPE=1."
    )
