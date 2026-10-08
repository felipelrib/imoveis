"""Notifier registry and channels for saved-search new matches (v0.14-s1.9).

``smtplib.SMTP`` is always patched: no test opens a connection to a mail server.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import adapters.notify as notify
from adapters.notify.base import Notifier, SavedSearchNewMatches
from adapters.notify.email_notifier import EmailNotifier
from adapters.notify.log_notifier import LogNotifier


def _batch() -> SavedSearchNewMatches:
    return SavedSearchNewMatches(
        principal_id="default",
        search_id="aaaaaaaa-0000-0000-0000-000000000001",
        search_name="Savassi 2q",
        subject="1 imóvel novo na busca “Savassi 2q”",
        body="Busca salva: Savassi 2q\n\n1. Apartamento",
        property_ids=["p1"],
        generated_at=datetime(2026, 10, 8, 15, 0),
    )


def _email_notifier(**alerts) -> EmailNotifier:
    cfg = SimpleNamespace(
        digest_email="felipe@example.test",
        smtp_host="smtp.example.test",
        smtp_port=2525,
        smtp_user="",
        smtp_pass="",
        digest_mode=False,
    )
    for key, value in alerts.items():
        setattr(cfg, key, value)
    notifier = EmailNotifier.__new__(EmailNotifier)
    notifier.cfg = cfg
    notifier.r = MagicMock()
    return notifier


@pytest.mark.unit
class TestEmailNotifierNewMatches:
    def test_sends_once_with_the_rendered_subject_and_body(self):
        notifier = _email_notifier()
        with patch("adapters.notify.email_notifier.smtplib.SMTP") as smtp:
            notifier.send_new_matches(_batch())

        smtp.assert_called_once_with("smtp.example.test", 2525, timeout=30)
        server = smtp.return_value.__enter__.return_value
        server.send_message.assert_called_once()
        server.login.assert_not_called()
        message = server.send_message.call_args.args[0]
        assert message["Subject"] == "1 imóvel novo na busca “Savassi 2q”"
        assert message["To"] == "felipe@example.test"
        assert message["From"] == "noreply@imoveis.local"
        assert "Busca salva: Savassi 2q" in message.get_content()

    def test_logs_in_when_credentials_are_configured(self):
        notifier = _email_notifier(smtp_user="user@example.test", smtp_pass="pw")
        with patch("adapters.notify.email_notifier.smtplib.SMTP") as smtp:
            notifier.send_new_matches(_batch())

        server = smtp.return_value.__enter__.return_value
        server.login.assert_called_once_with("user@example.test", "pw")
        assert server.send_message.call_args.args[0]["From"] == "user@example.test"

    def test_smtp_failure_is_raised_to_the_caller(self):
        notifier = _email_notifier()
        with patch("adapters.notify.email_notifier.smtplib.SMTP") as smtp:
            smtp.return_value.__enter__.return_value.send_message.side_effect = OSError("refused")
            with pytest.raises(OSError):
                notifier.send_new_matches(_batch())

    def test_connection_failure_is_raised_to_the_caller(self):
        notifier = _email_notifier()
        with patch(
            "adapters.notify.email_notifier.smtplib.SMTP", side_effect=ConnectionRefusedError()
        ):
            with pytest.raises(ConnectionRefusedError):
                notifier.send_new_matches(_batch())

    @pytest.mark.parametrize("recipient", ["", "   ", None])
    def test_no_recipient_raises_before_any_connection(self, recipient):
        notifier = _email_notifier(digest_email=recipient)
        with patch("adapters.notify.email_notifier.smtplib.SMTP") as smtp:
            with pytest.raises(ValueError):
                notifier.send_new_matches(_batch())
        smtp.assert_not_called()


@pytest.mark.unit
class TestOtherChannels:
    def test_log_notifier_logs_ids_without_raising(self):
        with patch("adapters.notify.log_notifier.logger") as logger:
            LogNotifier().send_new_matches(_batch())
        logger.info.assert_called_once()
        assert logger.info.call_args.kwargs["property_ids"] == ["p1"]
        assert logger.info.call_args.kwargs["principal_id"] == "default"

    def test_a_notifier_without_an_implementation_says_unsupported(self):
        class _Legacy(Notifier):
            def send(self, alert) -> None:
                pass

            def send_digest(self, digest) -> None:
                pass

        with pytest.raises(NotImplementedError):
            _Legacy().send_new_matches(_batch())


@pytest.fixture
def fresh_registry():
    notify.reset_notifiers()
    yield
    notify.reset_notifiers()


def _alerts_cfg(*, enabled=True, channels=("log", "redis", "email")):
    return SimpleNamespace(alerts=SimpleNamespace(enabled=enabled, channels=list(channels)))


@pytest.mark.unit
class TestRegistryChannelLookup:
    def _build(self, cfg):
        with patch("adapters.notify.get_config", return_value=cfg), patch(
            "adapters.notify.email_notifier.EmailNotifier.__init__", return_value=None
        ), patch("adapters.notify.redis_notifier.RedisNotifier.__init__", return_value=None):
            return notify.get_notifiers(), notify.get_notifiers_for_channel("email")

    def test_email_lookup_returns_the_registry_s_own_email_notifier(self, fresh_registry):
        everyone, emails = self._build(_alerts_cfg())

        assert [type(n).__name__ for n in everyone] == [
            "LogNotifier",
            "RedisNotifier",
            "EmailNotifier",
        ]
        assert len(emails) == 1
        assert emails[0] is everyone[2]

    def test_the_registry_is_built_once(self, fresh_registry):
        cfg = _alerts_cfg()
        with patch("adapters.notify.get_config", return_value=cfg) as get_config, patch(
            "adapters.notify.email_notifier.EmailNotifier.__init__", return_value=None
        ), patch("adapters.notify.redis_notifier.RedisNotifier.__init__", return_value=None):
            first = notify.get_notifiers_for_channel("email")
            second = notify.get_notifiers_for_channel("email")
            notify.get_notifiers()
        assert first[0] is second[0]
        assert get_config.call_count == 1

    def test_no_email_channel_configured_is_an_empty_lookup(self, fresh_registry):
        _everyone, emails = self._build(_alerts_cfg(channels=("log", "redis")))
        assert emails == []

    def test_alerts_disabled_is_an_empty_lookup_and_a_log_only_registry(self, fresh_registry):
        everyone, emails = self._build(_alerts_cfg(enabled=False))
        assert emails == []
        assert [type(n).__name__ for n in everyone] == ["LogNotifier"]

    def test_unknown_channel_is_an_empty_lookup(self, fresh_registry):
        self._build(_alerts_cfg())
        assert notify.get_notifiers_for_channel("push") == []
