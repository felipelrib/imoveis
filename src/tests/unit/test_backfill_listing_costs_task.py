"""Unit tests for ``tasks.backfill_listing_costs`` (Story 1.1): thin glue.

One happy path (loops keyset batches, commits per batch, returns counts) and
one error path (a failing batch rolls back, logs and re-raises, keeping the
batches already committed).
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

pytestmark = pytest.mark.unit


def _session_local():
    """A ``SessionLocal`` stand-in whose context manager yields one mock session."""
    session = MagicMock()
    factory = MagicMock()
    factory.return_value.__enter__.return_value = session
    factory.return_value.__exit__.return_value = False
    return factory, session


class TestBackfillListingCostsTask:
    def test_registered_under_its_task_name(self):
        from adapters.queue import tasks

        assert tasks.backfill_listing_costs_task.name == "tasks.backfill_listing_costs"

    @patch("adapters.queue.tasks.repopulate_listing_costs")
    def test_loops_batches_commits_each_and_returns_counts(self, repopulate):
        from adapters.queue import tasks

        factory, session = _session_local()
        repopulate.side_effect = [
            {"scanned": 2, "updated": 2, "last_id": "id-2"},
            {"scanned": 2, "updated": 1, "last_id": "id-4"},
            {"scanned": 1, "updated": 0, "last_id": None},
        ]

        with patch("adapters.queue.tasks.SessionLocal", factory):
            result = tasks.backfill_listing_costs_task.run(batch_size=2)

        assert result == {"status": "ok", "scanned": 5, "updated": 3, "batches": 3}
        assert repopulate.call_args_list == [
            call(session, after_id=None, batch_size=2),
            call(session, after_id="id-2", batch_size=2),
            call(session, after_id="id-4", batch_size=2),
        ]
        assert session.commit.call_count == 3
        session.rollback.assert_not_called()

    @patch("adapters.queue.tasks.logger")
    @patch("adapters.queue.tasks.repopulate_listing_costs")
    def test_failing_batch_rolls_back_logs_and_reraises(self, repopulate, logger):
        from adapters.queue import tasks

        factory, session = _session_local()
        repopulate.side_effect = [
            {"scanned": 2, "updated": 2, "last_id": "id-2"},
            RuntimeError("db gone"),
        ]

        with patch("adapters.queue.tasks.SessionLocal", factory):
            with pytest.raises(RuntimeError, match="db gone"):
                tasks.backfill_listing_costs_task.run(batch_size=2)

        # The first batch stays committed; only the failing one is rolled back.
        assert session.commit.call_count == 1
        session.rollback.assert_called_once()
        logger.error.assert_called_once()
        args, kwargs = logger.error.call_args
        assert args[0] == "listing_cost_backfill_failed"
        assert kwargs["error"] == "db gone"
        assert (kwargs["scanned"], kwargs["updated"], kwargs["batches"]) == (2, 2, 1)
