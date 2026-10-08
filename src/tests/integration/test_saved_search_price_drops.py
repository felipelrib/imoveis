"""Integration: the per-search price-drop alert on Postgres (v0.14-s1.10, FR-32).

Seeded like ``test_saved_search_new_matches.py`` (its ``_World`` is reused):
every row lives under one throwaway platform and every saved search filters on
it. The hourly sender task runs in process with a fixed clock; prices are real
``price_history`` intervals shaped as ``core.dedupe._record_price_change``
writes them; the email channel of the notifier registry is a recorder. No mail
server is contacted.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from adapters.notify.base import SavedSearchPriceDrops
from infra.config import get_config
from tests.db_isolation import assert_wipe_safe_database_url
from tests.integration.test_saved_search_new_matches import (
    _HEADERS,
    _TEST_API_KEY,
    CLOCK,
    _created,
    _patched,
    _recent,
    _Recorder,
    _send,
    _World,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("DATABASE_URL"),
        reason="DATABASE_URL not set",
    ),
]

REPO_ROOT = Path(__file__).resolve().parents[3]
REVISION = "a8b9c0d1e2f3"
DOWN_REVISION = "f7a8b9c0d1e2"

FLOOR = CLOCK - timedelta(days=2)  # drop alerts became active for the search
BEFORE = CLOCK - timedelta(days=10)  # a price in force long before that
FELL = CLOCK - timedelta(hours=3)  # a price change after the floor
TODAY = date(2026, 10, 8)
TOMORROW = CLOCK + timedelta(days=1)
DAY_AFTER = CLOCK + timedelta(days=2)


def _db_ready() -> bool:
    try:
        from infra.db import SessionLocal

        with SessionLocal() as session:
            session.execute(text("SELECT threshold FROM saved_search_price_drop_alerts LIMIT 0"))
            return True
    except Exception:
        return False


class _DropRecorder(_Recorder):
    def __init__(self) -> None:
        super().__init__()
        self.drop_batches: list[SavedSearchPriceDrops] = []

    def send_price_drops(self, batch: SavedSearchPriceDrops) -> None:
        if self.during is not None:
            self.during()
        if self.fail:
            raise RuntimeError("smtp down")
        self.drop_batches.append(batch)


class _DropWorld(_World):
    """``_World`` plus price history, drop searches and the alert rows."""

    def listing_id(self, label: str, listing_type: str = "rent") -> str:
        from infra.db import SessionLocal

        with SessionLocal() as session:
            row = session.execute(
                text(
                    "SELECT id FROM property_listings WHERE property_id = CAST(:pid AS uuid) "
                    "AND listing_type = :lt AND platform = :platform"
                ),
                {"pid": self.props[label], "lt": listing_type, "platform": self.platform},
            ).one()
        return str(row[0])

    def history(self, label: str, steps: list, *, listing_type: str = "rent") -> str:
        """Give a Listing its price intervals: ``[(since, price), ...]``, oldest first.

        Each interval ends where the next starts; the last one is open and its
        price becomes the Listing's price, as the persist path leaves them.
        """
        listing_id = self.listing_id(label, listing_type)
        self._write_history(label, listing_id, listing_type, self.platform, steps)
        return listing_id

    def _write_history(
        self, label: str, listing_id: str, listing_type: str, platform: str, steps: list
    ) -> None:
        from infra.db import SessionLocal

        with SessionLocal() as session:
            for index, (since, price) in enumerate(steps):
                until = steps[index + 1][0] if index + 1 < len(steps) else None
                session.execute(
                    text(
                        "INSERT INTO price_history (id, property_id, listing_type, platform, "
                        "property_listing_id, price, start_ts, end_ts) "
                        "VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), :lt, :platform, "
                        "CAST(:lid AS uuid), :price, :since, :until)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "pid": self.props[label],
                        "lt": listing_type,
                        "platform": platform,
                        "lid": listing_id,
                        "price": price,
                        "since": since,
                        "until": until,
                    },
                )
            session.execute(
                text("UPDATE property_listings SET price = :price WHERE id = CAST(:lid AS uuid)"),
                {"price": steps[-1][1], "lid": listing_id},
            )
            session.commit()

    def reprice(self, label: str, price: float, at: datetime, *, listing_type: str = "rent") -> None:
        """A later scrape saw another price: close the open interval, open one."""
        listing_id = self.listing_id(label, listing_type)
        self.execute(
            "UPDATE price_history SET end_ts = :at "
            "WHERE property_listing_id = CAST(:lid AS uuid) AND end_ts IS NULL",
            {"at": at, "lid": listing_id},
        )
        self._write_history(label, listing_id, listing_type, self.platform, [(at, price)])

    def add_dropped(
        self, label: str, before: float = 3240.0, now: float = 3000.0, *, scored: bool = True, **kwargs
    ) -> str:
        """A rent Property whose Listing went from ``before`` to ``now`` after the floor."""
        self.add_property(label, rent=now, **kwargs)
        if scored:
            self.score(label)
        return self.history(label, [(BEFORE, before), (FELL, now)])

    def add_other_listing(
        self,
        label: str,
        price: float,
        *,
        since: datetime,
        listing_type: str = "rent",
        platform: str | None = None,
    ) -> str:
        """A second Listing of the same Property, with its own history.

        On the searched platform by default (a second ad of the same home): the
        searches of these tests filter by platform, and a platform search only
        announces Listings of that platform. ``platform`` puts it elsewhere.
        """
        platform = platform or self.platform
        listing_id = str(uuid.uuid4())
        self.execute(
            "INSERT INTO property_listings (id, property_id, platform, platform_listing_id, "
            "listing_type, price, currency, url, active) "
            "VALUES (CAST(:lid AS uuid), CAST(:pid AS uuid), :platform, :plid, :lt, :price, "
            "'BRL', 'https://example.test/b', true)",
            {
                "lid": listing_id,
                "pid": self.props[label],
                "platform": platform,
                "plid": platform + "-" + label + "-" + uuid.uuid4().hex[:6],
                "lt": listing_type,
                "price": price,
            },
        )
        self._write_history(label, listing_id, listing_type, platform, [(since, price)])
        return listing_id

    def add_drop_search(
        self,
        label: str,
        filters: dict | None = None,
        *,
        threshold: float | None = 100.0,
        floor: datetime | None = FLOOR,
        notify: bool = True,
        **kwargs,
    ) -> str:
        search_id = self.add_search(label, filters, notify=notify, **kwargs)
        self.execute(
            "UPDATE saved_searches SET min_price_drop = :threshold, price_drop_enabled_at = :floor "
            "WHERE id = CAST(:sid AS uuid)",
            {"threshold": threshold, "floor": floor, "sid": search_id},
        )
        return search_id

    def alerts(self, search_label: str) -> list[dict]:
        """The alert rows of a search, oldest first, with the Property's label."""
        from infra.db import SessionLocal

        by_id = {pid: label for label, pid in self.props.items()}
        with SessionLocal() as session:
            rows = session.execute(
                text(
                    "SELECT property_id, property_listing_id, owner, listing_type, platform, "
                    "reference_price, new_price, threshold, sent_at "
                    "FROM saved_search_price_drop_alerts "
                    "WHERE saved_search_id = CAST(:sid AS uuid) ORDER BY sent_at, new_price DESC"
                ),
                {"sid": self.searches[search_label]},
            ).mappings().fetchall()
        return [{**dict(row), "label": by_id[str(row["property_id"])]} for row in rows]

    def drop_window(self, search_label: str) -> date | None:
        from infra.db import SessionLocal

        with SessionLocal() as session:
            return session.execute(
                text(
                    "SELECT price_drop_last_window_on FROM saved_searches "
                    "WHERE id = CAST(:sid AS uuid)"
                ),
                {"sid": self.searches[search_label]},
            ).scalar()


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch):
    if not _db_ready():
        pytest.skip("Postgres saved_search_price_drop_alerts table not available")
    monkeypatch.setenv("API_KEY", _TEST_API_KEY)
    monkeypatch.setenv("JWT_SECRET", "price-drop-test-jwt-secret")
    get_config.cache_clear()
    instance = _DropWorld(get_config().auth.principal_id)
    yield instance
    instance.cleanup()
    get_config.cache_clear()


@pytest.fixture
def mailbox(monkeypatch: pytest.MonkeyPatch):
    """The notifier registry with a recorder on every channel type."""
    recorders = {"log": _DropRecorder(), "redis": _DropRecorder(), "email": _DropRecorder()}
    monkeypatch.setattr("adapters.notify._registry", list(recorders.items()))
    return recorders


@pytest.fixture
def client(world):
    from api.main import app

    return TestClient(app, raise_server_exceptions=True)


def _drops(now: datetime = CLOCK) -> dict:
    """Run the hourly sender; return the drop pass's part of its result."""
    result = _send(now)
    # Nothing here is a new match: the new-match part stays silent.
    assert result["emails_sent"] == 0
    return result["price_drops"]


# ---------------------------------------------------------------------------
# I/O matrix
# ---------------------------------------------------------------------------


def test_drop_at_the_threshold_is_emailed_once_and_recorded(world, mailbox):
    listing_id = world.add_dropped("a", 3240.0, 3000.0)
    world.add_drop_search("s", {"listing_type": "rent", "max_price": 3500}, threshold=100)

    sent = _drops()

    assert sent == {
        "status": "ok",
        "searches_due": 1,
        "emails_sent": 1,
        "properties_alerted": 1,
        "unsupported": 0,
        "errors": 0,
    }
    # Exactly one email, on the email channel and no other, for the principal.
    assert len(mailbox["email"].drop_batches) == 1
    batch = mailbox["email"].drop_batches[0]
    assert batch.principal_id == world.owner
    assert batch.search_id == world.searches["s"]
    assert batch.property_ids == [world.props["a"]]
    assert batch.subject == "1 queda de preço na busca “s1.9 " + world.tag + " s”"
    lines = batch.body.split("\n")
    assert "1. s1.9 a" in lines
    assert "   Savassi, Belo Horizonte" in lines
    assert "   R$ 3.240/mês → R$ 3.000/mês · " + world.platform in lines
    assert "   queda de R$ 240 — seu mínimo: R$ 100" in lines
    for channel in ("log", "redis"):
        assert mailbox[channel].drop_batches == []
        assert mailbox[channel].batches == []
        assert mailbox[channel].other_calls == 0
    assert mailbox["email"].batches == []
    assert mailbox["email"].other_calls == 0

    # One alert row, with what the email compared and stated.
    rows = world.alerts("s")
    assert len(rows) == 1
    row = rows[0]
    assert row["label"] == "a"
    assert str(row["property_listing_id"]) == listing_id
    assert (row["reference_price"], row["new_price"], row["threshold"]) == (3240.0, 3000.0, 100.0)
    assert row["owner"] == world.owner
    assert row["listing_type"] == "rent"
    assert row["platform"] == world.platform
    assert row["sent_at"] == CLOCK
    assert world.drop_window("s") == TODAY
    # The new-match window is another column and was not touched.
    assert world.search_row("s")["new_match_last_window_on"] is None


def test_a_drop_of_exactly_the_threshold_alerts(world, mailbox):
    world.add_dropped("a", 3240.0, 3140.0)
    world.add_drop_search("s", threshold=100)

    assert _drops()["emails_sent"] == 1
    assert "queda de R$ 100 — seu mínimo: R$ 100" in mailbox["email"].drop_batches[0].body


def test_below_the_threshold_nothing_is_sent_and_the_day_stays_open(world, mailbox):
    world.add_dropped("a", 3240.0, 3200.0)
    world.add_drop_search("s", threshold=100)

    sent = _drops()

    assert sent["searches_due"] == 1
    assert sent["emails_sent"] == 0
    assert mailbox["email"].drop_batches == []
    assert world.alerts("s") == []
    assert world.drop_window("s") is None


def test_cumulative_drops_since_the_floor_add_up(world, mailbox):
    world.add_property("a", rent=3130.0)
    world.score("a")
    world.history(
        "a",
        [(BEFORE, 3240.0), (CLOCK - timedelta(hours=20), 3190.0), (CLOCK - timedelta(hours=2), 3130.0)],
    )
    world.add_drop_search("s", threshold=100)

    assert _drops()["emails_sent"] == 1

    assert len(mailbox["email"].drop_batches) == 1
    body = mailbox["email"].drop_batches[0].body
    assert "R$ 3.240/mês → R$ 3.130/mês" in body
    assert "queda de R$ 110 — seu mínimo: R$ 100" in body
    assert [(r["reference_price"], r["new_price"]) for r in world.alerts("s")] == [(3240.0, 3130.0)]


def test_an_alerted_price_needs_a_further_drop_of_the_threshold(world, mailbox):
    world.add_dropped("a", 3240.0, 3000.0)
    world.add_drop_search("s", threshold=100)
    assert _drops()["emails_sent"] == 1

    # Same price the next day: nothing, and the day stays open.
    assert _drops(TOMORROW)["emails_sent"] == 0
    assert world.drop_window("s") == TODAY

    # 3.000 -> 2.950 is 50 below the alerted price: under the minimum.
    world.reprice("a", 2950.0, TOMORROW + timedelta(minutes=10))
    assert _drops(TOMORROW + timedelta(hours=1))["emails_sent"] == 0
    assert len(mailbox["email"].drop_batches) == 1

    # 2.890 is 110 below it.
    world.reprice("a", 2890.0, DAY_AFTER - timedelta(hours=1))
    assert _drops(DAY_AFTER)["emails_sent"] == 1
    assert "R$ 3.000/mês → R$ 2.890/mês" in mailbox["email"].drop_batches[1].body
    assert "queda de R$ 110 — seu mínimo: R$ 100" in mailbox["email"].drop_batches[1].body
    assert [(r["reference_price"], r["new_price"]) for r in world.alerts("s")] == [
        (3240.0, 3000.0),
        (3000.0, 2890.0),
    ]


def test_a_rise_after_an_alert_keeps_the_alerted_price_as_the_reference(world, mailbox):
    """An alert announces a price below the last one this search announced."""
    world.add_dropped("a", 3240.0, 3000.0)
    world.add_drop_search("s", threshold=100)
    assert _drops()["emails_sent"] == 1

    # Up to 3.500, then down to 2.950: 550 below the peak, 50 below what the
    # search last said. Not news.
    world.reprice("a", 3500.0, TOMORROW + timedelta(minutes=10))
    world.reprice("a", 2950.0, TOMORROW + timedelta(minutes=20))
    assert _drops(TOMORROW + timedelta(hours=1))["emails_sent"] == 0
    assert world.drop_window("s") == TODAY

    # 2.890 is 110 below the alerted 3.000.
    world.reprice("a", 2890.0, DAY_AFTER - timedelta(hours=1))
    assert _drops(DAY_AFTER)["emails_sent"] == 1
    assert "R$ 3.000/mês → R$ 2.890/mês" in mailbox["email"].drop_batches[1].body
    assert "queda de R$ 110 — seu mínimo: R$ 100" in mailbox["email"].drop_batches[1].body
    assert [(r["reference_price"], r["new_price"]) for r in world.alerts("s")] == [
        (3240.0, 3000.0),
        (3000.0, 2890.0),
    ]


def test_a_rise_then_a_fall_short_of_the_price_at_activation_is_not_a_drop(world, mailbox):
    """Measured from the price in force at the floor, not from a later peak."""
    world.add_property("a", rent=3300.0)
    world.score("a")
    world.history("a", [(BEFORE, 3240.0), (FELL - timedelta(hours=2), 3600.0), (FELL, 3300.0)])
    world.add_drop_search("s", threshold=100)

    assert _drops()["emails_sent"] == 0

    # Below the price at activation by the minimum: a drop of 140, not of 500.
    world.reprice("a", 3100.0, TOMORROW - timedelta(hours=1))
    assert _drops(TOMORROW)["emails_sent"] == 1
    assert "queda de R$ 140 — seu mínimo: R$ 100" in mailbox["email"].drop_batches[0].body


def test_second_run_on_the_same_day_sends_nothing(world, mailbox):
    world.add_dropped("a", 3240.0, 3000.0)
    world.add_drop_search("s", threshold=100)
    assert _drops()["emails_sent"] == 1

    world.add_dropped("b", 3240.0, 3000.0)
    again = _drops(CLOCK + timedelta(hours=1))

    assert again["searches_due"] == 0
    assert again["emails_sent"] == 0
    assert len(mailbox["email"].drop_batches) == 1
    # The drop found after today's email leaves tomorrow.
    assert _drops(TOMORROW)["emails_sent"] == 1
    assert mailbox["email"].drop_batches[1].property_ids == [world.props["b"]]


def test_before_the_window_hour_nothing_is_sent(world, mailbox):
    world.add_dropped("a", 3240.0, 3000.0)
    world.add_drop_search("s", threshold=100)

    early = _drops(datetime(2026, 10, 8, 9, 0))  # 06:00 in Sao Paulo

    assert early["searches_due"] == 0
    assert mailbox["email"].drop_batches == []


def test_no_threshold_or_switch_off_means_no_drop_email(world, mailbox):
    world.add_dropped("a", 3240.0, 3000.0)
    world.add_drop_search("no-threshold", threshold=None)
    world.add_drop_search("off", threshold=100, notify=False)
    # On with a threshold, but never activated through the API (no floor).
    world.add_drop_search("no-floor", threshold=100, floor=None)

    sent = _drops()

    assert sent["searches_due"] == 0
    assert sent["emails_sent"] == 0
    assert mailbox["email"].drop_batches == []
    for label in ("no-threshold", "off", "no-floor"):
        assert world.alerts(label) == []


def test_threshold_zero_alerts_on_any_drop(world, mailbox):
    world.add_dropped("a", 3240.0, 3239.0)
    world.add_drop_search("s", threshold=0)

    assert _drops()["emails_sent"] == 1

    assert "queda de R$ 1 — seu mínimo: R$ 0" in mailbox["email"].drop_batches[0].body
    assert world.alerts("s")[0]["threshold"] == 0.0


def test_a_drop_before_activation_is_not_alerted(world, mailbox):
    world.add_property("a", rent=3000.0)
    world.score("a")
    # The price fell a day before drop alerts became active for the search.
    world.history("a", [(BEFORE, 3240.0), (FLOOR - timedelta(days=1), 3000.0)])
    world.add_drop_search("s", threshold=100)

    sent = _drops()

    assert sent["emails_sent"] == 0
    assert mailbox["email"].drop_batches == []
    assert world.alerts("s") == []


def test_a_listing_first_seen_after_activation_is_measured_from_its_first_price(world, mailbox):
    world.add_property("a", rent=3000.0)
    world.score("a")
    world.history("a", [(FLOOR + timedelta(hours=5), 3240.0), (FELL, 3000.0)])
    world.add_drop_search("s", threshold=100)

    assert _drops()["emails_sent"] == 1
    assert (world.alerts("s")[0]["reference_price"], world.alerts("s")[0]["new_price"]) == (
        3240.0,
        3000.0,
    )


def test_a_cheaper_listing_appearing_is_not_a_drop(world, mailbox):
    world.add_property("a", rent=3240.0)
    world.score("a")
    world.history("a", [(BEFORE, 3240.0)])
    # A second ad lists the same home for less; no Listing's own price fell.
    world.add_other_listing("a", 2500.0, since=FELL)
    world.add_drop_search("s", threshold=100)

    sent = _drops()

    assert sent["emails_sent"] == 0
    assert mailbox["email"].drop_batches == []


def test_a_price_rise_is_not_a_drop(world, mailbox):
    world.add_dropped("a", 3000.0, 3240.0)
    world.add_drop_search("s", threshold=0)

    assert _drops()["emails_sent"] == 0


def test_one_block_per_property_with_its_largest_drop(world, mailbox):
    first = world.add_dropped("a", 3240.0, 3100.0)  # 140 on the first Listing
    other = world.add_other_listing("a", 3500.0, since=BEFORE)
    world.execute(
        "UPDATE price_history SET end_ts = :at WHERE property_listing_id = CAST(:lid AS uuid)",
        {"at": FELL, "lid": other},
    )
    world._write_history("a", other, "rent", world.platform, [(FELL, 3200.0)])  # 300
    world.add_drop_search("s", threshold=100)

    assert _drops()["properties_alerted"] == 1

    body = mailbox["email"].drop_batches[0].body
    assert "queda de R$ 300 — seu mínimo: R$ 100" in body
    assert "queda de R$ 140" not in body
    # Both Listings that fell are recorded, the one the email showed and the
    # other: the Property is not emailed again for the smaller, older drop.
    rows = world.alerts("s")
    assert sorted((str(r["property_listing_id"]), r["new_price"]) for r in rows) == sorted(
        [(other, 3200.0), (first, 3100.0)]
    )
    assert _drops(TOMORROW)["emails_sent"] == 0
    assert len(mailbox["email"].drop_batches) == 1


def test_a_listing_above_the_searched_price_cap_is_not_announced(world, mailbox):
    first = world.add_dropped("a", 3240.0, 3000.0)  # within the cap: 240
    other = world.add_other_listing("a", 3900.0, since=BEFORE)
    world.execute(
        "UPDATE price_history SET end_ts = :at WHERE property_listing_id = CAST(:lid AS uuid)",
        {"at": FELL, "lid": other},
    )
    world._write_history("a", other, "rent", world.platform, [(FELL, 3500.0)])  # 400
    world.add_drop_search(
        "s", {"listing_type": "rent", "max_price": 3300, "price_type": "rent"}, threshold=100
    )

    assert _drops()["properties_alerted"] == 1

    body = mailbox["email"].drop_batches[0].body
    assert "queda de R$ 240 — seu mínimo: R$ 100" in body
    assert "queda de R$ 400" not in body
    assert [str(r["property_listing_id"]) for r in world.alerts("s")] == [first]


def test_a_listing_of_another_platform_is_not_announced_for_a_platform_search(world, mailbox):
    world.add_dropped("a", 3240.0, 3100.0)  # the searched platform: 140
    other = world.add_other_listing("a", 3500.0, since=BEFORE, platform=world.platform + "-b")
    world.execute(
        "UPDATE price_history SET end_ts = :at WHERE property_listing_id = CAST(:lid AS uuid)",
        {"at": FELL, "lid": other},
    )
    world._write_history("a", other, "rent", world.platform + "-b", [(FELL, 3200.0)])  # 300
    world.add_drop_search("s", {"platform": world.platform}, threshold=100)

    assert _drops()["properties_alerted"] == 1

    body = mailbox["email"].drop_batches[0].body
    assert "queda de R$ 140 — seu mínimo: R$ 100" in body
    assert "queda de R$ 300" not in body


def test_a_drop_written_by_the_persist_path_is_alerted(world, mailbox):
    """The history rows of ``core.dedupe._record_price_change`` itself, not a fixture."""
    from core.dedupe import _record_price_change
    from infra.db import SessionLocal

    world.add_property("a", rent=3240.0)
    world.score("a")
    listing_id = world.history("a", [(BEFORE, 3240.0)])
    world.add_drop_search("s", threshold=100)

    with SessionLocal() as session:
        _record_price_change(
            session,
            world.props["a"],
            3000.0,
            listing_type="rent",
            platform=world.platform,
            property_listing_id=listing_id,
        )
        session.execute(
            text("UPDATE property_listings SET price = 3000 WHERE id = CAST(:lid AS uuid)"),
            {"lid": listing_id},
        )
        session.commit()

    assert _drops()["properties_alerted"] == 1
    assert "queda de R$ 240 — seu mínimo: R$ 100" in mailbox["email"].drop_batches[0].body
    rows = world.alerts("s")
    assert [(r["reference_price"], r["new_price"]) for r in rows] == [(3240.0, 3000.0)]


def test_held_until_the_property_matches_is_active_and_is_decidable(world, mailbox):
    world.add_dropped("small", bedrooms=1)  # the search asks for two bedrooms
    world.add_dropped("inactive", active=False)
    world.add_dropped("undecided", scored=False)
    world.add_drop_search("s", {"min_bedrooms": 2}, threshold=100)

    first = _drops()
    assert first["emails_sent"] == 0
    assert world.alerts("s") == []
    assert world.drop_window("s") is None

    # A day later all three match, are active and have a verdict; the drops hold.
    world.execute(
        "UPDATE properties SET bedrooms = 2 WHERE id = CAST(:pid AS uuid)",
        {"pid": world.props["small"]},
    )
    world.execute(
        "UPDATE properties SET active = true WHERE id = CAST(:pid AS uuid)",
        {"pid": world.props["inactive"]},
    )
    world.score("undecided")

    later = _drops(TOMORROW)
    assert later["emails_sent"] == 1
    assert later["properties_alerted"] == 3
    assert world.labels(mailbox["email"].drop_batches[0].property_ids) == [
        "inactive",
        "small",
        "undecided",
    ]


def test_an_inactive_listing_is_not_alerted(world, mailbox):
    listing_id = world.add_dropped("a", 3240.0, 3000.0)
    world.execute(
        "UPDATE property_listings SET active = false WHERE id = CAST(:lid AS uuid)",
        {"lid": listing_id},
    )
    world.add_drop_search("s", threshold=100)

    assert _drops()["emails_sent"] == 0


def test_a_watched_property_is_announced_whatever_the_watchlist_stamped(world, mailbox):
    """The watchlist alert and the search's drop alert are independent.

    ``watchlist.last_notified_price`` is written when that path enqueues an
    alert, before its debounce and its delivery, and it survives a later rise.
    A Listing that falls (back) to a stamped price is announced by the search
    all the same: left out, nobody would say it.
    """
    world.add_dropped("same-price", 3240.0, 3000.0)
    world.add_dropped("older-stamp", 3240.0, 3000.0)
    for label, notified in (
        ("same-price", 3000.0),  # the stamp equals the Listing's price now
        ("older-stamp", 3100.0),
    ):
        world.execute(
            "INSERT INTO watchlist (property_id, owner, min_drop_pct, last_notified_price) "
            "VALUES (CAST(:pid AS uuid), :owner, 5.0, :notified)",
            {"pid": world.props[label], "owner": world.owner, "notified": notified},
        )
    world.add_drop_search("s", threshold=100)

    assert _drops()["properties_alerted"] == 2

    assert sorted(world.labels(mailbox["email"].drop_batches[0].property_ids)) == [
        "older-stamp",
        "same-price",
    ]
    assert sorted(row["label"] for row in world.alerts("s")) == ["older-stamp", "same-price"]


def test_unmatchable_search_is_counted_and_sends_nothing(world, mailbox):
    world.add_dropped("a", 3240.0, 3000.0)
    world.add_drop_search("semantic", {"q": "varanda gourmet"}, threshold=100)

    sent = _drops()

    assert sent["unsupported"] == 1
    assert sent["emails_sent"] == 0
    assert mailbox["email"].drop_batches == []
    assert world.alerts("semantic") == []
    assert world.drop_window("semantic") is None


def test_a_typed_search_only_looks_at_listings_of_its_type(world, mailbox):
    world.add_property("dual", rent=3000.0, sale=480000.0)
    world.score("dual")
    world.history("dual", [(BEFORE, 3000.0)])
    world.history("dual", [(BEFORE, 500000.0), (FELL, 480000.0)], listing_type="sale")
    world.add_drop_search("rent-only", {"listing_type": "rent"}, threshold=100)
    world.add_drop_search("any-type", {"listing_type": "both"}, threshold=100)

    assert _drops()["emails_sent"] == 1

    assert world.alerts("rent-only") == []
    rows = world.alerts("any-type")
    assert [(r["listing_type"], r["reference_price"], r["new_price"]) for r in rows] == [
        ("sale", 500000.0, 480000.0)
    ]
    body = mailbox["email"].drop_batches[0].body
    assert "R$ 500.000 → R$ 480.000" in body
    assert "queda de R$ 20.000 — seu mínimo: R$ 100" in body
    assert "/mês" not in body


def test_a_sale_search_capped_on_rent_announces_its_sale_listing(world, mailbox):
    """Sale Listings of homes that also rent for at most the cap.

    The cap is about the rent Listing (the grid's own WHERE keeps it); the
    announced Listing is of the searched type. Holding the cap against the
    sale Listing as well would match nothing, so the search would never alert.
    """
    world.add_property("dual", rent=3000.0, sale=480000.0)
    world.score("dual")
    world.history("dual", [(BEFORE, 3000.0)])
    world.history("dual", [(BEFORE, 500000.0), (FELL, 480000.0)], listing_type="sale")
    world.add_property("dear-rent", rent=9000.0, sale=480000.0)
    world.score("dear-rent")
    world.history("dear-rent", [(BEFORE, 9000.0)])
    world.history("dear-rent", [(BEFORE, 500000.0), (FELL, 480000.0)], listing_type="sale")
    world.add_drop_search(
        "s", {"listing_type": "sale", "max_price": 3500, "price_type": "rent"}, threshold=100
    )

    assert _drops()["properties_alerted"] == 1

    rows = world.alerts("s")
    assert [(r["label"], r["listing_type"], r["reference_price"], r["new_price"]) for r in rows] == [
        ("dual", "sale", 500000.0, 480000.0)
    ]
    assert "queda de R$ 20.000 — seu mínimo: R$ 100" in mailbox["email"].drop_batches[0].body


def test_more_drops_than_fit_the_largest_leave_and_only_those_are_recorded(world, mailbox):
    limit = get_config().alerts.price_drop.max_items_per_email
    assert limit == 20
    for index in range(25):
        # Drops of 100, 110, ... 340.
        world.add_dropped("p%02d" % index, 4000.0, 3900.0 - 10 * index)
    world.add_drop_search("s", threshold=100)

    sent = _drops()

    assert sent["emails_sent"] == 1
    assert sent["properties_alerted"] == 20
    batch = mailbox["email"].drop_batches[0]
    largest = ["p%02d" % index for index in range(5, 25)]
    assert world.labels(batch.property_ids) == largest
    assert batch.property_ids[0] == world.props["p24"]
    assert batch.subject.startswith("20 quedas de preço na busca")
    assert "+5 nesta busca chegam no próximo aviso." in batch.body.split("\n")
    assert sorted(row["label"] for row in world.alerts("s")) == largest

    # The five that did not fit were not recorded: they leave the next day.
    later = _drops(TOMORROW)
    assert later["properties_alerted"] == 5
    assert world.labels(mailbox["email"].drop_batches[1].property_ids) == [
        "p%02d" % index for index in range(5)
    ]
    assert len(world.alerts("s")) == 25


def test_failed_send_records_nothing_and_gives_the_day_back(world, mailbox):
    world.add_dropped("a", 3240.0, 3000.0)
    world.add_drop_search("s", threshold=100)
    world.execute(
        "UPDATE saved_searches SET price_drop_last_window_on = :day WHERE id = CAST(:sid AS uuid)",
        {"day": date(2026, 10, 7), "sid": world.searches["s"]},
    )
    mailbox["email"].fail = True

    failed = _drops()

    assert failed["errors"] == 1
    assert failed["emails_sent"] == 0
    assert world.alerts("s") == []
    assert world.drop_window("s") == date(2026, 10, 7)

    mailbox["email"].fail = False
    retried = _drops(CLOCK + timedelta(hours=1))
    assert retried["emails_sent"] == 1
    assert len(world.alerts("s")) == 1
    assert world.drop_window("s") == TODAY
    assert len(mailbox["email"].drop_batches) == 1


def test_no_email_channel_sends_nothing_and_records_nothing(world, monkeypatch):
    log_only = _DropRecorder()
    monkeypatch.setattr("adapters.notify._registry", [("log", log_only)])
    world.add_dropped("a", 3240.0, 3000.0)
    world.add_drop_search("s", threshold=100)

    sent = _drops()

    assert sent["status"] == "no_email_channel"
    assert sent["emails_sent"] == 0
    assert world.alerts("s") == []
    assert world.drop_window("s") is None
    assert log_only.drop_batches == []
    assert log_only.other_calls == 0


def test_searches_of_another_or_no_owner_are_ignored(world, mailbox):
    world.add_dropped("a", 3240.0, 3000.0)
    world.add_drop_search("theirs", threshold=100, owner="someone-else")
    world.add_drop_search("nobody", threshold=100, owner=None)

    sent = _drops()

    assert sent["searches_due"] == 0
    assert mailbox["email"].drop_batches == []


def test_switching_off_and_on_starts_the_comparison_over(world, client, mailbox):
    world.add_dropped("a", 3240.0, 3000.0)
    search_id = world.add_drop_search("s", threshold=100)
    assert _drops()["emails_sent"] == 1

    _patched(client, search_id, {"notify_new_matches": False})
    reenabled = _patched(client, search_id, {"notify_new_matches": True})
    assert _recent(reenabled["price_drop_enabled_at"])
    # The floor is now (wall clock); put it between the two price changes below.
    world.execute(
        "UPDATE saved_searches SET price_drop_enabled_at = :floor WHERE id = CAST(:sid AS uuid)",
        {"floor": TOMORROW, "sid": search_id},
    )
    # 2.950 is only 50 below the earlier alert, but that alert is before the
    # new floor: the comparison starts from the price in force at the floor.
    world.reprice("a", 2950.0, TOMORROW - timedelta(hours=1))
    world.reprice("a", 2840.0, TOMORROW + timedelta(hours=1))

    assert _drops(DAY_AFTER)["emails_sent"] == 1
    assert [(r["reference_price"], r["new_price"]) for r in world.alerts("s")] == [
        (3240.0, 3000.0),
        (2950.0, 2840.0),
    ]


def test_threshold_changed_before_the_window_is_the_one_stated_and_recorded(world, client, mailbox):
    world.add_dropped("a", 3240.0, 3000.0)
    search_id = world.add_drop_search("s", threshold=500)
    assert _drops()["emails_sent"] == 0

    changed = _patched(client, search_id, {"min_price_drop": 200})
    # Changing the value while active leaves the floor.
    assert changed["price_drop_enabled_at"] == FLOOR.isoformat()

    assert _drops(CLOCK + timedelta(hours=1))["emails_sent"] == 1
    assert "queda de R$ 240 — seu mínimo: R$ 200" in mailbox["email"].drop_batches[0].body
    assert world.alerts("s")[0]["threshold"] == 200.0


def test_search_deleted_while_its_email_is_being_sent(world, client, mailbox):
    from infra.db import SessionLocal

    world.add_dropped("a", 3240.0, 3000.0)
    search_id = world.add_drop_search("s", threshold=100)
    seen: dict = {}

    def during() -> None:
        # No lock is held during the send: the delete does not wait.
        seen["delete"] = client.delete("/saved-searches/" + search_id, headers=_HEADERS).status_code

    mailbox["email"].during = during
    sent = _drops()

    assert seen["delete"] == 200
    assert sent["errors"] == 0
    assert sent["emails_sent"] == 1
    assert len(mailbox["email"].drop_batches) == 1
    # Nothing is recorded for a search that no longer exists.
    with SessionLocal() as session:
        left = session.execute(
            text(
                "SELECT COUNT(*) FROM saved_search_price_drop_alerts "
                "WHERE property_id = CAST(:pid AS uuid)"
            ),
            {"pid": world.props["a"]},
        ).scalar()
    assert left == 0


def test_a_search_whose_statement_fails_does_not_stop_the_others(world, mailbox):
    world.add_dropped("a", 3240.0, 3000.0)
    # Not a number: Postgres rejects the comparison with the listing price.
    world.add_drop_search("broken", {"max_price": "abc"}, threshold=100)
    world.add_drop_search("fine", threshold=100)

    sent = _drops()

    assert sent["errors"] == 1
    assert sent["emails_sent"] == 1
    assert [batch.search_id for batch in mailbox["email"].drop_batches] == [world.searches["fine"]]


# ---------------------------------------------------------------------------
# API: the activation stamp and the read-only fields
# ---------------------------------------------------------------------------


def _stored_floor(world, search_id: str):
    from infra.db import SessionLocal

    with SessionLocal() as session:
        return session.execute(
            text("SELECT price_drop_enabled_at FROM saved_searches WHERE id = CAST(:sid AS uuid)"),
            {"sid": search_id},
        ).scalar()


def test_api_stamps_the_floor_when_drop_alerts_become_active(world, client):
    name = "s1.9 " + world.tag + " stamp"
    created = _created(world, client, {"name": name, "filters": {}})
    search_id = created["id"]
    assert created["price_drop_enabled_at"] is None
    assert created["last_price_drop_alert_on"] is None

    # A threshold while the switch is off, or the switch without a threshold.
    assert _patched(client, search_id, {"min_price_drop": 100})["price_drop_enabled_at"] is None
    _patched(client, search_id, {"min_price_drop": None})
    assert _patched(client, search_id, {"notify_new_matches": True})["price_drop_enabled_at"] is None

    # Threshold set while on: active from now.
    active = _patched(client, search_id, {"min_price_drop": 100})
    assert _recent(active["price_drop_enabled_at"])
    assert active["min_price_drop"] == 100.0

    # Tell a new stamp from the old one.
    old = datetime(2026, 1, 1, 12, 0)
    world.execute(
        "UPDATE saved_searches SET price_drop_enabled_at = :at WHERE id = CAST(:sid AS uuid)",
        {"at": old, "sid": search_id},
    )
    # Changing the value while active, a rename, or switching off leave it.
    for body in ({"min_price_drop": 240}, {"name": name + " b"}, {"notify_new_matches": False}):
        assert _patched(client, search_id, body)["price_drop_enabled_at"] == old.isoformat()
    assert _stored_floor(world, search_id) == old

    # Switched on again with the threshold stored: a new floor.
    again = _patched(client, search_id, {"notify_new_matches": True})
    assert again["price_drop_enabled_at"] != old.isoformat()
    assert _recent(again["price_drop_enabled_at"])
    assert again["min_price_drop"] == 240.0

    fetched = client.get("/saved-searches/" + search_id, headers=_HEADERS).json()
    assert fetched["price_drop_enabled_at"] == again["price_drop_enabled_at"]


def test_api_patch_waits_for_a_concurrent_write_and_stamps_from_what_it_left(world, client):
    """The row's switch and threshold are two requests that can arrive together.

    The second one decides the stamp from the row as the first one left it:
    its read takes the row lock. Deciding from a read made before the other
    write committed, neither request would see drop alerts become active and
    the search would be on, with a minimum, and no floor: it would never send.
    """
    name = "s1.9 " + world.tag + " together"
    search_id = _created(world, client, {"name": name, "filters": {}})["id"]
    answer: dict = {}

    def write_threshold() -> None:
        answer["item"] = _patched(client, search_id, {"min_price_drop": 100})

    thread = threading.Thread(target=write_threshold, daemon=True)
    engine = create_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    try:
        with engine.connect() as other_request:
            transaction = other_request.begin()
            other_request.execute(
                text("SELECT id FROM saved_searches WHERE id = CAST(:sid AS uuid) FOR UPDATE"),
                {"sid": search_id},
            )
            thread.start()
            thread.join(timeout=1.5)
            assert thread.is_alive(), "the PATCH did not wait for the row"
            other_request.execute(
                text(
                    "UPDATE saved_searches SET notify_new_matches = true, "
                    "notify_enabled_at = (now() AT TIME ZONE 'utc') "
                    "WHERE id = CAST(:sid AS uuid)"
                ),
                {"sid": search_id},
            )
            transaction.commit()
        thread.join(timeout=30)
        assert not thread.is_alive()
    finally:
        engine.dispose()

    item = answer["item"]
    assert item["notify_new_matches"] is True
    assert item["min_price_drop"] == 100.0
    assert item["price_drop_enabled_at"] is not None
    assert _recent(item["price_drop_enabled_at"])
    assert _stored_floor(world, search_id) is not None


def test_api_create_with_switch_and_threshold_is_active_at_once(world, client):
    item = _created(
        world,
        client,
        {
            "name": "s1.9 " + world.tag + " created-on",
            "filters": {},
            "notify_new_matches": True,
            "min_price_drop": 0,
        },
    )

    assert _recent(item["price_drop_enabled_at"])
    assert _stored_floor(world, item["id"]) is not None

    only_switch = _created(
        world,
        client,
        {"name": "s1.9 " + world.tag + " created-switch", "filters": {}, "notify_new_matches": True},
    )
    assert only_switch["price_drop_enabled_at"] is None


def test_api_reports_the_last_drop_email_date(world, client, mailbox):
    world.add_dropped("a", 3240.0, 3000.0)
    search_id = world.add_drop_search("s", threshold=100)
    _drops()

    item = client.get("/saved-searches/" + search_id, headers=_HEADERS).json()
    assert item["last_price_drop_alert_on"] == "2026-10-08"
    assert item["price_drop_enabled_at"] == FLOOR.isoformat()
    assert item["last_new_match_alert_on"] is None
    listed = client.get("/saved-searches?page_size=200", headers=_HEADERS).json()["items"]
    mine = next(entry for entry in listed if entry["id"] == search_id)
    assert mine["last_price_drop_alert_on"] == "2026-10-08"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def _insert_alert(world, search: str, label: str, *, reference: float, new: float, threshold: float):
    world.execute(
        "INSERT INTO saved_search_price_drop_alerts (saved_search_id, property_id, "
        "property_listing_id, listing_type, reference_price, new_price, threshold) "
        "VALUES (CAST(:sid AS uuid), CAST(:pid AS uuid), CAST(:lid AS uuid), 'rent', "
        ":reference, :new, :threshold)",
        {
            "sid": world.searches[search],
            "pid": world.props[label],
            "lid": world.listing_id(label),
            "reference": reference,
            "new": new,
            "threshold": threshold,
        },
    )


@pytest.mark.parametrize(
    ("reference", "new", "threshold"),
    [(3000.0, 3000.0, 100.0), (3000.0, 3240.0, 100.0), (3240.0, 3000.0, -1.0)],
)
def test_only_a_drop_with_a_valid_threshold_can_be_stored(world, reference, new, threshold):
    world.add_property("a")
    world.add_drop_search("s")

    with pytest.raises(IntegrityError) as excinfo:
        _insert_alert(world, "s", "a", reference=reference, new=new, threshold=threshold)
    assert "ck_saved_search_price_drop_alerts_drop" in str(excinfo.value)


def test_row_defaults_and_cascades(world):
    from infra.db import SessionLocal

    for label in ("search-goes", "listing-goes", "property-goes"):
        world.add_property(label)
    world.add_drop_search("kept")
    world.add_drop_search("deleted")
    _insert_alert(world, "deleted", "search-goes", reference=3240.0, new=3000.0, threshold=0.0)
    _insert_alert(world, "kept", "listing-goes", reference=3240.0, new=3000.0, threshold=0.0)
    _insert_alert(world, "kept", "property-goes", reference=3240.0, new=3000.0, threshold=0.0)
    _insert_alert(world, "kept", "search-goes", reference=3240.0, new=3000.0, threshold=0.0)

    def rows() -> list:
        with SessionLocal() as session:
            return session.execute(
                text(
                    "SELECT a.id, a.sent_at, a.owner, a.platform FROM saved_search_price_drop_alerts a "
                    "JOIN properties p ON p.id = a.property_id WHERE p.platform = :platform"
                ),
                {"platform": world.platform},
            ).fetchall()

    seeded = rows()
    assert len(seeded) == 4
    for row_id, sent_at, owner, platform in seeded:
        assert row_id is not None
        assert sent_at is not None
        assert owner is None and platform is None

    # An alert goes with its search, with its Listing and with its Property.
    world.execute(
        "DELETE FROM saved_searches WHERE id = CAST(:sid AS uuid)",
        {"sid": world.searches["deleted"]},
    )
    assert len(rows()) == 3
    world.execute(
        "DELETE FROM property_listings WHERE id = CAST(:lid AS uuid)",
        {"lid": world.listing_id("listing-goes")},
    )
    assert len(rows()) == 2
    world.execute(
        "DELETE FROM properties WHERE id = CAST(:pid AS uuid)",
        {"pid": world.props["property-goes"]},
    )
    assert len(rows()) == 1


def test_models_match_the_migrated_schema():
    """``compare_metadata`` reports no difference on what this story added."""
    from adapters.db.models import Base
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    tables = ("saved_searches", "saved_search_price_drop_alerts")
    # ``saved_searches`` carries older differences this story does not own (its
    # ``filters`` column is JSONB in the database); only what the story added is
    # compared.
    added = (
        "saved_search_price_drop_alerts",
        "price_drop_enabled_at",
        "price_drop_last_window_on",
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
                        "SELECT conname FROM pg_constraint "
                        "WHERE conname = 'ck_saved_search_price_drop_alerts_drop'"
                    )
                )
            }
            indexes = {
                row[0]: row[1]
                for row in conn.execute(
                    text(
                        "SELECT indexname, indexdef FROM pg_indexes "
                        "WHERE tablename = 'saved_search_price_drop_alerts'"
                    )
                )
            }
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    finally:
        engine.dispose()

    drift = [entry for entry in diff if any(name in repr(entry) for name in added)]
    assert drift == [], drift
    # compare_metadata does not look at CHECKs: pin the name both sides use.
    assert checks == {"ck_saved_search_price_drop_alerts_drop"}
    model = Base.metadata.tables["saved_search_price_drop_alerts"]
    assert "ck_saved_search_price_drop_alerts_drop" in {c.name for c in model.constraints}
    assert {
        "ix_saved_search_price_drop_alerts_lookup",
        "ix_saved_search_price_drop_alerts_property_id",
    } <= set(indexes)
    assert "(saved_search_id, property_listing_id, sent_at)" in indexes[
        "ix_saved_search_price_drop_alerts_lookup"
    ]
    assert version is not None


class TestPriceDropMigration:
    """Revision ``a8b9c0d1e2f3`` reverses, and applies over searches that exist."""

    @staticmethod
    def _alembic(*args: str) -> subprocess.CompletedProcess:
        # A subprocess keeps alembic's logging reconfiguration out of the test run.
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )

    @staticmethod
    def _columns(engine) -> set[str]:
        with engine.connect() as conn:
            return {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'saved_searches' AND column_name IN "
                        "('price_drop_enabled_at', 'price_drop_last_window_on')"
                    )
                )
            }

    @staticmethod
    def _has_alerts_table(engine) -> bool:
        with engine.connect() as conn:
            return (
                conn.execute(
                    text("SELECT to_regclass('public.saved_search_price_drop_alerts')")
                ).scalar()
                is not None
            )

    def test_downgrade_then_upgrade_round_trips_and_stamps_only_active_searches(self):
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            pytest.skip("DATABASE_URL not set — run through scripts/agent/validate.py")
        assert_wipe_safe_database_url(database_url)
        engine = create_engine(database_url, poolclass=NullPool)
        owner = "s1.10-migration-" + uuid.uuid4().hex[:8]
        # Stored before this story (the Story 1.9 API already took both fields).
        before = {
            "on with a minimum": (True, 100.0),
            "on with any drop": (True, 0.0),
            "on without a minimum": (True, None),
            "off with a minimum": (False, 100.0),
            "off": (False, None),
        }
        try:
            assert self._columns(engine) == {"price_drop_enabled_at", "price_drop_last_window_on"}
            assert self._has_alerts_table(engine)
            try:
                # Explicit target: stays a real round trip after later migrations land.
                down = self._alembic("downgrade", DOWN_REVISION)
                assert down.returncode == 0, down.stderr
                with engine.connect() as conn:
                    assert (
                        conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
                        == DOWN_REVISION
                    )
                assert self._columns(engine) == set()
                assert not self._has_alerts_table(engine)
                with engine.begin() as conn:
                    for name, (notify, minimum) in before.items():
                        conn.execute(
                            text(
                                "INSERT INTO saved_searches (id, name, filters, owner, created_at, "
                                "notify_new_matches, notify_enabled_at, min_price_drop) "
                                "VALUES (gen_random_uuid(), :name, CAST('{}' AS jsonb), :owner, "
                                "now() AT TIME ZONE 'utc', :notify, "
                                "CASE WHEN :notify THEN now() AT TIME ZONE 'utc' END, :minimum)"
                            ),
                            {"name": name, "owner": owner, "notify": notify, "minimum": minimum},
                        )
            finally:
                up = self._alembic("upgrade", "head")
            assert up.returncode == 0, up.stderr
            assert self._columns(engine) == {"price_drop_enabled_at", "price_drop_last_window_on"}
            assert self._has_alerts_table(engine)
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT name, price_drop_enabled_at, price_drop_last_window_on, "
                        "notify_new_matches, min_price_drop, "
                        "(now() AT TIME ZONE 'utc') - price_drop_enabled_at AS age "
                        "FROM saved_searches WHERE owner = :owner"
                    ),
                    {"owner": owner},
                ).fetchall()
            stored = {row.name: row for row in rows}
            assert set(stored) == set(before)
            # Active before the migration: measured from the migration on.
            for name in ("on with a minimum", "on with any drop"):
                assert stored[name].price_drop_enabled_at is not None, name
                assert timedelta(0) <= stored[name].age < timedelta(minutes=10), name
            # Nothing is switched on by the migration.
            for name in ("on without a minimum", "off with a minimum", "off"):
                assert stored[name].price_drop_enabled_at is None, name
            for name, (notify, minimum) in before.items():
                assert stored[name].notify_new_matches is notify, name
                assert stored[name].min_price_drop == minimum, name
                assert stored[name].price_drop_last_window_on is None, name
        finally:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM saved_searches WHERE owner = :owner"), {"owner": owner})
            engine.dispose()

    def test_revision_ids_are_the_ones_this_test_round_trips(self):
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        script = ScriptDirectory.from_config(Config(str(REPO_ROOT / "alembic.ini")))
        assert script.get_revision(REVISION).down_revision == DOWN_REVISION
