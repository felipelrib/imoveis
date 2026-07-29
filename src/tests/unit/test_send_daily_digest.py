"""Unit tests for tasks.send_daily_digest malformed-alert-JSON handling (BIN-143).

Regression: the digest loop used to swallow json.loads failures with a bare
``except Exception: pass`` — zero logging, silent data loss. It now logs a
warning with the offending raw item via infra.logging.get_logger.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestSendDailyDigestMalformedAlert:
    @patch("adapters.notify.email_notifier.EmailNotifier")
    @patch("adapters.queue.tasks.get_redis")
    @patch("adapters.queue.tasks.logger")
    def test_malformed_alert_json_logs_warning_and_continues(
        self, mock_logger, mock_get_redis, mock_email_notifier_cls
    ):
        from adapters.queue import tasks

        good_alert = b'{"property_id": "p1", "old_price": 2000, "new_price": 1800}'
        bad_alert = b"{not valid json"

        redis_client = MagicMock()
        redis_client.lrange.return_value = [good_alert, bad_alert]
        mock_get_redis.return_value = redis_client

        notifier = MagicMock()
        mock_email_notifier_cls.return_value = notifier

        result = tasks.send_daily_digest()

        # Malformed item is skipped but does not abort the batch.
        assert result == {"sent": 1}
        notifier.send_batch.assert_called_once()
        (sent_alerts,), _ = notifier.send_batch.call_args
        assert sent_alerts == [{"property_id": "p1", "old_price": 2000, "new_price": 1800}]

        # Warning logged with the offending raw item (not silently dropped).
        mock_logger.warning.assert_called_once()
        args, kwargs = mock_logger.warning.call_args
        assert args[0] == "send_daily_digest_bad_alert_json"
        assert kwargs["raw_item"] == "{not valid json"
        assert "error" in kwargs

        redis_client.delete.assert_called_once_with("alerts:email_digest")

    @patch("adapters.notify.email_notifier.EmailNotifier")
    @patch("adapters.queue.tasks.get_redis")
    @patch("adapters.queue.tasks.logger")
    def test_all_valid_alerts_no_warning(
        self, mock_logger, mock_get_redis, mock_email_notifier_cls
    ):
        from adapters.queue import tasks

        redis_client = MagicMock()
        redis_client.lrange.return_value = [b'{"property_id": "p1"}']
        mock_get_redis.return_value = redis_client
        mock_email_notifier_cls.return_value = MagicMock()

        result = tasks.send_daily_digest()

        assert result == {"sent": 1}
        mock_logger.warning.assert_not_called()
