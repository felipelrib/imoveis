"""The two saved-search new-match beat tasks (v0.14-s1.9): thin glue.

One happy and one error path each, plus the master switch. The SQL and the
rules are tested in ``test_saved_search_alerts.py`` (pure) and
``tests/integration/test_saved_search_new_matches.py`` (Postgres).
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from adapters.notify.base import Notifier, SavedSearchNewMatches
from core.property_list_filters import PropertyMatchFilters

NOW = datetime(2026, 10, 8, 15, 0)  # 12:00 in Sao Paulo
ENABLED_AT = datetime(2026, 10, 7, 12, 0)
SEARCH_A = "aaaaaaaa-0000-0000-0000-000000000001"
SEARCH_B = "bbbbbbbb-0000-0000-0000-000000000002"


def _cfg(*, enabled=True, app_base_url="", locale="pt-BR", max_items=20):
    new_match = SimpleNamespace(
        enabled=enabled,
        match_interval_minutes=15,
        window_hour=7,
        window_timezone="America/Sao_Paulo",
        hold_warning_hours=168,
        max_items_per_email=max_items,
        app_base_url=app_base_url,
    )
    return SimpleNamespace(
        alerts=SimpleNamespace(new_match=new_match),
        auth=SimpleNamespace(principal_id="default"),
        ui=SimpleNamespace(locale=locale),
    )


def _session_with(rows, locked=None):
    """``rows`` answer the task's first SELECT.

    ``locked`` answers the sender's per-search row lock, one entry per search
    (``None`` = another run holds that search). By default each search is free
    and its state is what the first SELECT returned.
    """
    session = MagicMock()
    session.execute.return_value.fetchall.return_value = rows
    if locked is None:
        locked = [tuple(row[3:6]) for row in rows]
    session.execute.return_value.fetchone.side_effect = list(locked)
    session_local = MagicMock()
    session_local.return_value.__enter__.return_value = session
    return session_local, session


class _FakeNotifier(Notifier):
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.batches: list[SavedSearchNewMatches] = []
        self.other_calls = 0

    def send(self, alert) -> None:
        self.other_calls += 1

    def send_digest(self, digest) -> None:
        self.other_calls += 1

    def send_new_matches(self, batch: SavedSearchNewMatches) -> None:
        if self.fail:
            raise RuntimeError("smtp down")
        self.batches.append(batch)


@pytest.fixture
def registry(monkeypatch):
    """The real registry, holding fakes for all three channel types."""
    fakes = {"log": _FakeNotifier(), "redis": _FakeNotifier(), "email": _FakeNotifier()}
    monkeypatch.setattr("adapters.notify._registry", list(fakes.items()))
    return fakes


@pytest.mark.unit
class TestMatcherTask:
    def test_master_switch_off_touches_nothing(self):
        from adapters.queue.tasks import match_saved_search_new_matches

        with patch("adapters.queue.tasks.get_config", return_value=_cfg(enabled=False)), patch(
            "adapters.queue.tasks.SessionLocal"
        ) as session_local, patch("core.saved_search_alerts.record_new_matches") as record:
            result = match_saved_search_new_matches.run()

        assert result["status"] == "skipped"
        assert result["matched"] == 0
        session_local.assert_not_called()
        record.assert_not_called()

    def test_records_per_search_and_reports_the_hold(self):
        from adapters.queue.tasks import match_saved_search_new_matches

        session_local, session = _session_with(
            [
                (SEARCH_A, {"listing_type": "rent"}, ENABLED_AT),
                (SEARCH_B, {"q": "varanda"}, ENABLED_AT),
            ]
        )
        hold = {"held": 3, "oldest_held_hours": 5.0, "held_overdue": 0}
        with patch("adapters.queue.tasks.get_config", return_value=_cfg()), patch(
            "adapters.queue.tasks.SessionLocal", session_local
        ), patch("adapters.queue.tasks._utcnow_naive", return_value=NOW), patch(
            "core.saved_search_alerts.record_new_matches", return_value=2
        ) as record, patch("core.saved_search_alerts.hold_report", return_value=hold) as report:
            result = match_saved_search_new_matches.run()

        assert result == {
            "status": "ok",
            "searches": 2,
            "matched": 2,
            "unsupported": 1,
            "errors": 0,
            "held": 3,
            "oldest_held_hours": 5.0,
            "held_overdue": 0,
        }
        record.assert_called_once()
        kwargs = record.call_args.kwargs
        assert kwargs["search_id"] == SEARCH_A
        assert kwargs["owner"] == "default"
        assert kwargs["filters"] == PropertyMatchFilters(listing_type="rent")
        assert kwargs["enabled_at"] == ENABLED_AT
        # No age limit is handed to the matcher: a hold never expires.
        assert set(kwargs) == {"search_id", "owner", "filters", "enabled_at", "now"}
        assert session.commit.call_count == 1
        report.assert_called_once()
        assert report.call_args.kwargs["floor"] == ENABLED_AT
        assert report.call_args.kwargs["overdue_after_hours"] == 168
        # Only the principal's searches are loaded.
        assert session.execute.call_args_list[0].args[1] == {"owner": "default"}

    def test_a_failing_search_is_rolled_back_and_the_others_still_run(self):
        from adapters.queue.tasks import match_saved_search_new_matches

        session_local, session = _session_with(
            [(SEARCH_A, {}, ENABLED_AT), (SEARCH_B, {}, ENABLED_AT)]
        )
        hold = {"held": 0, "oldest_held_hours": None, "held_overdue": 0}
        with patch("adapters.queue.tasks.get_config", return_value=_cfg()), patch(
            "adapters.queue.tasks.SessionLocal", session_local
        ), patch(
            "core.saved_search_alerts.record_new_matches",
            side_effect=[RuntimeError("boom"), 4],
        ) as record, patch("core.saved_search_alerts.hold_report", return_value=hold):
            result = match_saved_search_new_matches.run()

        assert record.call_count == 2
        assert result["errors"] == 1
        assert result["matched"] == 4
        assert result["status"] == "ok"
        session.rollback.assert_called_once()
        assert session.commit.call_count == 1

    def test_no_enabled_search_means_no_hold_report(self):
        from adapters.queue.tasks import match_saved_search_new_matches

        session_local, _session = _session_with([])
        with patch("adapters.queue.tasks.get_config", return_value=_cfg()), patch(
            "adapters.queue.tasks.SessionLocal", session_local
        ), patch("core.saved_search_alerts.hold_report") as report:
            result = match_saved_search_new_matches.run()

        report.assert_not_called()
        assert result["searches"] == 0
        assert result["held"] == 0

    def test_long_enabled_search_keeps_its_enable_moment_as_the_floor(self):
        from adapters.queue.tasks import match_saved_search_new_matches

        long_ago = datetime(2026, 1, 1, 12, 0)  # far more than hold_warning_hours
        session_local, _session = _session_with([(SEARCH_A, {}, long_ago)])
        hold = {"held": 0, "oldest_held_hours": None, "held_overdue": 0}
        with patch("adapters.queue.tasks.get_config", return_value=_cfg()), patch(
            "adapters.queue.tasks.SessionLocal", session_local
        ), patch("adapters.queue.tasks._utcnow_naive", return_value=NOW), patch(
            "core.saved_search_alerts.record_new_matches", return_value=0
        ) as record, patch("core.saved_search_alerts.hold_report", return_value=hold) as report:
            match_saved_search_new_matches.run()

        assert record.call_args.kwargs["enabled_at"] == long_ago
        assert report.call_args.kwargs["floor"] == long_ago

    def test_matches_held_past_the_warning_age_are_logged_as_a_warning(self):
        from adapters.queue.tasks import match_saved_search_new_matches

        session_local, _session = _session_with([(SEARCH_A, {}, ENABLED_AT)])
        hold = {"held": 2, "oldest_held_hours": 190.0, "held_overdue": 2}
        with patch("adapters.queue.tasks.get_config", return_value=_cfg()), patch(
            "adapters.queue.tasks.SessionLocal", session_local
        ), patch("core.saved_search_alerts.record_new_matches", return_value=0), patch(
            "core.saved_search_alerts.hold_report", return_value=hold
        ), patch("adapters.queue.tasks.logger") as logger:
            result = match_saved_search_new_matches.run()

        assert result["held_overdue"] == 2
        events = [call.args[0] for call in logger.warning.call_args_list]
        assert "saved_search_new_match_held_overdue" in events


def _pending(*ids):
    return [{"id": pid, "public_id": i, "title": "Imóvel " + pid} for i, pid in enumerate(ids, 1)]


def _run_sender(
    rows, *, pending, cfg=None, now=NOW, held=0, locked=None, mark_error=None, release_error=None
):
    from adapters.queue.tasks import send_saved_search_new_match_alerts

    session_local, session = _session_with(rows, locked)
    with patch("adapters.queue.tasks.get_config", return_value=cfg or _cfg()), patch(
        "adapters.queue.tasks.SessionLocal", session_local
    ), patch("adapters.queue.tasks._utcnow_naive", return_value=now), patch(
        "core.saved_search_alerts.withdraw_stale", return_value=0
    ) as withdraw, patch(
        "core.saved_search_alerts.collect_pending", return_value=pending
    ) as collect, patch(
        "core.saved_search_alerts.hold_report",
        return_value={"held": held, "oldest_held_hours": None, "held_overdue": 0},
    ) as report, patch(
        "core.saved_search_alerts.mark_sent", return_value=len(pending), side_effect=mark_error
    ) as mark, patch("core.saved_search_alerts.claim_window") as claim, patch(
        "core.saved_search_alerts.release_window", side_effect=release_error
    ) as release:
        result = send_saved_search_new_match_alerts.run()
    return result, SimpleNamespace(
        session=session,
        withdraw=withdraw,
        collect=collect,
        mark=mark,
        report=report,
        claim=claim,
        release=release,
    )


@pytest.mark.unit
class TestSenderTask:
    ROW = (SEARCH_A, "Savassi 2q", {"listing_type": "rent"}, True, ENABLED_AT, None)

    def test_master_switch_off_touches_nothing(self, registry):
        result, calls = _run_sender([self.ROW], pending=_pending("p1"), cfg=_cfg(enabled=False))

        assert result["status"] == "skipped"
        calls.withdraw.assert_not_called()
        assert registry["email"].batches == []

    def test_one_email_through_the_email_channel_only_and_rows_marked(self, registry):
        result, calls = _run_sender([self.ROW], pending=_pending("p1", "p2"), held=3)

        assert result == {
            "status": "ok",
            "searches_due": 1,
            "emails_sent": 1,
            "properties_alerted": 2,
            "withdrawn": 0,
            "errors": 0,
        }
        assert len(registry["email"].batches) == 1
        batch = registry["email"].batches[0]
        assert batch.principal_id == "default"
        assert batch.search_id == SEARCH_A
        assert batch.search_name == "Savassi 2q"
        assert batch.property_ids == ["p1", "p2"]
        assert batch.subject == "2 imóveis novos na busca “Savassi 2q”"
        assert "Imóvel p1" in batch.body and "em análise" in batch.body
        for channel in ("log", "redis"):
            assert registry[channel].batches == []
            assert registry[channel].other_calls == 0
        calls.mark.assert_called_once_with(
            calls.session, SEARCH_A, ["p1", "p2"], NOW, date(2026, 10, 8)
        )

    def test_held_line_counts_from_the_enable_moment_however_long_ago(self, registry):
        # Enabled far longer ago than hold_warning_hours: the floor is still
        # the enable moment, never "now minus some age".
        long_ago = datetime(2026, 1, 1, 12, 0)
        row = (SEARCH_A, "Savassi 2q", {}, True, long_ago, None)

        _result, calls = _run_sender([row], pending=_pending("p1"), held=1)

        calls.report.assert_called_once()
        assert calls.report.call_args.kwargs["floor"] == long_ago

    def test_over_the_limit_only_what_was_shown_is_marked_sent(self, registry):
        result, calls = _run_sender(
            [self.ROW], pending=_pending("p1", "p2", "p3"), cfg=_cfg(max_items=2)
        )

        batch = registry["email"].batches[0]
        assert batch.property_ids == ["p1", "p2"]
        assert batch.subject == "2 imóveis novos na busca “Savassi 2q”"
        assert "Imóvel p3" not in batch.body
        assert "+1 nesta busca chegam no próximo aviso." in batch.body
        assert result["properties_alerted"] == 2
        calls.mark.assert_called_once_with(
            calls.session, SEARCH_A, ["p1", "p2"], NOW, date(2026, 10, 8)
        )

    def test_a_search_another_run_is_sending_is_skipped(self, registry):
        result, calls = _run_sender([self.ROW], pending=_pending("p1"), locked=[None])

        assert result["searches_due"] == 0
        assert result["errors"] == 0
        calls.collect.assert_not_called()
        calls.mark.assert_not_called()
        assert registry["email"].batches == []

    def test_state_read_under_the_lock_wins_over_the_first_read(self, registry):
        # Switched off (or already stamped by another run) after the task
        # loaded its searches: nothing is sent.
        switched_off = [(False, ENABLED_AT, None)]
        stamped = [(True, ENABLED_AT, date(2026, 10, 8))]

        for locked in (switched_off, stamped):
            result, calls = _run_sender([self.ROW], pending=_pending("p1"), locked=locked)
            assert result["searches_due"] == 0
            calls.collect.assert_not_called()
        assert registry["email"].batches == []

    def test_search_type_base_url_and_locale_reach_the_email(self, registry):
        # Values that differ from the renderer's defaults: dropping any of the
        # three arguments at the call site changes the body asserted here.
        row = (SEARCH_A, "Casas", {"listing_type": "sale"}, True, ENABLED_AT, None)
        dual = {
            "id": "p1",
            "public_id": 42,
            "title": "Casa Lourdes",
            "listings": [
                {"listing_type": "rent", "price": 3000.0},
                {"listing_type": "sale", "price": 500000.0},
            ],
            "primary_listing": {"listing_type": "rent"},
            "price_per_m2_percentile_rent": 0.9,
            "price_per_m2_percentile_sale": 0.2,
        }

        _result, _calls = _run_sender(
            [row], pending=[dual], cfg=_cfg(app_base_url="http://imoveis.test", locale="en")
        )

        batch = registry["email"].batches[0]
        assert batch.subject == "1 new home for “Casas”"
        assert "R$ 500,000" in batch.body
        assert "3,000" not in batch.body
        assert "among the 20% cheapest in the neighbourhood" in batch.body
        assert "http://imoveis.test/properties/42" in batch.body

    def test_notifier_failure_leaves_the_rows_pending_and_does_not_raise(self, registry):
        registry["email"].fail = True

        result, calls = _run_sender([self.ROW], pending=_pending("p1"))

        assert result["errors"] == 1
        assert result["emails_sent"] == 0
        assert result["properties_alerted"] == 0
        calls.mark.assert_not_called()

    def test_the_day_is_claimed_and_committed_before_the_email_leaves(self, registry):
        # The search's row lock ends with that commit: nothing that writes the
        # search (PATCH, DELETE) waits for the mail server.
        at_send = {}
        session_local, session = _session_with([self.ROW])

        def sending(batch):
            at_send["claimed"] = claim.call_args
            at_send["commits"] = session.commit.call_count
            at_send["rollbacks"] = session.rollback.call_count

        registry["email"].send_new_matches = sending
        from adapters.queue.tasks import send_saved_search_new_match_alerts

        with patch("adapters.queue.tasks.get_config", return_value=_cfg()), patch(
            "adapters.queue.tasks.SessionLocal", session_local
        ), patch("adapters.queue.tasks._utcnow_naive", return_value=NOW), patch(
            "core.saved_search_alerts.withdraw_stale", return_value=0
        ), patch(
            "core.saved_search_alerts.collect_pending", return_value=_pending("p1")
        ), patch(
            "core.saved_search_alerts.hold_report",
            return_value={"held": 0, "oldest_held_hours": None, "held_overdue": 0},
        ), patch("core.saved_search_alerts.mark_sent", return_value=1), patch(
            "core.saved_search_alerts.claim_window"
        ) as claim, patch("core.saved_search_alerts.release_window") as release:
            result = send_saved_search_new_match_alerts.run()

        assert result["emails_sent"] == 1
        assert at_send["claimed"].args == (session, SEARCH_A, date(2026, 10, 8))
        # withdraw + claim are committed; the read for the held line is ended.
        assert at_send["commits"] == 2
        assert at_send["rollbacks"] == 1
        release.assert_not_called()

    def test_a_failed_send_gives_the_day_back_as_it_was(self, registry):
        registry["email"].fail = True
        yesterday = date(2026, 10, 7)
        row = (*self.ROW[:5], yesterday)

        result, calls = _run_sender([row], pending=_pending("p1"))

        assert result["emails_sent"] == 0
        calls.claim.assert_called_once_with(calls.session, SEARCH_A, date(2026, 10, 8))
        calls.release.assert_called_once_with(
            calls.session, SEARCH_A, date(2026, 10, 8), yesterday
        )

    def test_nothing_is_claimed_when_there_is_nothing_to_send(self, registry, monkeypatch):
        _result, calls = _run_sender([self.ROW], pending=[])
        calls.claim.assert_not_called()
        calls.release.assert_not_called()

        monkeypatch.setattr("adapters.notify._registry", [("log", _FakeNotifier())])
        _result, calls = _run_sender([self.ROW], pending=_pending("p1"))
        calls.claim.assert_not_called()
        calls.release.assert_not_called()

    def test_delivered_but_not_marked_keeps_the_day_claimed(self, registry):
        # The email left. Giving the day back would send it again every hour
        # while the database write keeps failing; kept, it goes again once,
        # the next day.
        result, calls = _run_sender(
            [self.ROW], pending=_pending("p1"), mark_error=RuntimeError("db gone")
        )

        assert len(registry["email"].batches) == 1
        assert result["errors"] == 1
        assert result["emails_sent"] == 0
        calls.release.assert_not_called()

    def test_a_release_that_fails_is_counted_and_does_not_raise(self, registry):
        registry["email"].fail = True

        result, calls = _run_sender(
            [self.ROW], pending=_pending("p1"), release_error=RuntimeError("db gone")
        )

        calls.release.assert_called_once()
        assert result["errors"] == 2  # the send and the release
        assert result["emails_sent"] == 0

    def test_no_email_channel_sends_nothing_and_says_why(self, monkeypatch):
        log_only = _FakeNotifier()
        monkeypatch.setattr("adapters.notify._registry", [("log", log_only)])

        result, calls = _run_sender([self.ROW], pending=_pending("p1"))

        assert result["status"] == "no_email_channel"
        assert result["emails_sent"] == 0
        assert log_only.batches == []
        calls.mark.assert_not_called()

    def test_nothing_pending_leaves_the_window_open(self, registry):
        result, calls = _run_sender([self.ROW], pending=[])

        assert result["searches_due"] == 1
        assert result["emails_sent"] == 0
        assert registry["email"].batches == []
        calls.mark.assert_not_called()

    def test_already_sent_today_is_not_due(self, registry):
        row = (*self.ROW[:5], date(2026, 10, 8))

        result, calls = _run_sender([row], pending=_pending("p1"))

        assert result["searches_due"] == 0
        calls.collect.assert_not_called()
        assert registry["email"].batches == []

    def test_before_the_window_hour_is_not_due(self, registry):
        result, calls = _run_sender(
            [self.ROW], pending=_pending("p1"), now=datetime(2026, 10, 8, 9, 0)
        )

        assert result["searches_due"] == 0
        calls.collect.assert_not_called()

    def test_disabled_search_is_withdrawn_from_but_never_emailed(self, registry):
        row = (SEARCH_A, "Off", {}, False, ENABLED_AT, None)

        result, calls = _run_sender([row], pending=_pending("p1"))

        calls.withdraw.assert_called_once_with(calls.session, search_id=SEARCH_A)
        calls.collect.assert_not_called()
        assert result["searches_due"] == 0
        assert registry["email"].batches == []

    def test_a_search_that_blows_up_does_not_stop_the_next_one(self, registry):
        from adapters.queue.tasks import send_saved_search_new_match_alerts

        other = (SEARCH_B, "Outra", {}, True, ENABLED_AT, None)
        session_local, session = _session_with([self.ROW, other])
        with patch("adapters.queue.tasks.get_config", return_value=_cfg()), patch(
            "adapters.queue.tasks.SessionLocal", session_local
        ), patch("adapters.queue.tasks._utcnow_naive", return_value=NOW), patch(
            "core.saved_search_alerts.withdraw_stale", return_value=0
        ), patch(
            "core.saved_search_alerts.collect_pending",
            side_effect=[RuntimeError("db"), _pending("p9")],
        ), patch(
            "core.saved_search_alerts.hold_report",
            return_value={"held": 0, "oldest_held_hours": None, "held_overdue": 0},
        ), patch("core.saved_search_alerts.mark_sent", return_value=1):
            result = send_saved_search_new_match_alerts.run()

        assert result["errors"] == 1
        assert result["emails_sent"] == 1
        assert [b.search_id for b in registry["email"].batches] == [SEARCH_B]
        # Every search ends its transaction, failed or not (releases the row
        # lock); the one that sent also ended its read before the send.
        assert session.rollback.call_count == 3


@pytest.mark.unit
class TestDigestTaskPassesTheOwner:
    def test_weekly_digest_asks_to_leave_out_what_was_already_alerted(self):
        from adapters.queue.tasks import send_top_deals_digest

        cfg = _cfg()
        cfg.alerts.top_deals = SimpleNamespace(
            enabled=True,
            lookback_hours=168,
            min_combined_score=0.0,
            limit=10,
            score_target="primary",
        )
        session_local, _session = _session_with([])
        with patch("adapters.queue.tasks.get_config", return_value=cfg), patch(
            "adapters.queue.tasks.SessionLocal", session_local
        ), patch("core.top_deals_digest.select_top_deals", return_value=[]) as select:
            result = send_top_deals_digest.run()

        assert result == {"status": "empty", "sent": 0}
        assert select.call_args.kwargs["alerted_owner"] == "default"
