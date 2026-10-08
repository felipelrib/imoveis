"""``tasks.evaluate_watchlist_alerts``: a drop that reaches the threshold is sent.

Regression: the task built ``PriceDropAlert(..., title=...)`` although the
payload has no ``title`` field, so the first watchlist entry whose drop reached
its threshold raised ``TypeError`` before any notifier ran and before
``last_notified_price`` was stored. The path had no test.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from adapters.notify.base import PriceDropAlert


def _row(**overrides):
    values = {
        "id": "w1",
        "property_id": "11111111-0000-0000-0000-000000000001",
        "min_drop_pct": 5.0,
        "last_notified_price": 1000.0,
        "current_price": 900.0,
        "listing_type": "rent",
        "platform": "olx",
        "title": "Apartamento Savassi",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _run(rows, notifier):
    from adapters.queue.tasks import evaluate_watchlist_alerts

    session = MagicMock()
    session.execute.return_value.fetchall.return_value = rows
    session_local = MagicMock()
    session_local.return_value.__enter__.return_value = session
    with patch("adapters.queue.tasks.SessionLocal", session_local), patch(
        "adapters.notify.get_notifiers", return_value=[notifier]
    ):
        evaluate_watchlist_alerts.run()
    return session


@pytest.mark.unit
def test_a_drop_at_the_threshold_is_sent_and_the_notified_price_is_stored():
    notifier = MagicMock()

    session = _run([_row()], notifier)

    notifier.send.assert_called_once()
    alert = notifier.send.call_args.args[0]
    assert alert == PriceDropAlert(
        property_id="11111111-0000-0000-0000-000000000001",
        old_price=1000.0,
        new_price=900.0,
        drop_pct=pytest.approx(10.0),
        platform="olx",
        listing_type="rent",
    )
    update = session.execute.call_args_list[-1]
    assert "UPDATE watchlist SET last_notified_price" in str(update.args[0])
    assert update.args[1] == {"price": 900.0, "id": "w1"}
    session.commit.assert_called_once()


@pytest.mark.unit
def test_a_drop_below_the_threshold_sends_nothing():
    notifier = MagicMock()

    session = _run([_row(current_price=980.0)], notifier)

    notifier.send.assert_not_called()
    assert session.execute.call_count == 1  # the SELECT only
