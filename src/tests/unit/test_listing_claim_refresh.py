"""Unit tests for listing claim refresh adapter + task glue (BIN-93)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from infra.config import ListingClaimStatsConfig


def _mappings_result(rows):
    """Build a fake Result with ``.mappings().all()`` / ``.first()``."""
    map_proxy = MagicMock()
    map_proxy.all.return_value = rows
    map_proxy.first.return_value = rows[0] if rows else None
    result = MagicMock()
    result.mappings.return_value = map_proxy
    return result


@pytest.mark.unit
class TestRefreshListingClaimStatsAdapter:
    def test_updates_quality_meta_only(self):
        from adapters.geo.listing_claim_refresh import refresh_listing_claim_stats

        sentiment_rows = [
            {
                "neighborhood_id": "n1",
                "meta": {
                    "sentiment": {
                        "green_flags": ["metro", "park"],
                        "red_flags": ["noise"],
                    }
                },
            },
            {
                "neighborhood_id": "n1",
                "meta": {
                    "sentiment": {"green_flags": ["metro"], "red_flags": []}
                },
            },
        ]
        session = MagicMock()
        # First execute: load sentiment rows; later: load nhood + update
        sentiment_result = _mappings_result(sentiment_rows)
        nhood_result = _mappings_result(
            [{"quality_meta": {"provider": "curated-yaml", "access": {"hub_id": "x"}}}]
        )
        update_result = MagicMock()
        session.execute.side_effect = [sentiment_result, nhood_result, update_result]

        cfg = ListingClaimStatsConfig(enabled=True, top_n=5, min_sample_size=1)
        stats = refresh_listing_claim_stats(
            session, cfg, refreshed_at="2026-07-27T15:00:00+00:00"
        )
        assert stats == {"processed": 1, "updated": 1, "skipped": 0, "errors": 0}
        session.commit.assert_called_once()
        # Third execute is the UPDATE
        update_call = session.execute.call_args_list[2]
        params = update_call.args[1]
        assert params["id"] == "n1"
        meta = json.loads(params["meta"])
        assert meta["provider"] == "curated-yaml"
        assert meta["access"]["hub_id"] == "x"
        claims = meta["listing_claim_stats"]
        assert claims["source"] == "listing_llm_aggregate"
        assert claims["sample_size"] == 2
        assert claims["top_green_flags"][0] == {"flag": "metro", "count": 2}

    def test_skips_below_min_sample_size(self):
        from adapters.geo.listing_claim_refresh import refresh_listing_claim_stats

        session = MagicMock()
        session.execute.return_value = _mappings_result(
            [
                {
                    "neighborhood_id": "n1",
                    "meta": {"sentiment": {"green_flags": ["metro"], "red_flags": []}},
                }
            ]
        )
        cfg = ListingClaimStatsConfig(enabled=True, min_sample_size=5)
        stats = refresh_listing_claim_stats(session, cfg)
        assert stats["processed"] == 1
        assert stats["updated"] == 0
        assert stats["skipped"] == 1
        # Only the sentiment load execute — no UPDATE
        assert session.execute.call_count == 1

    def test_skips_missing_neighbourhood(self):
        from adapters.geo.listing_claim_refresh import refresh_listing_claim_stats

        session = MagicMock()
        sentiment_result = _mappings_result(
            [
                {
                    "neighborhood_id": "missing",
                    "meta": {"sentiment": {"green_flags": ["x"], "red_flags": []}},
                }
            ]
        )
        empty_nhood = _mappings_result([])
        session.execute.side_effect = [sentiment_result, empty_nhood]

        cfg = ListingClaimStatsConfig(enabled=True, min_sample_size=1)
        stats = refresh_listing_claim_stats(session, cfg)
        assert stats["processed"] == 1
        assert stats["skipped"] == 1
        assert stats["updated"] == 0

    def test_filters_single_neighbourhood_query(self):
        from adapters.geo.listing_claim_refresh import refresh_listing_claim_stats

        session = MagicMock()
        session.execute.return_value = _mappings_result([])
        cfg = ListingClaimStatsConfig(enabled=True)
        stats = refresh_listing_claim_stats(
            session, cfg, neighborhood_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        )
        assert stats["processed"] == 0
        assert stats["updated"] == 0
        params = session.execute.call_args.args[1]
        assert params["nid"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    def test_row_error_increments_errors(self):
        from adapters.geo.listing_claim_refresh import refresh_listing_claim_stats

        session = MagicMock()
        sentiment_result = _mappings_result(
            [
                {
                    "neighborhood_id": "n1",
                    "meta": {"sentiment": {"green_flags": ["x"], "red_flags": []}},
                }
            ]
        )
        nhood_result = _mappings_result([{"quality_meta": {}}])
        session.execute.side_effect = [
            sentiment_result,
            nhood_result,
            RuntimeError("db down"),
        ]
        cfg = ListingClaimStatsConfig(enabled=True)
        stats = refresh_listing_claim_stats(session, cfg)
        assert stats["errors"] == 1
        assert stats["updated"] == 0
        session.commit.assert_called_once()

    def test_outer_failure_rolls_back(self):
        from adapters.geo.listing_claim_refresh import refresh_listing_claim_stats

        session = MagicMock()
        session.execute.side_effect = RuntimeError("boom")
        cfg = ListingClaimStatsConfig(enabled=True)
        with pytest.raises(RuntimeError, match="boom"):
            refresh_listing_claim_stats(session, cfg)
        session.rollback.assert_called_once()
        session.commit.assert_not_called()


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
        args, _kwargs = mock_refresh.call_args
        assert args[0] is session
        assert args[1].enabled is True
        assert args[1].top_n == 5
