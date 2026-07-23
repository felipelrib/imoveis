"""Unit tests for scheduled top-deals digest (BIN-52)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from adapters.notify.base import TopDealsDigest
from adapters.notify.log_notifier import LogNotifier
from core.top_deals_digest import TOP_DEALS_RULE, select_top_deals


def _row(
    *,
    prop_id: str,
    combined_score: float,
    first_seen: datetime,
    title: str = "Deal",
    price: float = 3000.0,
):
    return {
        "id": prop_id,
        "platform": "olx",
        "platform_id": f"p-{prop_id}",
        "title": title,
        "price": price,
        "area_m2": 50.0,
        "bedrooms": 2,
        "bathrooms": 1,
        "address": "Rua A",
        "image_urls": [],
        "first_seen": first_seen,
        "stat_score": combined_score,
        "ai_score": combined_score,
        "combined_score": combined_score,
        "percentile_rank": 0.9,
        "z_score": 1.0,
        "price_per_m2": 60.0,
        "neighborhood_mean": 55.0,
        "meta": {},
        "neighborhood_id": None,
        "neighborhood_name": "Centro",
        "parking": 0,
        "description": "",
        "props_json": {},
        "lon": -46.6,
        "lat": -23.5,
        "listings": [
            {
                "platform": "olx",
                "platform_listing_id": "1",
                "listing_type": "rent",
                "price": price,
                "currency": "BRL",
                "url": "https://example.com",
                "is_furnished": False,
                "accepts_pets": True,
                "condo_fee": None,
                "iptu": None,
            }
        ],
    }


@pytest.mark.unit
class TestSelectTopDeals:
    def test_empty_result(self):
        session = MagicMock()
        result = MagicMock()
        result.mappings.return_value.fetchall.return_value = []
        session.execute.return_value = result

        assert select_top_deals(session, limit=10) == []
        session.execute.assert_called_once()

    def test_zero_limit_skips_query(self):
        session = MagicMock()
        assert select_top_deals(session, limit=0) == []
        session.execute.assert_not_called()

    def test_projects_ad12_fields(self):
        now = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
        high = _row(prop_id="aaa", combined_score=0.9, first_seen=now, title="High")
        low = _row(prop_id="bbb", combined_score=0.5, first_seen=now, title="Low")

        session = MagicMock()
        result = MagicMock()
        result.mappings.return_value.fetchall.return_value = [high, low]
        session.execute.return_value = result

        items = select_top_deals(
            session,
            lookback_hours=168,
            min_combined_score=0.0,
            limit=10,
            now=now,
        )

        assert [i["id"] for i in items] == ["aaa", "bbb"]
        assert items[0]["combined_score"] == 0.9
        assert items[0]["neighborhood_name"] == "Centro"
        assert items[0]["primary_listing"] is not None
        assert "price" in items[0]

        params = session.execute.call_args.args[1]
        assert params["min_score"] == 0.0
        assert params["limit"] == 10
        assert params["since"] == datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


@pytest.mark.unit
class TestLogNotifierDigest:
    def test_send_digest_logs_count_and_ids(self):
        digest = TopDealsDigest(
            principal_id="default",
            generated_at=datetime(2026, 7, 23, tzinfo=timezone.utc),
            properties=[{"id": "p1"}, {"id": "p2"}],
            rule=TOP_DEALS_RULE,
        )
        with patch("adapters.notify.log_notifier.logger") as logger:
            LogNotifier().send_digest(digest)
        logger.info.assert_called_once()
        kwargs = logger.info.call_args.kwargs
        assert kwargs["count"] == 2
        assert kwargs["property_ids"] == ["p1", "p2"]
        assert kwargs["principal_id"] == "default"


@pytest.mark.unit
class TestSendTopDealsDigestTask:
    @patch("adapters.queue.tasks.get_config")
    def test_disabled_skips_without_notifiers(self, mock_get_config):
        from adapters.queue.tasks import send_top_deals_digest

        cfg = MagicMock()
        cfg.alerts.top_deals.enabled = False
        mock_get_config.return_value = cfg

        with patch("adapters.notify.get_notifiers") as get_notifiers:
            result = send_top_deals_digest.run()

        assert result == {"status": "skipped", "sent": 0}
        get_notifiers.assert_not_called()

    @patch("adapters.queue.tasks.SessionLocal")
    @patch("adapters.queue.tasks.get_config")
    def test_empty_selection_does_not_call_notifiers_or_smtp(
        self, mock_get_config, mock_session_local
    ):
        from adapters.queue.tasks import send_top_deals_digest

        top = SimpleNamespace(
            enabled=True,
            lookback_hours=168,
            min_combined_score=0.0,
            limit=10,
        )
        cfg = MagicMock()
        cfg.alerts.top_deals = top
        cfg.auth.principal_id = "default"
        mock_get_config.return_value = cfg
        mock_session_local.return_value.__enter__.return_value = MagicMock()

        notifier = MagicMock()
        with patch("core.top_deals_digest.select_top_deals", return_value=[]):
            with patch("adapters.notify.get_notifiers", return_value=[notifier]) as gn:
                with patch("smtplib.SMTP") as smtp:
                    result = send_top_deals_digest.run()

        assert result == {"status": "empty", "sent": 0}
        gn.assert_not_called()
        notifier.send_digest.assert_not_called()
        smtp.assert_not_called()

    @patch("adapters.queue.tasks.SessionLocal")
    @patch("adapters.queue.tasks.get_config")
    def test_enabled_fans_out_to_notifiers(self, mock_get_config, mock_session_local):
        from adapters.queue.tasks import send_top_deals_digest

        top = SimpleNamespace(
            enabled=True,
            lookback_hours=24,
            min_combined_score=0.5,
            limit=5,
        )
        cfg = MagicMock()
        cfg.alerts.top_deals = top
        cfg.auth.principal_id = "default"
        mock_get_config.return_value = cfg
        mock_session_local.return_value.__enter__.return_value = MagicMock()

        props = [{"id": "p1", "title": "Nice", "combined_score": 0.8, "price": 2000}]
        notifier = MagicMock()

        with patch("core.top_deals_digest.select_top_deals", return_value=props):
            with patch("adapters.notify.get_notifiers", return_value=[notifier]):
                result = send_top_deals_digest.run()

        assert result == {"status": "sent", "sent": 1}
        notifier.send_digest.assert_called_once()
        digest = notifier.send_digest.call_args.args[0]
        assert isinstance(digest, TopDealsDigest)
        assert digest.principal_id == "default"
        assert digest.properties == props
        assert digest.rule == TOP_DEALS_RULE


@pytest.mark.unit
class TestEmailNotifierDigest:
    def test_send_digest_does_not_queue_price_drop_list(self):
        from adapters.notify.email_notifier import EmailNotifier

        digest = TopDealsDigest(
            principal_id="default",
            generated_at=datetime(2026, 7, 23, tzinfo=timezone.utc),
            properties=[
                {
                    "id": "p1",
                    "title": "Flat",
                    "combined_score": 0.9,
                    "price": 2500,
                    "neighborhood_name": "Centro",
                }
            ],
            rule=TOP_DEALS_RULE,
        )
        with patch("adapters.notify.email_notifier.get_config") as gc:
            with patch("adapters.notify.email_notifier.get_redis") as gr:
                alerts = MagicMock()
                alerts.digest_mode = True
                alerts.digest_email = "ops@example.com"
                alerts.smtp_host = "localhost"
                alerts.smtp_port = 1025
                alerts.smtp_user = ""
                alerts.smtp_pass = ""
                gc.return_value = MagicMock(alerts=alerts)
                redis = MagicMock()
                gr.return_value = redis
                with patch("smtplib.SMTP") as smtp_cls:
                    smtp = MagicMock()
                    smtp_cls.return_value.__enter__.return_value = smtp
                    EmailNotifier().send_digest(digest)

        redis.rpush.assert_not_called()
        smtp.send_message.assert_called_once()
