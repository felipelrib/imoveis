"""Unit tests for listing claim refresh task glue (BIN-93)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from infra.config import ListingClaimStatsConfig


@pytest.mark.unit
class TestRefreshListingClaimStatsTask:
    @patch("adapters.geo.listing_claim_refresh.refresh_listing_claim_stats")
    @patch("adapters.queue.tasks.SessionLocal")
    @patch("adapters.queue.tasks.get_config")
    def test_skips_when_disabled(self, mock_get_config, mock_session, mock_refresh):
        from adapters.queue import tasks as tasks_mod

        cfg = MagicMock()
        cfg.neighbourhood_quality.listing_claim_stats = ListingClaimStatsConfig(
            enabled=False
        )
        mock_get_config.return_value = cfg

        result = tasks_mod.refresh_listing_claim_stats_task.run()
        assert result["status"] == "skipped"
        mock_refresh.assert_not_called()
        mock_session.assert_not_called()

    @patch("adapters.geo.listing_claim_refresh.refresh_listing_claim_stats")
    @patch("adapters.queue.tasks.SessionLocal")
    @patch("adapters.queue.tasks.get_config")
    def test_runs_when_enabled(self, mock_get_config, mock_session, mock_refresh):
        from adapters.queue import tasks as tasks_mod

        cfg = MagicMock()
        cfg.neighbourhood_quality.listing_claim_stats = ListingClaimStatsConfig(
            enabled=True, top_n=5
        )
        mock_get_config.return_value = cfg
        session = MagicMock()
        mock_session.return_value.__enter__.return_value = session
        mock_refresh.return_value = {
            "processed": 2,
            "updated": 1,
            "skipped": 1,
            "errors": 0,
        }

        result = tasks_mod.refresh_listing_claim_stats_task.run()
        assert result["status"] == "ok"
        assert result["updated"] == 1
        mock_refresh.assert_called_once()
        args, kwargs = mock_refresh.call_args
        assert args[0] is session
        assert args[1].enabled is True
        assert args[1].top_n == 5
