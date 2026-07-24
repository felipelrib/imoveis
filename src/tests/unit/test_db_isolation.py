"""Unit tests for integration DB isolation helpers (BIN-71)."""

from __future__ import annotations

import pytest

from tests.db_isolation import (
    assert_wipe_safe_database_url,
    database_name_from_url,
    is_wipe_safe_database_url,
)


@pytest.mark.unit
class TestDbIsolation:
    def test_parses_database_name(self):
        assert (
            database_name_from_url(
                "postgresql://imoveis:x@localhost:5433/realestate_test"
            )
            == "realestate_test"
        )

    def test_primary_realestate_not_wipe_safe(self):
        url = "postgresql://imoveis:x@localhost:5433/realestate"
        assert is_wipe_safe_database_url(url, allow_primary_wipe=False) is False
        with pytest.raises(RuntimeError, match="Refusing to wipe"):
            assert_wipe_safe_database_url(url)

    def test_realestate_test_is_wipe_safe(self):
        url = "postgresql://imoveis:x@localhost:5433/realestate_test"
        assert is_wipe_safe_database_url(url, allow_primary_wipe=False) is True
        assert_wipe_safe_database_url(url)

    def test_escape_hatch_allows_primary(self):
        url = "postgresql://imoveis:x@localhost:5433/realestate"
        assert is_wipe_safe_database_url(url, allow_primary_wipe=True) is True
