"""Unit tests for PropertyListing upsert logic in dedupe.py.

Uses raw DDL to create SQLite tables matching the real schema but without
GeoAlchemy2 geometry columns, so tests run without PostGIS.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from core.dedupe import _upsert_listings

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
    raw_json TEXT,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    active BOOLEAN DEFAULT 1
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
