"""Unit tests for PropertyListing upsert logic in dedupe.py.

Uses raw DDL to create SQLite tables matching the real schema but without
GeoAlchemy2 geometry columns, so tests run without PostGIS.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from core.dedupe import _upsert_listings, repopulate_listing_costs
from core.listing_cost import build_cost_source

# ---------------------------------------------------------------------------
# Raw DDL for properties + property_listings, matching the real schema
# but without Geometry columns so SQLite can create them.
# ---------------------------------------------------------------------------
_DDL_CREATE = """
CREATE TABLE IF NOT EXISTS properties (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    platform_id TEXT NOT NULL,
    title TEXT,
    description TEXT,
    price REAL NOT NULL,
    currency TEXT(3),
    area_m2 REAL,
    bedrooms INTEGER,
    bathrooms INTEGER,
    parking INTEGER,
    address TEXT,
    image_urls TEXT,
    props_json TEXT,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    active BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS property_listings (
    id TEXT PRIMARY KEY,
    property_id TEXT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    platform_listing_id TEXT NOT NULL,
    listing_type TEXT NOT NULL,
    price REAL NOT NULL,
    currency TEXT(3),
    url TEXT,
    is_furnished BOOLEAN,
    accepts_pets BOOLEAN,
    condo_fee REAL,
    iptu REAL,
    base_price REAL,
    raw_json TEXT,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    active BOOLEAN DEFAULT 1,
    rent_monthly REAL,
    condo_fee_monthly REAL,
    iptu_monthly REAL,
    iptu_periodicity_source TEXT NOT NULL DEFAULT 'unknown'
        CHECK (iptu_periodicity_source IN ('monthly', 'annual', 'unknown')),
    fees_bundled BOOLEAN NOT NULL DEFAULT 0,
    total_monthly_cost REAL,
    cost_complete BOOLEAN NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS price_history (
    id TEXT PRIMARY KEY,
    property_id TEXT NOT NULL,
    listing_type TEXT NOT NULL DEFAULT 'sale',
    platform TEXT,
    property_listing_id TEXT,
    price REAL NOT NULL,
    start_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    end_ts TIMESTAMP
);
"""


@pytest.fixture()
def db_session():
    """Create an in-memory SQLite session with matching tables."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    with engine.connect() as conn:
        for stmt in _DDL_CREATE.split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(text(stmt))
        conn.commit()

    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def sample_property(db_session):
    """Insert and return a sample Property row."""
    prop_id = str(uuid.uuid4())
    db_session.execute(
        text(
            "INSERT INTO properties (id, platform, platform_id, title, price, currency, "
            "area_m2, bedrooms, bathrooms, parking, active) "
            "VALUES (:id, :platform, :platform_id, :title, :price, :currency, "
            ":area_m2, :bedrooms, :bathrooms, :parking, :active)"
        ),
        {
            "id": prop_id,
            "platform": "quintoandar",
            "platform_id": "qa-12345",
            "title": "Apt 2 quartos Savassi",
            "price": 2500.0,
            "currency": "BRL",
            "area_m2": 70.0,
            "bedrooms": 2,
            "bathrooms": 1,
            "parking": 1,
            "active": True,
        },
    )
    db_session.flush()

    class _Prop:
        def __init__(self, id_):
            self.id = id_

    return _Prop(prop_id)


def _make_listing(
    platform: str = "quintoandar",
    platform_listing_id: str = "qa-12345",
    listing_type: str = "rent",
    price: float = 2500.0,
    **extra,
) -> dict:
    """Helper to build a listing dict matching scraper normalizer output."""
    d = {
        "platform": platform,
        "platform_listing_id": platform_listing_id,
        "listing_type": listing_type,
        "price": price,
        "currency": "BRL",
        "url": f"https://www.quintoandar.com.br/imovel/{platform_listing_id}",
        "is_furnished": None,
        "accepts_pets": None,
        "condo_fee": None,
        "iptu": None,
    }
    d.update(extra)
    return d


class TestUpsertListings:

    def test_creates_new_listing(self, db_session, sample_property):
        """A new listing dict should insert a PropertyListing row."""
        _upsert_listings(db_session, sample_property.id, [_make_listing()])
        db_session.commit()

        rows = db_session.execute(text("SELECT * FROM property_listings")).fetchall()
        assert len(rows) == 1

    def test_creates_dual_listings_rent_and_sale(self, db_session, sample_property):
        """A dual rent+sale property should create two distinct rows."""
        _upsert_listings(
            db_session,
            sample_property.id,
            [
                _make_listing(listing_type="rent", price=2500.0),
                _make_listing(listing_type="sale", price=500000.0),
            ],
        )
        db_session.commit()

        rows = db_session.execute(text("SELECT * FROM property_listings")).fetchall()
        assert len(rows) == 2

    def test_idempotent_on_duplicate(self, db_session, sample_property):
        """Upserting the same listing twice should update, not duplicate."""
        _upsert_listings(db_session, sample_property.id, [_make_listing()])
        db_session.commit()

        _upsert_listings(db_session, sample_property.id, [_make_listing(price=2800.0)])
        db_session.commit()

        rows = db_session.execute(text("SELECT * FROM property_listings")).fetchall()
        assert len(rows) == 1
        assert rows[0].price == pytest.approx(2800.0)

    def test_empty_listings_is_noop(self, db_session, sample_property):
        """Passing an empty list should not create any rows."""
        _upsert_listings(db_session, sample_property.id, [])
        db_session.commit()
        rows = db_session.execute(text("SELECT * FROM property_listings")).fetchall()
        assert len(rows) == 0

    def test_preserves_first_seen_on_update(self, db_session, sample_property):
        """Updating an existing listing should NOT change first_seen."""
        _upsert_listings(db_session, sample_property.id, [_make_listing()])
        db_session.commit()

        original = db_session.execute(text("SELECT first_seen FROM property_listings")).one().first_seen

        _upsert_listings(db_session, sample_property.id, [_make_listing(price=3000.0)])
        db_session.commit()

        updated = db_session.execute(text("SELECT * FROM property_listings")).one()
        assert updated.first_seen == original
        assert updated.price == pytest.approx(3000.0)

    def test_lists_from_different_platforms_are_separate(self, db_session, sample_property):
        """Listings from different platforms should be distinct rows."""
        _upsert_listings(
            db_session,
            sample_property.id,
            [
                _make_listing(
                    platform="quintoandar",
                    platform_listing_id="qa-111",
                    listing_type="rent",
                    price=2500,
                ),
                _make_listing(
                    platform="olx",
                    platform_listing_id="olx-222",
                    listing_type="rent",
                    price=2600,
                ),
            ],
        )
        db_session.commit()

        rows = db_session.execute(text("SELECT * FROM property_listings")).fetchall()
        assert len(rows) == 2

    def test_extra_fields_persisted(self, db_session, sample_property):
        """Extra fields like condo_fee and iptu should be stored."""
        _upsert_listings(
            db_session,
            sample_property.id,
            [_make_listing(condo_fee=800.0, iptu=150.0, is_furnished=True)],
        )
        db_session.commit()

        row = db_session.execute(text("SELECT * FROM property_listings")).one()
        assert row.condo_fee == pytest.approx(800.0)
        assert row.iptu == pytest.approx(150.0)
        assert row.is_furnished == 1

    def test_base_price_persisted(self, db_session, sample_property):
        """base_price (BIN-67) is stored on upsert."""
        _upsert_listings(
            db_session,
            sample_property.id,
            [_make_listing(base_price=2200.0, price=2850.0)],
        )
        db_session.commit()
        row = db_session.execute(text("SELECT base_price, price FROM property_listings")).one()
        assert row.base_price == pytest.approx(2200.0)
        assert row.price == pytest.approx(2850.0)


# ---------------------------------------------------------------------------
# Total Monthly Cost on the persist path (Story 1.1, FR-31, AD-3 / AD-19)
# ---------------------------------------------------------------------------

_COST_SELECT = (
    "SELECT rent_monthly, condo_fee_monthly, iptu_monthly, iptu_periodicity_source, "
    "fees_bundled, total_monthly_cost, cost_complete, updated_at, active, "
    "price, base_price, condo_fee, iptu, raw_json FROM property_listings"
)
_EPOCH = "2000-01-01 00:00:00"


def _stamped(rent, condo_fee, iptu, **extra) -> dict:
    """A ZapImoveis-shaped rent listing carrying the scraper cost stamp."""
    listing = _make_listing(
        platform="zapimoveis",
        platform_listing_id="zap-1",
        price=float(rent),
        base_price=float(rent),
        condo_fee=condo_fee,
        iptu=iptu,
        raw_json={
            "fees_bundled": False,
            "cost_source": build_cost_source(rent=rent, condo_fee=condo_fee, iptu=iptu),
        },
    )
    listing.update(extra)
    return listing


def _one(db_session):
    return db_session.execute(text(_COST_SELECT)).one()


def _set_updated_at(db_session, value: str = _EPOCH) -> str:
    """Pin ``updated_at`` to a sentinel so any later movement is unambiguous."""
    db_session.execute(text("UPDATE property_listings SET updated_at = :v"), {"v": value})
    db_session.commit()
    return value


class TestUpsertListingCost:
    def test_insert_writes_the_cost_columns(self, db_session, sample_property):
        _upsert_listings(db_session, sample_property.id, [_stamped(3500, 400.0, 273.0)])
        db_session.commit()

        row = _one(db_session)
        assert row.rent_monthly == pytest.approx(3500.0)
        assert row.condo_fee_monthly == pytest.approx(400.0)
        assert row.iptu_monthly == pytest.approx(273.0)
        assert row.iptu_periodicity_source == "monthly"
        assert not row.fees_bundled
        assert row.total_monthly_cost == pytest.approx(4173.0)
        assert row.cost_complete
        assert row.updated_at is not None

    def test_insert_with_unknown_component_stores_null_not_zero(self, db_session, sample_property):
        _upsert_listings(db_session, sample_property.id, [_stamped(3500, 650.0, 0.0)])
        db_session.commit()

        row = _one(db_session)
        assert row.iptu_monthly is None
        assert row.iptu_periodicity_source == "unknown"
        assert row.total_monthly_cost is None
        assert not row.cost_complete
        # Legacy columns keep what the platform mapping produced.
        assert row.iptu == pytest.approx(0.0)
        assert row.condo_fee == pytest.approx(650.0)

    def test_unstamped_listing_persists_incomplete_cost(self, db_session, sample_property):
        """A bare listing dict (no fees) is still written, with an honest unknown."""
        _upsert_listings(db_session, sample_property.id, [_make_listing()])
        db_session.commit()

        row = _one(db_session)
        assert row.condo_fee_monthly is None
        assert row.total_monthly_cost is None
        assert not row.cost_complete
        assert row.iptu_periodicity_source == "unknown"

    def test_update_rewrites_the_cost_columns(self, db_session, sample_property):
        _upsert_listings(db_session, sample_property.id, [_stamped(3500, 400.0, 273.0)])
        db_session.commit()
        _upsert_listings(db_session, sample_property.id, [_stamped(4700, 480.0, 4940.0)])
        db_session.commit()

        row = _one(db_session)
        assert row.rent_monthly == pytest.approx(4700.0)
        assert row.iptu_periodicity_source == "annual"
        assert row.iptu_monthly == pytest.approx(411.67)
        assert row.total_monthly_cost == pytest.approx(5591.67)
        assert row.iptu == pytest.approx(4940.0)  # legacy value as published

    def test_updated_at_unchanged_when_cost_figures_are_identical(self, db_session, sample_property):
        _upsert_listings(db_session, sample_property.id, [_stamped(3500, 400.0, 273.0)])
        db_session.commit()
        sentinel = _set_updated_at(db_session)

        # A non-cost field changes (url); the cost facts do not.
        _upsert_listings(
            db_session,
            sample_property.id,
            [_stamped(3500, 400.0, 273.0, url="https://example.com/new")],
        )
        db_session.commit()

        assert str(_one(db_session).updated_at) == sentinel

    def test_updated_at_advances_when_a_component_changes(self, db_session, sample_property):
        _upsert_listings(db_session, sample_property.id, [_stamped(3500, 400.0, 273.0)])
        db_session.commit()
        sentinel = _set_updated_at(db_session)

        _upsert_listings(db_session, sample_property.id, [_stamped(3500, 450.0, 273.0)])
        db_session.commit()

        row = _one(db_session)
        assert str(row.updated_at) > sentinel
        assert row.total_monthly_cost == pytest.approx(4223.0)

    def test_updated_at_advances_when_a_component_becomes_unknown(self, db_session, sample_property):
        _upsert_listings(db_session, sample_property.id, [_stamped(3500, 400.0, 273.0)])
        db_session.commit()
        sentinel = _set_updated_at(db_session)

        _upsert_listings(db_session, sample_property.id, [_stamped(3500, 400.0, None)])
        db_session.commit()

        row = _one(db_session)
        assert str(row.updated_at) > sentinel
        assert row.total_monthly_cost is None

    def test_updated_at_advances_when_listing_is_reactivated(self, db_session, sample_property):
        _upsert_listings(db_session, sample_property.id, [_stamped(3500, 400.0, 273.0)])
        db_session.commit()
        db_session.execute(text("UPDATE property_listings SET active = 0"))
        sentinel = _set_updated_at(db_session)

        _upsert_listings(db_session, sample_property.id, [_stamped(3500, 400.0, 273.0)])
        db_session.commit()

        row = _one(db_session)
        assert row.active
        assert str(row.updated_at) > sentinel


def _insert_pre_story_row(db_session, property_id: str, listing_id: str, **columns) -> None:
    """Insert a row the way pre-story code left it: legacy columns only."""
    values = {
        "id": listing_id,
        "pid": property_id,
        "platform": "zapimoveis",
        "plid": listing_id,
        "lt": "rent",
        "price": 3500.0,
        "base_price": None,
        "condo_fee": None,
        "iptu": None,
        "raw_json": "{}",
        "updated_at": _EPOCH,
    }
    values.update(columns)
    db_session.execute(
        text(
            "INSERT INTO property_listings "
            "(id, property_id, platform, platform_listing_id, listing_type, price, "
            "base_price, condo_fee, iptu, raw_json, updated_at) "
            "VALUES (:id, :pid, :platform, :plid, :lt, :price, "
            ":base_price, :condo_fee, :iptu, :raw_json, :updated_at)"
        ),
        values,
    )


_LEGACY_SELECT = (
    "SELECT id, price, base_price, condo_fee, iptu, raw_json FROM property_listings ORDER BY id"
)
_COST_BY_ID_SELECT = (
    "SELECT id, rent_monthly, condo_fee_monthly, iptu_monthly, iptu_periodicity_source, "
    "fees_bundled, total_monthly_cost, cost_complete, updated_at FROM property_listings"
)


def _seed_pre_story_rows(db_session, property_id: str) -> None:
    _insert_pre_story_row(
        db_session, property_id, "a-zap", price=4700.0, base_price=4700.0,
        condo_fee=480.0, iptu=4940.0, raw_json='{"fees_bundled": false}',
    )
    _insert_pre_story_row(
        db_session, property_id, "b-olx", platform="olx", price=4150.0, base_price=3500.0,
        condo_fee=650.0, iptu=0.0, raw_json='{"fees_bundled": false}',
    )
    _insert_pre_story_row(
        db_session, property_id, "c-qa", platform="quintoandar", price=857.0, base_price=800.0,
        condo_fee=57.0, iptu=None,
        raw_json=(
            '{"partial_price": 800, "fees_bundled": true, '
            '"fees_note": "condoIptu is a bundled condo+IPTU field"}'
        ),
    )
    _insert_pre_story_row(
        db_session, property_id, "d-malformed", price=3500.0, condo_fee=400.0, iptu=273.0,
        raw_json="{not json",
    )
    db_session.commit()


def _costs_by_id(db_session) -> dict:
    return {row.id: row for row in db_session.execute(text(_COST_BY_ID_SELECT)).fetchall()}


class TestRepopulateListingCosts:
    def test_populates_pre_story_rows(self, db_session, sample_property):
        _seed_pre_story_rows(db_session, sample_property.id)

        stats = repopulate_listing_costs(db_session, after_id=None, batch_size=100)
        db_session.commit()

        assert stats == {"scanned": 4, "updated": 4, "last_id": None}
        costs = _costs_by_id(db_session)
        assert costs["a-zap"].iptu_periodicity_source == "annual"
        assert costs["a-zap"].total_monthly_cost == pytest.approx(5591.67)
        assert costs["b-olx"].rent_monthly == pytest.approx(3500.0)
        assert costs["b-olx"].iptu_monthly is None
        assert costs["b-olx"].total_monthly_cost is None
        assert costs["c-qa"].fees_bundled
        assert costs["c-qa"].total_monthly_cost == pytest.approx(857.0)
        assert costs["d-malformed"].total_monthly_cost == pytest.approx(4173.0)
        assert all(str(row.updated_at) > _EPOCH for row in costs.values())

    def test_second_run_updates_nothing_and_leaves_updated_at(self, db_session, sample_property):
        _seed_pre_story_rows(db_session, sample_property.id)
        repopulate_listing_costs(db_session, after_id=None, batch_size=100)
        db_session.commit()
        sentinel = _set_updated_at(db_session, "2001-01-01 00:00:00")

        stats = repopulate_listing_costs(db_session, after_id=None, batch_size=100)
        db_session.commit()

        assert stats == {"scanned": 4, "updated": 0, "last_id": None}
        assert {str(row.updated_at) for row in _costs_by_id(db_session).values()} == {sentinel}

    def test_legacy_columns_are_byte_identical(self, db_session, sample_property):
        _seed_pre_story_rows(db_session, sample_property.id)
        before = [tuple(row) for row in db_session.execute(text(_LEGACY_SELECT)).fetchall()]

        repopulate_listing_costs(db_session, after_id=None, batch_size=100)
        db_session.commit()

        after = [tuple(row) for row in db_session.execute(text(_LEGACY_SELECT)).fetchall()]
        assert after == before

    def test_keyset_batches_cover_every_row_once(self, db_session, sample_property):
        _seed_pre_story_rows(db_session, sample_property.id)

        scanned, updated, after_id, batches = 0, 0, None, 0
        while True:
            stats = repopulate_listing_costs(db_session, after_id=after_id, batch_size=2)
            db_session.commit()
            batches += 1
            scanned += stats["scanned"]
            updated += stats["updated"]
            after_id = stats["last_id"]
            if after_id is None:
                break

        # 4 rows in batches of 2: two full batches, then the empty one that ends the scan.
        assert (scanned, updated, batches) == (4, 4, 3)

    def test_row_already_matching_is_skipped(self, db_session, sample_property):
        """A pre-story row whose mapping is all-unknown already equals the column defaults."""
        _insert_pre_story_row(db_session, sample_property.id, "olx-bare", platform="olx")
        db_session.commit()

        stats = repopulate_listing_costs(db_session, after_id=None, batch_size=10)

        assert stats == {"scanned": 1, "updated": 0, "last_id": None}

    def test_matches_what_the_persist_path_writes(self, db_session, sample_property):
        """Stored row with no stamp == fresh persist of the same figures."""
        _upsert_listings(db_session, sample_property.id, [_stamped(4700, 480.0, 4940.0)])
        _insert_pre_story_row(
            db_session, sample_property.id, "legacy", price=4700.0, base_price=4700.0,
            condo_fee=480.0, iptu=4940.0, raw_json='{"fees_bundled": false}',
        )
        db_session.commit()

        repopulate_listing_costs(db_session, after_id=None, batch_size=10)
        db_session.commit()

        rows = db_session.execute(
            text(
                "SELECT rent_monthly, condo_fee_monthly, iptu_monthly, iptu_periodicity_source, "
                "fees_bundled, total_monthly_cost, cost_complete FROM property_listings"
            )
        ).fetchall()
        assert len(rows) == 2
        assert tuple(rows[0]) == tuple(rows[1])

    def test_rejects_non_positive_batch_size(self, db_session):
        with pytest.raises(ValueError, match="batch_size"):
            repopulate_listing_costs(db_session, after_id=None, batch_size=0)


def _labelled_cases() -> dict:
    from tests.unit.test_listing_cost_fixtures import CASES

    return CASES


class TestLabelledFixturesPersist:
    """Raw payload -> real ``normalize()`` -> ``_upsert_listings`` -> stored columns."""

    @pytest.mark.parametrize("case_id", sorted(_labelled_cases()))
    def test_stored_row_matches_the_label(self, db_session, sample_property, case_id):
        from tests.unit.test_listing_cost_fixtures import _normalized_listing

        case = _labelled_cases()[case_id]
        _upsert_listings(db_session, sample_property.id, [_normalized_listing(case)])
        db_session.commit()

        row = _one(db_session)
        for column, expected in case["expected"].items():
            stored = getattr(row, column)
            if isinstance(expected, bool):
                assert bool(stored) is expected, (case_id, column)
            elif isinstance(expected, float):
                assert stored == pytest.approx(expected), (case_id, column)
            else:
                assert stored == expected, (case_id, column)
        assert row.price == pytest.approx(case["headline_price"])
