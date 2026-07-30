"""Unit tests for adapters.scrapers.base shared helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from adapters.scrapers.base import BaseScraper


@pytest.mark.unit
class TestRecordCircuitOutcome:
    """BIN-156: shared success/failure classification used by every
    platform's ``_throttled_request`` (extracted to de-duplicate identical
    logic across olx.py / quintoandar.py / zapimoveis.py).
    """

    @pytest.mark.parametrize("status_code", [200, 201, 204, 299])
    def test_2xx_records_success(self, status_code):
        cb = MagicMock()
        BaseScraper._record_circuit_outcome(cb, status_code)
        cb.record_success.assert_called_once()
        cb.record_failure.assert_not_called()

    def test_403_records_failure_with_cloudflare_reason(self):
        """Sustained 403s must feed a SEPARATE reason bucket, not be dropped."""
        cb = MagicMock()
        BaseScraper._record_circuit_outcome(cb, 403)
        cb.record_failure.assert_called_once_with(reason="cloudflare_403")
        cb.record_success.assert_not_called()

    @pytest.mark.parametrize("status_code", [429, 500, 502, 503])
    def test_5xx_and_429_record_default_failure(self, status_code):
        cb = MagicMock()
        BaseScraper._record_circuit_outcome(cb, status_code)
        cb.record_failure.assert_called_once_with()
        cb.record_success.assert_not_called()

    @pytest.mark.parametrize("status_code", [301, 302, 400, 401, 404, 410])
    def test_other_client_errors_and_redirects_are_a_noop(self, status_code):
        """403 gets its own bucket, but other 4xx/3xx must not touch the breaker."""
        cb = MagicMock()
        BaseScraper._record_circuit_outcome(cb, status_code)
        cb.record_failure.assert_not_called()
        cb.record_success.assert_not_called()
