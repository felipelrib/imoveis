"""Integration: saved-search new-match detection on Postgres (v0.14-s1.9, FR-32).

Every row is seeded under one throwaway platform and every saved search
filters on it, so the two beat tasks - which look at all searches of the
principal - only ever touch this module's Properties. The tasks run in
process with a fixed clock; the email channel of the notifier registry is a
recorder. No mail server is contacted.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from adapters.notify.base import Notifier, SavedSearchNewMatches
from infra.config import get_config

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("DATABASE_URL"),
        reason="DATABASE_URL not set",
    ),
]

_TEST_API_KEY = "new-match-test-api-key"
# 12:00 in Sao Paulo: past the 07:00 window of the committed config.
CLOCK = datetime(2026, 10, 8, 15, 0, 0)
ENABLED_AT = CLOCK - timedelta(hours=2)
NEW = CLOCK - timedelta(hours=1)  # created after the search was enabled
OLD = CLOCK - timedelta(hours=10)  # existed before it
VERDICT = "Bom negócio para a região."


def _db_ready() -> bool:
    try:
        from infra.db import SessionLocal

        with SessionLocal() as session:
            session.execute(text("SELECT status FROM saved_search_new_matches LIMIT 0"))
            return True
    except Exception:
        return False


class _Recorder(Notifier):
    def __init__(self) -> None:
        self.fail = False
        self.during = None  # called while the email is "being sent"
        self.batches: list[SavedSearchNewMatches] = []
        self.other_calls = 0

    def send(self, alert) -> None:
        self.other_calls += 1

    def send_digest(self, digest) -> None:
        self.other_calls += 1

    def send_new_matches(self, batch: SavedSearchNewMatches) -> None:
        if self.during is not None:
            self.during()
        if self.fail:
            raise RuntimeError("smtp down")
        self.batches.append(batch)


class _World:
    """Seeding and reading helpers bound to one throwaway platform."""

    def __init__(self, owner: str) -> None:
        self.tag = uuid.uuid4().hex[:8]
        self.platform = "test-s19-" + self.tag
        self.owner = owner
        self.props: dict[str, str] = {}
        self.searches: dict[str, str] = {}

    # -- seeding ---------------------------------------------------------

    def add_property(
        self,
        label: str,
        *,
        first_seen: datetime = NEW,
        rent: float | None = 3000.0,
        sale: float | None = None,
        bedrooms: int = 2,
        parking: int = 0,
        neighborhood: str = "Savassi",
        city: str = "Belo Horizonte",
        kind: str = "apartamento",
        furnished: bool = False,
        pets: bool | None = None,
        amenities: list[str] | None = None,
        active: bool = True,
        titled: bool = True,
    ) -> str:
        from infra.db import SessionLocal

        prop_id = str(uuid.uuid4())
        props_json = {
            "available_for_rent": rent is not None,
            "available_for_sale": sale is not None,
            "neighborhood": neighborhood,
            "city": city,
            "type": kind,
            "isFurnished": furnished,
        }
        if amenities is not None:
            props_json["amenities"] = amenities
        with SessionLocal() as session:
            session.execute(
                text(
                    "INSERT INTO properties (id, platform, platform_id, title, description, "
                    "price, area_m2, bedrooms, parking, active, first_seen, props_json) "
                    "VALUES (CAST(:id AS uuid), :platform, :pid, :title, 'teste s1.9', "
                    ":price, 80, :bedrooms, :parking, :active, :first_seen, "
                    "CAST(:props AS json))"
                ),
                {
                    "id": prop_id,
                    "platform": self.platform,
                    "pid": self.platform + "-" + label,
                    "title": "s1.9 " + label if titled else None,
                    "price": rent if rent is not None else sale,
                    "bedrooms": bedrooms,
                    "parking": parking,
                    "active": active,
                    "first_seen": first_seen,
                    "props": json.dumps(props_json),
                },
            )
            session.commit()
        self.props[label] = prop_id
        for listing_type, price in (("rent", rent), ("sale", sale)):
            if price is not None:
                self.add_listing(label, listing_type, price, pets=pets)
        return prop_id

    def add_listing(
        self, label: str, listing_type: str, price: float, *, pets: bool | None = None
    ) -> None:
        from infra.db import SessionLocal

        with SessionLocal() as session:
            session.execute(
                text(
                    "INSERT INTO property_listings (id, property_id, platform, "
                    "platform_listing_id, listing_type, price, currency, url, active, "
                    "accepts_pets) "
                    "VALUES (CAST(:lid AS uuid), CAST(:pid AS uuid), :platform, :plid, :lt, "
                    ":price, 'BRL', :url, true, :pets)"
                ),
                {
                    "lid": str(uuid.uuid4()),
                    "pid": self.props[label],
                    "platform": self.platform,
                    "plid": self.platform + "-" + label + "-" + listing_type + "-" + uuid.uuid4().hex[:6],
                    "lt": listing_type,
                    "price": price,
                    "url": "https://example.test/" + self.platform + "/" + label,
                    "pets": pets,
                },
            )
            session.commit()

    def score(
        self,
        label: str,
        *,
        verdict: str | None = VERDICT,
        evaluated: bool = True,
        pct_rent: float | None = None,
        pct_sale: float | None = None,
        combined: float = 0.5,
    ) -> None:
        """Store what enrichment would: the verdict and the percentile stamp."""
        from infra.db import SessionLocal

        meta = {} if verdict is None else {"deal_verdict": {"verdict": verdict}}
        with SessionLocal() as session:
            session.execute(
                text("DELETE FROM metrics_scoring WHERE property_id = CAST(:pid AS uuid)"),
                {"pid": self.props[label]},
            )
            session.execute(
                text(
                    "INSERT INTO metrics_scoring (property_id, combined_score, "
                    "price_per_m2_percentile_rent, price_per_m2_percentile_sale, "
                    "percentile_evaluated_at, meta) "
                    "VALUES (CAST(:pid AS uuid), :combined, :pct_rent, :pct_sale, "
                    ":evaluated_at, CAST(:meta AS json))"
                ),
                {
                    "pid": self.props[label],
                    "combined": combined,
                    "pct_rent": pct_rent,
                    "pct_sale": pct_sale,
                    "evaluated_at": CLOCK - timedelta(minutes=30) if evaluated else None,
                    "meta": json.dumps(meta),
                },
            )
            session.commit()

    def add_search(
        self,
        label: str,
        filters: dict | None = None,
        *,
        notify: bool = True,
        enabled_at: datetime | None = ENABLED_AT,
        owner: str | None = "__principal__",
        scoped: bool = True,
    ) -> str:
        from infra.db import SessionLocal

        blob = dict(filters or {})
        if scoped:
            blob.setdefault("platform", self.platform)
        search_id = str(uuid.uuid4())
        with SessionLocal() as session:
            session.execute(
                text(
                    "INSERT INTO saved_searches (id, name, filters, owner, created_at, "
                    "notify_new_matches, notify_enabled_at) "
                    "VALUES (CAST(:id AS uuid), :name, CAST(:filters AS jsonb), :owner, "
                    ":created_at, :notify, :enabled_at)"
                ),
                {
                    "id": search_id,
                    "name": "s1.9 " + self.tag + " " + label,
                    "filters": json.dumps(blob),
                    "owner": self.owner if owner == "__principal__" else owner,
                    "created_at": CLOCK - timedelta(days=1),
                    "notify": notify,
                    "enabled_at": enabled_at,
                },
            )
            session.commit()
        self.searches[label] = search_id
        return search_id

    def execute(self, sql: str, params: dict | None = None) -> None:
        from infra.db import SessionLocal

        with SessionLocal() as session:
            session.execute(text(sql), params or {})
            session.commit()

    # -- reading ---------------------------------------------------------

    def matches(self, search_label: str) -> dict[str, str]:
        """``{property label: status}`` recorded for a search."""
        from infra.db import SessionLocal

        by_id = {pid: label for label, pid in self.props.items()}
        with SessionLocal() as session:
            rows = session.execute(
                text(
                    "SELECT property_id, status FROM saved_search_new_matches "
                    "WHERE saved_search_id = CAST(:sid AS uuid)"
                ),
                {"sid": self.searches[search_label]},
            ).fetchall()
        return {by_id[str(row[0])]: row[1] for row in rows}

    def search_row(self, search_label: str) -> dict:
        from infra.db import SessionLocal

        with SessionLocal() as session:
            row = session.execute(
                text(
                    "SELECT notify_new_matches, notify_enabled_at, min_price_drop, "
                    "new_match_last_window_on FROM saved_searches WHERE id = CAST(:sid AS uuid)"
                ),
                {"sid": self.searches[search_label]},
            ).mappings().one()
        return dict(row)

    def labels(self, property_ids) -> list[str]:
        by_id = {pid: label for label, pid in self.props.items()}
        return sorted(by_id[pid] for pid in property_ids if pid in by_id)

    # -- cleanup ---------------------------------------------------------

    def cleanup(self) -> None:
        from infra.db import SessionLocal

        with SessionLocal() as session:
            session.execute(
                text(
                    "DELETE FROM saved_search_new_matches WHERE property_id IN "
                    "(SELECT id FROM properties WHERE platform = :platform)"
                ),
                {"platform": self.platform},
            )
            session.execute(
                text("DELETE FROM saved_searches WHERE name LIKE :name"),
                {"name": "s1.9 " + self.tag + "%"},
            )
            for table, column in (
                ("metrics_scoring", "property_id"),
                ("property_listings", "property_id"),
                ("properties", "id"),
            ):
                # table / column come from the literal tuple above.
                session.execute(
                    text(
                        "DELETE FROM " + table + " WHERE " + column + " IN "
                        "(SELECT id FROM properties WHERE platform = :platform)"
                    ),
                    {"platform": self.platform},
                )
            session.commit()


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch):
    if not _db_ready():
        pytest.skip("Postgres saved_search_new_matches table not available")
    monkeypatch.setenv("API_KEY", _TEST_API_KEY)
    monkeypatch.setenv("JWT_SECRET", "new-match-test-jwt-secret")
    get_config.cache_clear()
    instance = _World(get_config().auth.principal_id)
    yield instance
    instance.cleanup()
    get_config.cache_clear()


@pytest.fixture
def mailbox(monkeypatch: pytest.MonkeyPatch):
    """The notifier registry with a recorder on every channel type."""
    recorders = {"log": _Recorder(), "redis": _Recorder(), "email": _Recorder()}
    monkeypatch.setattr("adapters.notify._registry", list(recorders.items()))
    return recorders


@pytest.fixture
def client(world):
    from api.main import app

    return TestClient(app, raise_server_exceptions=True)


_HEADERS = {"X-API-Key": _TEST_API_KEY}


def _match(now: datetime = CLOCK) -> dict:
    from adapters.queue.tasks import match_saved_search_new_matches

    with patch("adapters.queue.tasks._utcnow_naive", return_value=now):
        return match_saved_search_new_matches.run()


def _send(now: datetime = CLOCK) -> dict:
    from adapters.queue.tasks import send_saved_search_new_match_alerts

    with patch("adapters.queue.tasks._utcnow_naive", return_value=now):
        return send_saved_search_new_match_alerts.run()


# ---------------------------------------------------------------------------
# I/O matrix
# ---------------------------------------------------------------------------


def test_new_decidable_match_is_recorded_then_emailed_once(world, mailbox):
    world.add_property("a")
    world.score("a", pct_rent=0.2)
    world.add_search("s", {"listing_type": "rent", "max_price": 3500})

    matched = _match()
    assert matched["status"] == "ok"
    assert matched["matched"] == 1
    assert world.matches("s") == {"a": "pending"}

    sent = _send()
    assert sent["emails_sent"] == 1
    assert sent["properties_alerted"] == 1
    assert sent["errors"] == 0
    assert world.matches("s") == {"a": "sent"}
    assert world.search_row("s")["new_match_last_window_on"] == date(2026, 10, 8)

    # Exactly one email, on the email channel and no other, for the principal.
    assert len(mailbox["email"].batches) == 1
    batch = mailbox["email"].batches[0]
    assert batch.principal_id == world.owner
    assert batch.search_id == world.searches["s"]
    assert batch.property_ids == [world.props["a"]]
    assert "s1.9 a" in batch.body
    assert VERDICT in batch.body
    assert "entre os 20% mais baratos do bairro" in batch.body
    assert "R$ 3.000/mês" in batch.body
    for channel in ("log", "redis"):
        assert mailbox[channel].batches == []
        assert mailbox[channel].other_calls == 0


def test_suppressed_percentile_is_decidable_but_fails_a_percentile_filter(world, mailbox):
    world.add_property("a")
    world.score("a", pct_rent=None)  # evaluated, cohort too small
    world.add_search("plain", {"listing_type": "rent"})
    world.add_search("cheap", {"listing_type": "rent", "max_price_per_m2_percentile": 0.5})

    _match()

    assert world.matches("plain") == {"a": "pending"}
    assert world.matches("cheap") == {}
    _send()
    body = mailbox["email"].batches[0].body
    assert "mais baratos" not in body


def test_undecidable_property_is_held_then_matched_once_decidable(world, mailbox):
    world.add_property("no_row")
    world.add_property("no_verdict")
    world.score("no_verdict", verdict=None)
    world.add_property("blank_verdict")
    world.score("blank_verdict", verdict="   ")
    world.add_property("no_stamp")
    world.score("no_stamp", evaluated=False)
    world.add_search("s", {})

    first = _match()
    assert first["matched"] == 0
    assert first["held"] >= 4
    assert first["oldest_held_hours"] is not None
    assert world.matches("s") == {}
    # Nothing to say yet: no email, and the day is not used up.
    assert _send()["emails_sent"] == 0
    assert world.search_row("s")["new_match_last_window_on"] is None

    for label in ("no_row", "no_verdict", "blank_verdict", "no_stamp"):
        world.score(label)
    second = _match(CLOCK + timedelta(minutes=15))
    assert second["matched"] == 4
    assert second["held"] <= first["held"] - 4
    assert set(world.matches("s")) == {"no_row", "no_verdict", "blank_verdict", "no_stamp"}

    assert _send(CLOCK + timedelta(minutes=30))["properties_alerted"] == 4
    assert len(mailbox["email"].batches) == 1


def test_hold_report_counts_only_new_active_undecidable_properties(world):
    from core.saved_search_alerts import hold_report
    from infra.db import SessionLocal

    def report() -> dict:
        with SessionLocal() as session:
            return hold_report(session, floor=ENABLED_AT, now=CLOCK, overdue_after_hours=168)

    before = report()
    world.add_property("held")
    world.add_property("decidable")
    world.score("decidable")
    world.add_property("before_floor", first_seen=OLD)
    world.add_property("inactive", active=False)
    after = report()

    assert after["held"] == before["held"] + 1
    assert after["held_overdue"] == before["held_overdue"]
    assert after["oldest_held_hours"] >= 1.0


def test_held_past_the_warning_age_is_reported_overdue_and_alerted_once_decidable(
    world, mailbox
):
    """Held, never dropped: there is no age at which a hold ends unalerted."""
    world.add_search("s", {}, enabled_at=CLOCK - timedelta(hours=1000))
    # Undecidable for far longer than alerts.new_match.hold_warning_hours (168).
    world.add_property("long_held", first_seen=CLOCK - timedelta(hours=900))
    world.add_property("held", first_seen=CLOCK - timedelta(hours=10))

    first = _match()
    assert first["matched"] == 0
    assert first["held"] >= 2
    assert first["held_overdue"] >= 1
    assert first["oldest_held_hours"] >= 900
    assert world.matches("s") == {}

    world.score("long_held")
    world.score("held")
    later = _match(CLOCK + timedelta(minutes=15))
    assert later["matched"] == 2
    assert world.matches("s") == {"long_held": "pending", "held": "pending"}

    sent = _send(CLOCK + timedelta(minutes=30))
    assert sent["properties_alerted"] == 2
    assert world.matches("s") == {"long_held": "sent", "held": "sent"}
    assert len(mailbox["email"].batches) == 1


def test_decidable_property_no_run_saw_in_time_is_still_matched(world):
    # The matcher was down (or the master switch off) for weeks: what became
    # decidable meanwhile is recorded by the first run that looks.
    world.add_search("s", {}, enabled_at=CLOCK - timedelta(hours=1000))
    world.add_property("missed", first_seen=CLOCK - timedelta(hours=700))
    world.score("missed")

    assert _match()["matched"] == 1
    assert world.matches("s") == {"missed": "pending"}


def test_property_that_existed_before_enabling_never_fires(world, mailbox):
    world.add_property("old", first_seen=OLD)
    world.score("old")
    world.add_property("at_the_moment", first_seen=ENABLED_AT)
    world.score("at_the_moment")
    world.add_search("s", {})

    _match()

    assert world.matches("s") == {"at_the_moment": "pending"}


def test_search_without_the_flag_writes_nothing_and_notifies_nobody(world, mailbox):
    world.add_property("a")
    world.score("a")
    world.add_search("never_enabled", {}, notify=False, enabled_at=None)
    world.add_search("switched_off", {}, notify=False, enabled_at=ENABLED_AT)
    world.add_search("flag_without_stamp", {}, notify=True, enabled_at=None)

    matched = _match()
    sent = _send()

    assert matched["searches"] == 0
    assert matched["matched"] == 0
    assert sent["emails_sent"] == 0
    for label in ("never_enabled", "switched_off", "flag_without_stamp"):
        assert world.matches(label) == {}
    for recorder in mailbox.values():
        assert recorder.batches == []
        assert recorder.other_calls == 0


def test_database_default_keeps_existing_searches_off(world):
    search_id = str(uuid.uuid4())
    world.execute(
        "INSERT INTO saved_searches (id, name, filters, owner) "
        "VALUES (CAST(:id AS uuid), :name, CAST('{}' AS jsonb), :owner)",
        {"id": search_id, "name": "s1.9 " + world.tag + " legacy", "owner": world.owner},
    )
    world.searches["legacy"] = search_id

    row = world.search_row("legacy")
    assert row["notify_new_matches"] is False
    assert row["notify_enabled_at"] is None
    assert row["min_price_drop"] is None
    assert row["new_match_last_window_on"] is None


def test_search_disabled_before_the_window_has_its_pending_rows_withdrawn(world, mailbox):
    world.add_property("a")
    world.score("a")
    world.add_search("s", {})
    _match()
    assert world.matches("s") == {"a": "pending"}

    world.execute(
        "UPDATE saved_searches SET notify_new_matches = false WHERE id = CAST(:sid AS uuid)",
        {"sid": world.searches["s"]},
    )
    sent = _send()

    assert sent["withdrawn"] == 1
    assert sent["emails_sent"] == 0
    assert world.matches("s") == {"a": "withdrawn"}
    assert mailbox["email"].batches == []


def test_rows_matched_under_an_earlier_enabling_are_withdrawn(world, mailbox):
    world.add_property("a")
    world.score("a")
    world.add_search("s", {})
    _match()

    # Off and on again after the match: the floor starts over.
    world.execute(
        "UPDATE saved_searches SET notify_enabled_at = :at WHERE id = CAST(:sid AS uuid)",
        {"sid": world.searches["s"], "at": CLOCK + timedelta(minutes=5)},
    )
    sent = _send(CLOCK + timedelta(minutes=10))

    assert sent["withdrawn"] == 1
    assert world.matches("s") == {"a": "withdrawn"}
    assert mailbox["email"].batches == []
    # And the pair stays unique: it is not matched a second time.
    assert _match(CLOCK + timedelta(minutes=20))["matched"] == 0


def test_outage_recovery_produces_no_match(world, mailbox):
    world.add_property("reactivated", first_seen=OLD)
    world.score("reactivated")
    world.add_property("gains_listing", first_seen=OLD, rent=None, sale=500000.0)
    world.score("gains_listing")
    world.add_search("s", {"listing_type": "rent"})

    # The platform goes away ...
    world.execute(
        "UPDATE properties SET active = false WHERE platform = :platform",
        {"platform": world.platform},
    )
    world.execute(
        "UPDATE property_listings SET active = false WHERE platform = :platform",
        {"platform": world.platform},
    )
    assert _match()["matched"] == 0

    # ... and comes back: Properties and Listings reactivate, one gains a rent Listing.
    world.execute(
        "UPDATE properties SET active = true WHERE platform = :platform",
        {"platform": world.platform},
    )
    world.execute(
        "UPDATE property_listings SET active = true, last_seen = :now WHERE platform = :platform",
        {"platform": world.platform, "now": CLOCK},
    )
    world.add_listing("gains_listing", "rent", 2800.0)
    world.execute(
        "UPDATE properties SET props_json = CAST(:props AS json) WHERE id = CAST(:pid AS uuid)",
        {
            "pid": world.props["gains_listing"],
            "props": json.dumps(
                {
                    "available_for_rent": True,
                    "available_for_sale": True,
                    "neighborhood": "Savassi",
                    "city": "Belo Horizonte",
                    "type": "apartamento",
                    "isFurnished": False,
                }
            ),
        },
    )

    assert _match(CLOCK + timedelta(minutes=15))["matched"] == 0
    assert world.matches("s") == {}
    assert _send(CLOCK + timedelta(minutes=30))["emails_sent"] == 0
    assert mailbox["email"].batches == []


def test_running_twice_keeps_one_row_and_one_email(world, mailbox):
    world.add_property("a")
    world.score("a")
    world.add_search("s", {})

    assert _match()["matched"] == 1
    assert _match()["matched"] == 0
    assert world.matches("s") == {"a": "pending"}

    assert _send()["emails_sent"] == 1
    assert _send()["emails_sent"] == 0
    assert _match(CLOCK + timedelta(minutes=15))["matched"] == 0
    assert world.matches("s") == {"a": "sent"}
    assert len(mailbox["email"].batches) == 1


def test_one_email_per_search_per_local_day(world, mailbox):
    world.add_property("a")
    world.score("a")
    world.add_search("s", {})
    _match()
    assert _send()["emails_sent"] == 1

    # A second match the same local day waits for tomorrow's window.
    world.add_property("b")
    world.score("b")
    assert _match(CLOCK + timedelta(hours=1))["matched"] == 1
    same_day = _send(CLOCK + timedelta(hours=2))
    assert same_day["emails_sent"] == 0
    assert same_day["searches_due"] == 0
    assert world.matches("s") == {"a": "sent", "b": "pending"}

    # 05:00 UTC the next day is 02:00 local: a new day, before the window hour.
    assert _send(CLOCK + timedelta(hours=14))["emails_sent"] == 0
    next_day = _send(CLOCK + timedelta(hours=24))
    assert next_day["emails_sent"] == 1
    assert world.matches("s") == {"a": "sent", "b": "sent"}
    assert world.search_row("s")["new_match_last_window_on"] == date(2026, 10, 9)
    assert [b.property_ids for b in mailbox["email"].batches] == [
        [world.props["a"]],
        [world.props["b"]],
    ]


def test_before_the_window_hour_nothing_is_sent(world, mailbox):
    world.add_property("a")
    world.score("a")
    world.add_search("s", {})
    _match()

    early = _send(datetime(2026, 10, 8, 9, 0))  # 06:00 local
    assert early["emails_sent"] == 0
    assert world.matches("s") == {"a": "pending"}

    late = _send(datetime(2026, 10, 8, 23, 0))  # a worker that was down at 07:00
    assert late["emails_sent"] == 1


def test_failed_send_leaves_rows_pending_for_the_next_tick(world, mailbox):
    world.add_property("a")
    world.score("a")
    world.add_search("s", {})
    _match()
    mailbox["email"].fail = True

    failed = _send()
    assert failed["errors"] == 1
    assert failed["emails_sent"] == 0
    assert world.matches("s") == {"a": "pending"}
    assert world.search_row("s")["new_match_last_window_on"] is None

    mailbox["email"].fail = False
    retried = _send(CLOCK + timedelta(hours=1))
    assert retried["emails_sent"] == 1
    assert world.matches("s") == {"a": "sent"}
    assert len(mailbox["email"].batches) == 1


def test_no_email_channel_sends_nothing_and_keeps_rows_pending(world, monkeypatch):
    log_only = _Recorder()
    monkeypatch.setattr("adapters.notify._registry", [("log", log_only)])
    world.add_property("a")
    world.score("a")
    world.add_search("s", {})
    _match()

    sent = _send()

    assert sent["status"] == "no_email_channel"
    assert sent["emails_sent"] == 0
    assert world.matches("s") == {"a": "pending"}
    assert world.search_row("s")["new_match_last_window_on"] is None
    assert log_only.batches == []
    assert log_only.other_calls == 0


def test_semantic_search_is_skipped(world, mailbox):
    world.add_property("a")
    world.score("a")
    world.add_search("semantic", {"q": "varanda gourmet"})

    matched = _match()

    assert matched["unsupported"] >= 1
    assert world.matches("semantic") == {}
    assert _send()["emails_sent"] == 0


def test_property_gone_before_the_window_is_withdrawn_not_emailed(world, mailbox):
    world.add_property("stays")
    world.score("stays")
    world.add_property("goes")
    world.score("goes")
    world.add_search("s", {})
    _match()
    assert world.matches("s") == {"stays": "pending", "goes": "pending"}

    world.execute(
        "UPDATE properties SET active = false WHERE id = CAST(:pid AS uuid)",
        {"pid": world.props["goes"]},
    )
    sent = _send()

    assert sent["withdrawn"] == 1
    assert sent["properties_alerted"] == 1
    assert world.matches("s") == {"stays": "sent", "goes": "withdrawn"}
    assert mailbox["email"].batches[0].property_ids == [world.props["stays"]]
    assert "s1.9 goes" not in mailbox["email"].batches[0].body


def test_searches_of_another_or_no_owner_are_ignored(world, mailbox):
    world.add_property("a")
    world.score("a")
    world.add_search("other", {}, owner="someone-else-" + world.tag)
    world.add_search("nobody", {}, owner=None)

    matched = _match()
    sent = _send()

    assert matched["matched"] == 0
    assert sent["emails_sent"] == 0
    assert world.matches("other") == {}
    assert world.matches("nobody") == {}
    assert mailbox["email"].batches == []


def test_over_the_email_limit_the_rest_stays_pending_for_the_next_day(world, mailbox):
    labels = ["p" + str(i) for i in range(23)]
    for label in labels:
        world.add_property(label)
        world.score(label)
    world.add_search("s", {})
    assert _match()["matched"] == 23

    sent = _send()

    # alerts.new_match.max_items_per_email = 20: only what the email shows is
    # marked sent; nothing is marked sent unseen.
    assert sent["properties_alerted"] == 20
    statuses = sorted(world.matches("s").values())
    assert statuses == ["pending"] * 3 + ["sent"] * 20
    first = mailbox["email"].batches[0]
    assert len(first.property_ids) == 20
    assert first.subject.startswith("20 imóveis novos")
    assert "+3 nesta busca chegam no próximo aviso." in first.body

    # Same local day: nothing more. Next day's window carries the rest.
    assert _send(CLOCK + timedelta(hours=1))["emails_sent"] == 0
    next_day = _send(CLOCK + timedelta(hours=24))
    assert next_day["properties_alerted"] == 3
    assert set(world.matches("s").values()) == {"sent"}
    second = mailbox["email"].batches[1]
    assert second.subject.startswith("3 imóveis novos")
    assert not set(first.property_ids) & set(second.property_ids)
    assert "\n+" not in second.body


def test_matches_recorded_by_one_run_leave_oldest_property_first(world, mailbox):
    """A backlog released at once shares one ``matched_at``; the Property's age decides."""
    ages = {"p" + str(i): CLOCK - timedelta(minutes=10 * (i + 1)) for i in range(8)}
    for label, first_seen in ages.items():
        world.add_property(label, first_seen=first_seen)
        world.score(label)
    world.add_search("s", {})
    assert _match()["matched"] == 8

    _send()

    oldest_first = [world.props[label] for label in sorted(ages, key=ages.get)]
    assert mailbox["email"].batches[0].property_ids == oldest_first


def test_search_being_sent_by_another_run_is_skipped_not_emailed_twice(world, mailbox):
    """Two sender runs can start together (the worker has several processes).

    The first holds the search's row lock while it claims the day; the second
    skips the search instead of emailing the same matches.
    """
    from infra.db import SessionLocal

    world.add_property("a")
    world.score("a")
    world.add_search("s", {})
    _match()

    with SessionLocal() as other_run:
        other_run.execute(
            text(
                "SELECT id FROM saved_searches WHERE id = CAST(:sid AS uuid) "
                "FOR NO KEY UPDATE"
            ),
            {"sid": world.searches["s"]},
        )
        skipped = _send()
        # The matcher's insert (a foreign-key check on the locked row) is not
        # blocked by that lock: a Property that turns up meanwhile is recorded.
        world.add_property("b")
        world.score("b")
        during = _match()
        other_run.rollback()

    assert during["errors"] == 0
    assert during["matched"] == 1
    assert skipped["emails_sent"] == 0
    assert skipped["errors"] == 0
    assert mailbox["email"].batches == []
    assert world.matches("s") == {"a": "pending", "b": "pending"}

    assert _send()["emails_sent"] == 1
    assert world.matches("s") == {"a": "sent", "b": "sent"}
    assert len(mailbox["email"].batches) == 1


def _write_search_or_fail(search_id: str) -> None:
    """Write the search row from another connection; fail fast if it is locked."""
    from infra.db import SessionLocal

    with SessionLocal() as other:
        other.execute(text("SET LOCAL lock_timeout = '2s'"))
        other.execute(
            text("UPDATE saved_searches SET name = name WHERE id = CAST(:sid AS uuid)"),
            {"sid": search_id},
        )
        other.commit()


def test_search_can_be_edited_while_its_email_is_being_sent(world, client, mailbox):
    """Regression: the sender held the search's row lock across the SMTP conversation.

    A ``PATCH`` (or ``DELETE``) of the search from the API then waited for the
    mail server, up to its timeout. The day is now claimed in a short
    transaction and the email leaves with no lock held.
    """
    world.add_property("a")
    world.score("a")
    search_id = world.add_search("s", {})
    _match()
    seen: dict = {}

    def during() -> None:
        try:
            _write_search_or_fail(search_id)
        except Exception as exc:  # the row is locked: do not hang on the API call
            seen["locked"] = repr(exc)
            return
        seen["patch"] = client.patch(
            "/saved-searches/" + search_id,
            json={"name": "s1.9 " + world.tag + " renamed"},
            headers=_HEADERS,
        ).status_code
        # A second run that starts now finds the day claimed.
        seen["second_run"] = _send()
        # And the matcher keeps recording.
        world.add_property("b")
        world.score("b")
        seen["matcher"] = _match()

    mailbox["email"].during = during
    sent = _send()

    assert "locked" not in seen, seen
    assert seen["patch"] == 200
    assert seen["second_run"]["emails_sent"] == 0
    assert seen["second_run"]["errors"] == 0
    assert seen["matcher"]["matched"] == 1
    assert sent["emails_sent"] == 1
    assert sent["errors"] == 0
    assert len(mailbox["email"].batches) == 1
    assert world.matches("s") == {"a": "sent", "b": "pending"}
    assert world.search_row("s")["new_match_last_window_on"] == date(2026, 10, 8)


def test_search_deleted_while_its_email_is_being_sent(world, client, mailbox):
    from infra.db import SessionLocal

    world.add_property("a")
    world.score("a")
    search_id = world.add_search("s", {})
    _match()
    seen: dict = {}

    def during() -> None:
        try:
            _write_search_or_fail(search_id)
        except Exception as exc:
            seen["locked"] = repr(exc)
            return
        seen["delete"] = client.delete(
            "/saved-searches/" + search_id, headers=_HEADERS
        ).status_code

    mailbox["email"].during = during
    sent = _send()

    assert "locked" not in seen, seen
    assert seen["delete"] == 200
    # The email was already on its way; the run ends without an error.
    assert sent["errors"] == 0
    assert sent["emails_sent"] == 1
    assert len(mailbox["email"].batches) == 1
    # The row outlives the search (FK SET NULL) and belongs to no search now.
    with SessionLocal() as session:
        rows = session.execute(
            text(
                "SELECT saved_search_id, status FROM saved_search_new_matches "
                "WHERE property_id = CAST(:pid AS uuid)"
            ),
            {"pid": world.props["a"]},
        ).fetchall()
    assert [(row[0], row[1]) for row in rows] == [(None, "pending")]


def test_failed_send_gives_the_day_back_as_it_was(world, mailbox):
    """A send that fails releases the claim: the stored date is the earlier one again."""
    world.add_property("a")
    world.score("a")
    world.add_search("s", {})
    world.execute(
        "UPDATE saved_searches SET new_match_last_window_on = :d WHERE id = CAST(:sid AS uuid)",
        {"d": date(2026, 10, 7), "sid": world.searches["s"]},
    )
    _match()
    during: dict = {}
    mailbox["email"].during = lambda: during.update(world.search_row("s"))
    mailbox["email"].fail = True

    failed = _send()

    # Claimed while the email was being sent, given back when it failed.
    assert during["new_match_last_window_on"] == date(2026, 10, 8)
    assert failed["errors"] == 1
    assert world.search_row("s")["new_match_last_window_on"] == date(2026, 10, 7)
    assert world.matches("s") == {"a": "pending"}

    mailbox["email"].during = None
    mailbox["email"].fail = False
    assert _send(CLOCK + timedelta(hours=1))["emails_sent"] == 1
    assert world.matches("s") == {"a": "sent"}


# ---------------------------------------------------------------------------
# Weekly digest
# ---------------------------------------------------------------------------


def test_weekly_digest_excludes_already_alerted_properties(world, mailbox):
    from core.top_deals_digest import select_top_deals
    from infra.db import SessionLocal

    for label in ("sent", "pending", "withdrawn", "pending_off", "other_owner", "never"):
        world.add_property(label)
        world.score(label, combined=0.999)
    world.add_search("on", {})
    world.add_search("off", {}, notify=False)

    def record(search: str | None, label: str, status: str, owner: str | None = None) -> None:
        world.execute(
            "INSERT INTO saved_search_new_matches (saved_search_id, property_id, owner, status) "
            "VALUES (CAST(:sid AS uuid), CAST(:pid AS uuid), :owner, :status)",
            {
                "sid": world.searches[search] if search else None,
                "pid": world.props[label],
                "owner": owner or world.owner,
                "status": status,
            },
        )

    record("on", "sent", "sent")
    record("on", "pending", "pending")
    record("on", "withdrawn", "withdrawn")
    record("off", "pending_off", "pending")
    record("on", "other_owner", "sent", owner="someone-else-" + world.tag)

    def digest(**kwargs) -> list[str]:
        with SessionLocal() as session:
            items = select_top_deals(
                session,
                lookback_hours=168,
                min_combined_score=0.99,
                limit=500,
                now=CLOCK.replace(tzinfo=timezone.utc),
                **kwargs,
            )
        return world.labels(item["id"] for item in items)

    everything = sorted(["sent", "pending", "withdrawn", "pending_off", "other_owner", "never"])
    assert digest() == everything
    assert digest(alerted_owner=world.owner) == sorted(
        ["withdrawn", "pending_off", "other_owner", "never"]
    )

    # Deleting the search keeps "already alerted" (FK SET NULL).
    world.execute(
        "DELETE FROM saved_searches WHERE id = CAST(:sid AS uuid)", {"sid": world.searches["on"]}
    )
    remaining = digest(alerted_owner=world.owner)
    assert "sent" not in remaining
    # A pending row of a deleted search will never be emailed: back in the digest.
    assert "pending" in remaining


def test_a_search_whose_statement_fails_does_not_stop_the_others(world, mailbox):
    """The per-search rollback on a real session, not a mock."""
    world.add_property("a")
    world.score("a")
    # Not a number: Postgres rejects the comparison with the listing price.
    world.add_search("broken", {"max_price": "abc"})
    world.add_search("healthy", {})

    result = _match()

    assert result["searches"] == 2
    assert result["errors"] == 1
    assert world.matches("broken") == {}
    assert world.matches("healthy") == {"a": "pending"}


def test_untitled_property_is_named_by_its_stored_type(world, mailbox):
    world.add_property("a", titled=False, kind="casa")
    world.score("a")
    world.add_search("s", {})

    _match()
    assert _send()["emails_sent"] == 1
    assert "1. Casa" in mailbox["email"].batches[0].body


def test_only_creation_on_the_persist_path_counts_as_new(world, mailbox):
    """The real dedupe path: a re-scrape updates the Property and leaves first_seen alone."""
    from core.dedupe import match_or_create_property
    from core.entities import PropertyCandidate
    from infra.db import SessionLocal

    def candidate(price: float) -> PropertyCandidate:
        return PropertyCandidate(
            platform=world.platform,
            platform_id=world.platform + "-persist",
            title="s1.9 persist " + world.tag,
            description="teste s1.9",
            price=price,
            area_m2=80.0,
            bedrooms=2,
            bathrooms=1,
            parking=0,
            location=None,
            address="Rua Teste 1, Belo Horizonte",
            image_urls=["https://example.test/" + world.tag + ".jpg"],
            props_json={"type": "apartment", "neighborhood": "Savassi", "city": "Belo Horizonte"},
            currency="BRL",
            listings=[
                {
                    "platform": world.platform,
                    "platform_listing_id": world.platform + "-persist",
                    "listing_type": "rent",
                    "price": price,
                    "currency": "BRL",
                    "url": "https://example.test/" + world.platform + "/persist",
                }
            ],
        )

    def first_seen() -> datetime:
        with SessionLocal() as session:
            return session.execute(
                text("SELECT first_seen FROM properties WHERE id = CAST(:pid AS uuid)"),
                {"pid": world.props["persist"]},
            ).scalar()

    with SessionLocal() as session:
        created = match_or_create_property(session, candidate(3000.0))
        session.commit()
    assert created.action == "created"
    world.props["persist"] = created.property_id
    created_at = first_seen()
    world.score("persist")

    world.add_search("before", {}, enabled_at=created_at - timedelta(hours=1))
    world.add_search("after", {}, enabled_at=created_at + timedelta(minutes=30))
    assert _match(created_at + timedelta(hours=1))["matched"] == 1
    assert world.matches("before") == {"persist": "pending"}

    with SessionLocal() as session:
        updated = match_or_create_property(session, candidate(3200.0))
        session.commit()
    assert updated.action == "updated"
    assert updated.property_id == created.property_id
    assert first_seen() == created_at

    assert _match(created_at + timedelta(hours=2))["matched"] == 0
    assert world.matches("after") == {}


# ---------------------------------------------------------------------------
# Parity with GET /properties
# ---------------------------------------------------------------------------

# (label, stored saved-search filters, the query parameters the SPA sends when
# that search is applied, expected new decidable matches)
_PARITY = [
    (
        "rent_cap",
        {"listing_type": "rent", "max_price": 3500, "min_bedrooms": 2, "neighborhood": "Savassi"},
        {
            "listing_type": "rent",
            "max_price": 3500,
            "price_type": "rent",
            "min_bedrooms": 2,
            "neighborhood_name": "Savassi",
        },
        ["a", "g"],
    ),
    (
        "sale_cap_both_types",
        {"listing_type": "both", "max_price": 600000, "price_type": "sale"},
        {"max_price": 600000, "price_type": "sale"},
        ["c", "d"],
    ),
    (
        "cheapest_quarter",
        {"max_price_per_m2_percentile": 0.25},
        {"max_price_per_m2_percentile": 0.25},
        ["a", "d"],
    ),
    (
        "sale_houses_scored",
        {"listing_type": "sale", "min_score": 0.6, "property_type": "house"},
        {"listing_type": "sale", "min_score": 0.6, "property_type": "house"},
        ["c"],
    ),
    (
        "furnished_in_contagem",
        {
            "city": "Contagem",
            "is_furnished": True,
            "sort_by": "price",
            "sort_dir": "asc",
            "min_price": 100,
            "max_bedrooms": 1,
        },
        {"city_name": "Contagem", "is_furnished": "true", "sort_by": "price", "sort_dir": "asc"},
        ["d"],
    ),
    ("pets", {"accepts_pets": True}, {"accepts_pets": "true"}, ["a"]),
    # A blob written through the API without ``price_type`` (the SPA always
    # stores one): the cap follows the listing type, as it does on the list.
    (
        "sale_cap_without_price_type",
        {"listing_type": "sale", "max_price": 600000},
        {"listing_type": "sale", "max_price": 600000},
        ["c", "d"],
    ),
    ("places_as_a_list", {"neighborhood": "Lourdes,Centro"}, {"neighborhood_name": "Lourdes,Centro"}, ["b", "d"]),
    ("parking", {"min_parking": 1}, {"min_parking": 1}, ["a"]),
    ("platform_only", {}, {}, ["a", "b", "c", "d", "g"]),
]
_NEW_DECIDABLE = {"a", "b", "c", "d", "g"}


def test_matcher_selects_what_the_list_endpoint_lists(world, client, mailbox):
    world.add_property("a", rent=3000.0, bedrooms=2, parking=1, pets=True)
    world.score("a", pct_rent=0.2, combined=0.8)
    world.add_property("b", rent=5000.0, bedrooms=3, neighborhood="Lourdes")
    world.score("b", pct_rent=0.6, combined=0.5)
    world.add_property("c", rent=None, sale=500000.0, bedrooms=3, kind="casa")
    world.score("c", pct_sale=0.3, combined=0.7)
    world.add_property(
        "d",
        rent=2500.0,
        sale=400000.0,
        bedrooms=1,
        neighborhood="Centro",
        city="Contagem",
        furnished=True,
    )
    world.score("d", pct_rent=0.1, pct_sale=0.9, combined=0.4)
    world.add_property("e", rent=2800.0)  # not decidable
    world.add_property("f", rent=2900.0, first_seen=OLD)  # not new
    world.score("f", pct_rent=0.2, combined=0.8)
    world.add_property("g", rent=2700.0)  # suppressed percentile
    world.score("g", pct_rent=None, combined=0.5)

    for label, saved, _params, _expected in _PARITY:
        world.add_search(label, saved)
    result = _match()
    assert result["errors"] == 0
    assert result["unsupported"] == 0

    for label, _saved, params, expected in _PARITY:
        response = client.get(
            "/properties",
            params={"page": 1, "page_size": 100, "platform": world.platform, **params},
            headers=_HEADERS,
        )
        assert response.status_code == 200, response.text
        listed = set(world.labels(p["id"] for p in response.json()["properties"]))
        matched = set(world.matches(label))
        assert matched == listed & _NEW_DECIDABLE, label
        assert sorted(matched) == expected, label
        # The list also shows what is not new or not decidable; the matcher never does.
        assert not matched & {"e", "f"}, label


def test_accepts_pets_runs_on_postgres_for_the_list_and_the_matcher(world, client, mailbox):
    """Regression: the pets predicate applied the jsonb ``?`` operator to a ``json`` column.

    ``GET /properties?accepts_pets=...`` was a 500 on Postgres and a notifying
    search with the filter failed on every matcher run. Every earlier test of
    the filter compared SQL text only.
    """
    pets_amenity = "PODE_TER_ANIMAIS_DE_ESTIMACAO"
    world.add_property("by_listing", pets=True)
    world.add_property("by_amenity", amenities=["PISCINA", pets_amenity])
    world.add_property("listing_says_no", pets=False, amenities=[])
    world.add_property("no_amenities_key")
    for label in ("by_listing", "by_amenity", "listing_says_no", "no_amenities_key"):
        world.score(label)
    world.add_search("pets", {"accepts_pets": True})

    def listed(value: str) -> list[str]:
        response = client.get(
            "/properties",
            params={"page": 1, "page_size": 100, "platform": world.platform, "accepts_pets": value},
            headers=_HEADERS,
        )
        assert response.status_code == 200, response.text
        return world.labels(p["id"] for p in response.json()["properties"])

    assert listed("true") == ["by_amenity", "by_listing"]
    # A Property with no ``amenities`` key is "not known to accept pets", not lost.
    assert listed("false") == ["listing_says_no", "no_amenities_key"]

    result = _match()
    assert result["errors"] == 0
    assert sorted(world.matches("pets")) == ["by_amenity", "by_listing"]


# ---------------------------------------------------------------------------
# Release path: enrichment makes a Property decidable, no bulk recalculation
# ---------------------------------------------------------------------------


class _VerdictClient:
    async def summarize_deal(self, **_kwargs):
        return SimpleNamespace(verdict=VERDICT, confidence=0.8, degraded=False)


def test_property_released_by_the_enrichment_write_is_matched_on_the_next_run(world, mailbox):
    from adapters.db.models import MetricsScoring
    from adapters.queue.tasks import _persist_ai_scores, _write_deal_verdict
    from infra.db import SessionLocal

    world.add_property("fresh")
    world.add_search("s", {"listing_type": "rent"})
    assert _match()["matched"] == 0
    assert world.matches("s") == {}

    # What run_enrichment does in one transaction: AI scores (which scores the
    # Property and stamps percentile_evaluated_at), then the verdict.
    with SessionLocal() as session:
        _persist_ai_scores(
            session,
            world.props["fresh"],
            0.7,
            {"visual": {"condition_score": 0.7}, "sentiment": {"sentiment_score": 0.7}},
            get_config(),
        )
        ms = session.query(MetricsScoring).filter_by(property_id=world.props["fresh"]).one()
        assert ms.percentile_evaluated_at is not None
        # The production verdict writer, with a client that answers like a model.
        asyncio.run(
            _write_deal_verdict(_VerdictClient(), session, world.props["fresh"], dict(ms.meta or {}))
        )
        session.commit()

    assert _match(CLOCK + timedelta(minutes=15))["matched"] == 1
    assert world.matches("s") == {"fresh": "pending"}
    assert _send(CLOCK + timedelta(minutes=30))["emails_sent"] == 1
    assert VERDICT in mailbox["email"].batches[0].body


# ---------------------------------------------------------------------------
# API round trip
# ---------------------------------------------------------------------------


def _created(world, client, body: dict) -> dict:
    response = client.post("/saved-searches", json=body, headers=_HEADERS)
    assert response.status_code == 201, response.text
    item = response.json()
    world.searches[body["name"]] = item["id"]
    return item


def _patched(client, search_id: str, body: dict) -> dict:
    response = client.patch("/saved-searches/" + search_id, json=body, headers=_HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def _recent(stamp: str) -> bool:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return abs((now - datetime.fromisoformat(stamp)).total_seconds()) < 300


def test_api_new_search_is_off_by_default(world, client):
    item = _created(
        world, client, {"name": "s1.9 " + world.tag + " off", "filters": {"listing_type": "rent"}}
    )

    assert item["notify_new_matches"] is False
    assert item["notify_enabled_at"] is None
    assert item["min_price_drop"] is None
    assert item["new_match_alerts_supported"] is True
    assert item["last_new_match_alert_on"] is None

    fetched = client.get("/saved-searches/" + item["id"], headers=_HEADERS).json()
    for key in (
        "notify_new_matches",
        "notify_enabled_at",
        "min_price_drop",
        "new_match_alerts_supported",
        "last_new_match_alert_on",
    ):
        assert fetched[key] == item[key], key


def test_api_create_with_the_flag_stamps_the_enable_moment(world, client):
    item = _created(
        world,
        client,
        {
            "name": "s1.9 " + world.tag + " on",
            "filters": {},
            "notify_new_matches": True,
            "min_price_drop": 5,
        },
    )

    assert item["notify_new_matches"] is True
    assert item["min_price_drop"] == 5.0
    assert _recent(item["notify_enabled_at"])
    listed = client.get("/saved-searches?page_size=200", headers=_HEADERS).json()["items"]
    mine = next(entry for entry in listed if entry["id"] == item["id"])
    assert mine["notify_new_matches"] is True
    assert mine["notify_enabled_at"] == item["notify_enabled_at"]
    assert mine["min_price_drop"] == 5.0


def test_api_toggle_stamps_on_enable_keeps_on_disable_and_restamps(world, client):
    name = "s1.9 " + world.tag + " toggle"
    search_id = _created(world, client, {"name": name, "filters": {}})["id"]

    enabled = _patched(client, search_id, {"notify_new_matches": True})
    assert enabled["notify_new_matches"] is True
    assert _recent(enabled["notify_enabled_at"])

    # Already on: the floor does not move.
    again = _patched(client, search_id, {"notify_new_matches": True})
    assert again["notify_enabled_at"] == enabled["notify_enabled_at"]

    # Move the stored stamp into the past to tell a new stamp from the old one.
    world.execute(
        "UPDATE saved_searches SET notify_enabled_at = :at WHERE id = CAST(:sid AS uuid)",
        {"sid": search_id, "at": OLD},
    )
    disabled = _patched(client, search_id, {"notify_new_matches": False})
    assert disabled["notify_new_matches"] is False
    assert disabled["notify_enabled_at"] == OLD.isoformat()

    renamed = _patched(client, search_id, {"name": name + " renamed"})
    assert renamed["notify_new_matches"] is False
    assert renamed["notify_enabled_at"] == OLD.isoformat()

    reenabled = _patched(client, search_id, {"notify_new_matches": True})
    assert reenabled["notify_new_matches"] is True
    assert reenabled["notify_enabled_at"] != OLD.isoformat()
    assert _recent(reenabled["notify_enabled_at"])


def test_api_threshold_round_trip_and_explicit_null(world, client):
    name = "s1.9 " + world.tag + " threshold"
    search_id = _created(world, client, {"name": name, "filters": {}})["id"]

    assert _patched(client, search_id, {"min_price_drop": 7.5})["min_price_drop"] == 7.5
    # A patch that does not mention it leaves it.
    assert _patched(client, search_id, {"name": name + " b"})["min_price_drop"] == 7.5
    assert _patched(client, search_id, {"notify_new_matches": True})["min_price_drop"] == 7.5
    assert _patched(client, search_id, {"min_price_drop": 0})["min_price_drop"] == 0
    # null sent explicitly clears it.
    cleared = _patched(client, search_id, {"min_price_drop": None})
    assert cleared["min_price_drop"] is None
    assert cleared["notify_new_matches"] is True

    for method, url in (("post", "/saved-searches"), ("patch", "/saved-searches/" + search_id)):
        rejected = getattr(client, method)(
            url, json={"name": name + " bad", "filters": {}, "min_price_drop": -1}, headers=_HEADERS
        )
        assert rejected.status_code == 422, rejected.text


def test_api_semantic_search_can_be_enabled_but_is_reported_unsupported(world, client, mailbox):
    item = _created(
        world,
        client,
        {
            "name": "s1.9 " + world.tag + " semantic",
            "filters": {"q": "varanda gourmet", "platform": world.platform},
            "notify_new_matches": True,
        },
    )
    assert item["notify_new_matches"] is True
    assert item["new_match_alerts_supported"] is False

    world.add_property("a")
    world.score("a")
    assert _match()["unsupported"] >= 1
    assert world.matches("s1.9 " + world.tag + " semantic") == {}

    # Dropping the query makes it matchable.
    patched = _patched(client, item["id"], {"filters": {"platform": world.platform}})
    assert patched["new_match_alerts_supported"] is True


def test_api_reports_the_last_alert_date(world, client, mailbox):
    world.add_property("a")
    world.score("a")
    world.add_search("s", {})
    _match()
    _send()

    item = client.get("/saved-searches/" + world.searches["s"], headers=_HEADERS).json()
    assert item["last_new_match_alert_on"] == "2026-10-08"
    assert item["notify_enabled_at"] == ENABLED_AT.isoformat()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def _insert_match(world, search: str, label: str, status: str = "pending") -> None:
    world.execute(
        "INSERT INTO saved_search_new_matches (saved_search_id, property_id, owner, status) "
        "VALUES (CAST(:sid AS uuid), CAST(:pid AS uuid), :owner, :status)",
        {
            "sid": world.searches[search],
            "pid": world.props[label],
            "owner": world.owner,
            "status": status,
        },
    )


def test_unique_constraint_on_search_and_property(world):
    world.add_property("a")
    world.add_search("s", {})
    world.add_search("t", {})
    _insert_match(world, "s", "a")
    _insert_match(world, "t", "a")  # another search may match the same Property

    with pytest.raises(IntegrityError) as excinfo:
        _insert_match(world, "s", "a", status="sent")
    assert "uq_saved_search_new_match" in str(excinfo.value)


def test_status_check_constraint(world):
    world.add_property("a")
    world.add_search("s", {})

    with pytest.raises(IntegrityError) as excinfo:
        _insert_match(world, "s", "a", status="queued")
    assert "ck_saved_search_new_matches_status" in str(excinfo.value)


def test_min_price_drop_check_constraint(world):
    world.add_search("s", {})

    with pytest.raises(IntegrityError) as excinfo:
        world.execute(
            "UPDATE saved_searches SET min_price_drop = -0.01 WHERE id = CAST(:sid AS uuid)",
            {"sid": world.searches["s"]},
        )
    assert "ck_saved_searches_min_price_drop" in str(excinfo.value)


def test_row_defaults_and_foreign_keys(world):
    from infra.db import SessionLocal

    world.add_property("kept")
    world.add_property("deleted")
    world.add_search("s", {})
    world.execute(
        "INSERT INTO saved_search_new_matches (saved_search_id, property_id) "
        "SELECT CAST(:sid AS uuid), id FROM properties WHERE platform = :platform",
        {"sid": world.searches["s"], "platform": world.platform},
    )

    def rows() -> list:
        with SessionLocal() as session:
            return session.execute(
                text(
                    "SELECT a.saved_search_id, a.status, a.matched_at, a.sent_at, a.id "
                    "FROM saved_search_new_matches a JOIN properties p ON p.id = a.property_id "
                    "WHERE p.platform = :platform"
                ),
                {"platform": world.platform},
            ).fetchall()

    seeded = rows()
    assert len(seeded) == 2
    for search_id, status, matched_at, sent_at, row_id in seeded:
        assert str(search_id) == world.searches["s"]
        assert status == "pending"
        assert matched_at is not None
        assert sent_at is None
        assert row_id is not None

    # Deleting the Property removes its rows; deleting the search keeps them.
    world.execute(
        "DELETE FROM properties WHERE id = CAST(:pid AS uuid)", {"pid": world.props["deleted"]}
    )
    world.execute(
        "DELETE FROM saved_searches WHERE id = CAST(:sid AS uuid)", {"sid": world.searches["s"]}
    )
    left = rows()
    assert len(left) == 1
    assert left[0][0] is None


def test_models_match_the_migrated_schema():
    """``compare_metadata`` reports no difference on the two tables of this story."""
    from adapters.db.models import Base
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    tables = ("saved_searches", "saved_search_new_matches")
    # ``saved_searches`` carries older differences this story does not own (its
    # ``filters`` column is JSONB in the database); only what the story added is
    # compared.
    added = (
        "saved_search_new_matches",
        "notify_new_matches",
        "notify_enabled_at",
        "min_price_drop",
        "new_match_last_window_on",
    )

    def only_ours(name, type_) -> bool:
        return type_ != "table" or name in tables

    engine = create_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(
                conn,
                opts={
                    "include_name": lambda name, type_, _parents: only_ours(name, type_),
                    "include_object": lambda _obj, name, type_, *_: only_ours(name, type_),
                    "compare_server_default": True,
                },
            )
            diff = compare_metadata(context, Base.metadata)
            checks = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT conname FROM pg_constraint WHERE conname IN "
                        "('ck_saved_searches_min_price_drop', "
                        "'ck_saved_search_new_matches_status', 'uq_saved_search_new_match')"
                    )
                )
            }
    finally:
        engine.dispose()

    drift = [entry for entry in diff if any(name in repr(entry) for name in added)]
    assert drift == [], drift
    # compare_metadata does not look at CHECKs: pin the names both sides use.
    assert checks == {
        "ck_saved_searches_min_price_drop",
        "ck_saved_search_new_matches_status",
        "uq_saved_search_new_match",
    }
    model_constraints = {
        constraint.name
        for table in tables
        for constraint in Base.metadata.tables[table].constraints
    }
    assert checks <= model_constraints
