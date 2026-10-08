"""
Integration tests for PropertyListing persistence through the dedupe pipeline.

Tests that scraping a property creates the correct listing rows in the
property_listings table and that the API subqueries return them.

Run with: pytest src/tests/integration/test_listings_e2e.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from adapters.db.models import Property, PropertyListing
from core.dedupe import match_or_create_property, repopulate_listing_costs
from core.entities import PropertyCandidate
from core.listing_cost import build_cost_source
from tests.db_isolation import assert_wipe_safe_database_url

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture()
def session(wipe_safe_db_session):
    """DB session on the isolated test database (BIN-71)."""
    yield wipe_safe_db_session


def _make_candidate(**overrides) -> PropertyCandidate:
    """Build a PropertyCandidate with sensible defaults."""
    defaults = dict(
        platform="quintoandar",
        platform_id="qa-test-001",
        title="Apt 2 quartos Savassi",
        description="Lindo apt",
        price=3000.0,
        area_m2=75.0,
        bedrooms=2,
        bathrooms=1,
        parking=1,
        location={"lat": -19.92, "lon": -43.94},
        address="Rua Paraíba 100, Belo Horizonte",
        image_urls=["https://example.com/img1.jpg"],
        props_json={"type": "apartment", "neighborhood": "Savassi"},
        currency="BRL",
        listings=[],
    )
    defaults.update(overrides)
    return PropertyCandidate(**defaults)


class TestListingPersistence:
    """End-to-end tests for property_listings writes through dedupe."""

    def test_new_property_persists_listing(self, session):
        """Creating a new property should also create a property_listings row."""
        candidate = _make_candidate(
            listings=[
                {
                    "platform": "quintoandar",
                    "platform_listing_id": "qa-test-001",
                    "listing_type": "rent",
                    "price": 3000.0,
                    "currency": "BRL",
                    "url": "https://www.quintoandar.com.br/imovel/qa-test-001",
                }
            ]
        )
        result = match_or_create_property(session, candidate)
        session.flush()

        assert result.action == "created"

        listings = session.query(PropertyListing).all()
        assert len(listings) == 1
        assert str(listings[0].property_id) == result.property_id
        assert listings[0].platform == "quintoandar"
        assert listings[0].listing_type == "rent"
        assert listings[0].price == pytest.approx(3000.0)

    def test_update_property_upserts_listings(self, session):
        """Updating an existing property should upsert (not duplicate) listings."""
        candidate = _make_candidate(
            listings=[
                {
                    "platform": "quintoandar",
                    "platform_listing_id": "qa-test-001",
                    "listing_type": "rent",
                    "price": 3000.0,
                    "currency": "BRL",
                    "url": "https://www.quintoandar.com.br/imovel/qa-test-001",
                }
            ]
        )
        result1 = match_or_create_property(session, candidate)
        session.flush()

        # Re-scrape the same property (e.g. price changed)
        candidate2 = _make_candidate(
            listings=[
                {
                    "platform": "quintoandar",
                    "platform_listing_id": "qa-test-001",
                    "listing_type": "rent",
                    "price": 3500.0,
                    "currency": "BRL",
                    "url": "https://www.quintoandar.com.br/imovel/qa-test-001",
                }
            ]
        )
        result2 = match_or_create_property(session, candidate2)
        session.flush()

        assert result2.action == "updated"
        assert result2.property_id == result1.property_id

        # Should still be 1 listing row (updated, not duplicated)
        listings = session.query(PropertyListing).filter_by(property_id=result1.property_id).all()
        assert len(listings) == 1
        assert listings[0].price == pytest.approx(3500.0)

    def test_dual_listing_rent_and_sale(self, session):
        """A property with both rent and sale listings should create two rows."""
        candidate = _make_candidate(
            listings=[
                {
                    "platform": "quintoandar",
                    "platform_listing_id": "qa-test-002",
                    "listing_type": "rent",
                    "price": 3000.0,
                    "currency": "BRL",
                    "url": "https://www.quintoandar.com.br/imovel/qa-test-002",
                },
                {
                    "platform": "quintoandar",
                    "platform_listing_id": "qa-test-002",
                    "listing_type": "sale",
                    "price": 600000.0,
                    "currency": "BRL",
                    "url": "https://www.quintoandar.com.br/imovel/qa-test-002",
                },
            ]
        )
        result = match_or_create_property(session, candidate)
        session.flush()

        assert result.action == "created"

        listings = session.query(PropertyListing).filter_by(property_id=result.property_id).all()
        assert len(listings) == 2
        types = {listing.listing_type for listing in listings}
        assert types == {"rent", "sale"}

    def test_empty_listings_does_not_fail(self, session):
        """A property with no listings should still be created without error."""
        candidate = _make_candidate(listings=[])
        result = match_or_create_property(session, candidate)
        session.flush()

        assert result.action == "created"
        listings = session.query(PropertyListing).filter_by(property_id=result.property_id).all()
        assert len(listings) == 0

    def test_no_listings_attribute_does_not_fail(self, session):
        """A property where listings is None should still be created."""
        candidate = PropertyCandidate(
            platform="quintoandar",
            platform_id="qa-test-003",
            title="Studio minimal",
            price=1500.0,
            location=None,
            props_json={},
        )
        result = match_or_create_property(session, candidate)
        session.flush()

        assert result.action == "created"
        assert result.property_id is not None


class TestDescriptionPersistence:
    """Description must round-trip to the DB and survive a blank re-scrape (BIN-243).

    The DB was 100% empty because every row predated the description-enrich step,
    not because persistence drops the field. These tests lock the persist
    invariant so a future regression (or an over-eager "blank overwrites" change)
    is caught: a candidate carrying a description is stored non-empty, and a
    later thin re-scrape with an empty description does not wipe it.
    """

    def test_description_round_trips_non_empty(self, session):
        """A candidate with a description persists that text to the DB."""
        candidate = _make_candidate(
            platform_id="qa-desc-001",
            description="Apartamento reformado, andar alto, sol da manhã.",
            listings=[
                {
                    "platform": "quintoandar",
                    "platform_listing_id": "qa-desc-001",
                    "listing_type": "rent",
                    "price": 3000.0,
                    "currency": "BRL",
                    "url": "https://www.quintoandar.com.br/imovel/qa-desc-001",
                }
            ],
        )
        result = match_or_create_property(session, candidate)
        session.flush()

        assert result.action == "created"
        prop = session.get(Property, result.property_id)
        assert prop is not None
        assert prop.description == "Apartamento reformado, andar alto, sol da manhã."

    def test_blank_rescrape_does_not_wipe_stored_description(self, session):
        """A later re-scrape with an empty description must not blank the DB text."""
        original = "Casa ampla com quintal e churrasqueira."
        first = _make_candidate(
            platform_id="qa-desc-002",
            description=original,
            listings=[
                {
                    "platform": "quintoandar",
                    "platform_listing_id": "qa-desc-002",
                    "listing_type": "rent",
                    "price": 2500.0,
                    "currency": "BRL",
                    "url": "https://www.quintoandar.com.br/imovel/qa-desc-002",
                }
            ],
        )
        created = match_or_create_property(session, first)
        session.flush()

        # Re-scrape: thin search payload carries an empty description, price moved.
        blank = _make_candidate(
            platform_id="qa-desc-002",
            description="",
            price=2600.0,
            listings=[
                {
                    "platform": "quintoandar",
                    "platform_listing_id": "qa-desc-002",
                    "listing_type": "rent",
                    "price": 2600.0,
                    "currency": "BRL",
                    "url": "https://www.quintoandar.com.br/imovel/qa-desc-002",
                }
            ],
        )
        updated = match_or_create_property(session, blank)
        session.flush()

        assert updated.property_id == created.property_id
        prop = session.get(Property, created.property_id)
        assert prop.description == original


# ---------------------------------------------------------------------------
# Total Monthly Cost on the persist path (Story 1.1, FR-31, AD-3 / AD-19)
# ---------------------------------------------------------------------------

COST_DOWN_REVISION = "f3a7c81d5e42"
COST_SCHEMA_COLUMNS = {
    "rent_monthly",
    "condo_fee_monthly",
    "iptu_monthly",
    "iptu_periodicity_source",
    "fees_bundled",
    "total_monthly_cost",
    "cost_complete",
    "updated_at",
}
_EPOCH = datetime(2000, 1, 1)


def _zap_rent_listing(platform_listing_id: str, rent, condo_fee, iptu, *, stamped: bool = True) -> dict:
    raw_json: dict = {"fees_bundled": False}
    if stamped:
        raw_json["cost_source"] = build_cost_source(rent=rent, condo_fee=condo_fee, iptu=iptu)
    return {
        "platform": "zapimoveis",
        "platform_listing_id": platform_listing_id,
        "listing_type": "rent",
        "price": float(rent),
        "base_price": float(rent),
        "currency": "BRL",
        "url": f"https://www.zapimoveis.com.br/imovel/id-{platform_listing_id}/",
        "condo_fee": condo_fee,
        "iptu": iptu,
        "raw_json": raw_json,
    }


def _zap_candidate(platform_id: str, listing: dict, **overrides) -> PropertyCandidate:
    return _make_candidate(
        platform="zapimoveis",
        platform_id=platform_id,
        price=listing["price"],
        listings=[listing],
        **overrides,
    )


def _pin_updated_at(session, property_id: str) -> None:
    session.execute(
        text("UPDATE property_listings SET updated_at = :ts WHERE property_id = :pid"),
        {"ts": _EPOCH, "pid": property_id},
    )
    session.flush()
    session.expire_all()


def _listing_row(session, property_id: str) -> PropertyListing:
    session.expire_all()
    return session.query(PropertyListing).filter_by(property_id=property_id).one()


class TestListingCostPersistence:
    """The cost columns round-trip through the migrated Postgres schema."""

    def test_new_listing_persists_cost_columns(self, session):
        listing = _zap_rent_listing("zap-cost-001", 4700, 480.0, 4940.0)
        result = match_or_create_property(session, _zap_candidate("zap-cost-001", listing))
        session.flush()

        row = _listing_row(session, result.property_id)
        assert row.rent_monthly == pytest.approx(4700.0)
        assert row.condo_fee_monthly == pytest.approx(480.0)
        assert row.iptu_monthly == pytest.approx(411.67)
        assert row.iptu_periodicity_source == "annual"
        assert row.fees_bundled is False
        assert row.total_monthly_cost == pytest.approx(5591.67)
        assert row.cost_complete is True
        assert row.updated_at is not None
        # Legacy values are stored as published.
        assert row.price == pytest.approx(4700.0)
        assert row.iptu == pytest.approx(4940.0)
        assert row.raw_json["fees_bundled"] is False

    def test_unknown_component_is_null_and_incomplete(self, session):
        listing = _zap_rent_listing("zap-cost-002", 3500, 650.0, None)
        result = match_or_create_property(session, _zap_candidate("zap-cost-002", listing))
        session.flush()

        row = _listing_row(session, result.property_id)
        assert row.iptu_monthly is None
        assert row.iptu_periodicity_source == "unknown"
        assert row.total_monthly_cost is None
        assert row.cost_complete is False

    def test_updated_at_moves_only_when_a_cost_component_changes(self, session):
        listing = _zap_rent_listing("zap-cost-003", 3500, 400.0, 273.0)
        created = match_or_create_property(session, _zap_candidate("zap-cost-003", listing))
        session.flush()
        _pin_updated_at(session, created.property_id)

        # Rescrape with identical cost figures (title drift forces the listing write).
        same_cost = match_or_create_property(
            session, _zap_candidate("zap-cost-003", listing, title="Apt 2 quartos Savassi reformado")
        )
        session.flush()
        assert same_cost.action == "updated"
        assert _listing_row(session, created.property_id).updated_at == _EPOCH

        # Rescrape with a different condo fee.
        changed = _zap_rent_listing("zap-cost-003", 3500, 450.0, 273.0)
        match_or_create_property(
            session, _zap_candidate("zap-cost-003", changed, title="Apt 2 quartos Savassi novo")
        )
        session.flush()
        row = _listing_row(session, created.property_id)
        assert row.updated_at > _EPOCH
        assert row.total_monthly_cost == pytest.approx(4223.0)

    def test_schema_defaults_and_periodicity_check(self, session):
        """A row written without the cost columns gets the migration defaults; the CHECK holds."""
        created = match_or_create_property(session, _make_candidate(platform_id="qa-cost-004"))
        session.flush()
        insert = text(
            "INSERT INTO property_listings "
            "(property_id, platform, platform_listing_id, listing_type, price) "
            "VALUES (:pid, 'olx', :plid, 'rent', 1000)"
        )
        session.execute(insert, {"pid": created.property_id, "plid": "olx-default"})
        session.flush()

        row = _listing_row(session, created.property_id)
        assert row.iptu_periodicity_source == "unknown"
        assert row.fees_bundled is False
        assert row.cost_complete is False
        assert row.total_monthly_cost is None
        assert row.updated_at is not None

        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.execute(
                    text(
                        "UPDATE property_listings SET iptu_periodicity_source = 'weekly' "
                        "WHERE platform_listing_id = 'olx-default'"
                    )
                )


class TestRepopulateListingCostsPostgres:
    """``repopulate_listing_costs`` over rows stored before the story (UUID keyset, JSON column)."""

    LEGACY_SELECT = text(
        "SELECT id, price, base_price, condo_fee, iptu, raw_json::text AS raw_json "
        "FROM property_listings ORDER BY id"
    )

    def _seed(self, session) -> list[str]:
        """Three pre-story rows (no stamp, default cost columns) on three Properties."""
        rows = [
            ("zap-legacy-1", _zap_rent_listing("zap-legacy-1", 4700, 480.0, 4940.0, stamped=False)),
            ("zap-legacy-2", _zap_rent_listing("zap-legacy-2", 3500, 400.0, 273.0, stamped=False)),
            ("zap-legacy-3", _zap_rent_listing("zap-legacy-3", 4000, 500.0, 1000.0, stamped=False)),
        ]
        property_ids = []
        for index, (platform_id, listing) in enumerate(rows):
            result = match_or_create_property(
                session,
                _zap_candidate(
                    platform_id,
                    listing,
                    location={"lat": -19.80 - index * 0.05, "lon": -43.80 - index * 0.05},
                    address=f"Rua Legada {index}, Belo Horizonte",
                    title=f"Legacy fixture {index}",
                ),
            )
            assert result.action == "created"
            property_ids.append(result.property_id)
        # Rewind to the pre-story state: column defaults, old updated_at.
        session.execute(
            text(
                "UPDATE property_listings SET rent_monthly = NULL, condo_fee_monthly = NULL, "
                "iptu_monthly = NULL, iptu_periodicity_source = 'unknown', fees_bundled = false, "
                "total_monthly_cost = NULL, cost_complete = false, updated_at = :ts"
            ),
            {"ts": _EPOCH},
        )
        session.flush()
        return property_ids

    def _run_all(self, session, batch_size: int) -> dict:
        totals = {"scanned": 0, "updated": 0, "batches": 0}
        after_id = None
        while True:
            stats = repopulate_listing_costs(session, after_id=after_id, batch_size=batch_size)
            session.flush()
            totals["scanned"] += stats["scanned"]
            totals["updated"] += stats["updated"]
            totals["batches"] += 1
            after_id = stats["last_id"]
            if after_id is None:
                return totals

    def test_backfill_is_complete_idempotent_and_leaves_legacy_untouched(self, session):
        self._seed(session)
        before = [tuple(row) for row in session.execute(self.LEGACY_SELECT).fetchall()]

        first = self._run_all(session, batch_size=2)
        assert (first["scanned"], first["updated"]) == (3, 3)
        assert first["batches"] == 2

        session.expire_all()
        by_listing = {
            row.platform_listing_id: row for row in session.query(PropertyListing).all()
        }
        assert by_listing["zap-legacy-1"].iptu_periodicity_source == "annual"
        assert by_listing["zap-legacy-1"].total_monthly_cost == pytest.approx(5591.67)
        assert by_listing["zap-legacy-2"].iptu_periodicity_source == "monthly"
        assert by_listing["zap-legacy-2"].total_monthly_cost == pytest.approx(4173.0)
        assert by_listing["zap-legacy-3"].iptu_periodicity_source == "unknown"
        assert by_listing["zap-legacy-3"].total_monthly_cost is None
        assert by_listing["zap-legacy-3"].cost_complete is False
        # The ambiguous row still gained its rent and condo fee, so all three moved.
        assert all(row.updated_at > _EPOCH for row in by_listing.values())

        session.execute(text("UPDATE property_listings SET updated_at = :ts"), {"ts": _EPOCH})
        second = self._run_all(session, batch_size=2)
        assert (second["scanned"], second["updated"]) == (3, 0)
        session.expire_all()
        assert all(row.updated_at == _EPOCH for row in session.query(PropertyListing).all())

        after = [tuple(row) for row in session.execute(self.LEGACY_SELECT).fetchall()]
        assert after == before


class TestListingCostMigration:
    """AC 1: the migration applies and reverses on a real Postgres."""

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
            rows = conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'property_listings'"
                )
            ).fetchall()
        return {row[0] for row in rows}

    def test_downgrade_then_upgrade_round_trips(self):
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            pytest.skip("DATABASE_URL not set — run through scripts/agent/validate.py")
        assert_wipe_safe_database_url(database_url)
        engine = create_engine(database_url, poolclass=NullPool)
        try:
            assert COST_SCHEMA_COLUMNS <= self._columns(engine)

            try:
                # Explicit target: stays a real round trip after later migrations land.
                down = self._alembic("downgrade", COST_DOWN_REVISION)
                assert down.returncode == 0, down.stderr
                with engine.connect() as conn:
                    assert (
                        conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
                        == COST_DOWN_REVISION
                    )
                assert not (COST_SCHEMA_COLUMNS & self._columns(engine))
            finally:
                up = self._alembic("upgrade", "head")
            assert up.returncode == 0, up.stderr
            assert COST_SCHEMA_COLUMNS <= self._columns(engine)
            with engine.connect() as conn:
                check = conn.execute(
                    text(
                        "SELECT 1 FROM pg_constraint "
                        "WHERE conname = 'ck_property_listings_iptu_periodicity_source'"
                    )
                ).scalar()
            assert check == 1
        finally:
            engine.dispose()

    def test_model_matches_the_migrated_schema(self):
        """AC 1 without a human reading the gate log: no model/migration drift on the table."""
        from adapters.db.models import Base
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext

        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            pytest.skip("DATABASE_URL not set — run through scripts/agent/validate.py")

        def only_listings(name, type_, *_):
            return type_ != "table" or name == "property_listings"

        engine = create_engine(database_url, poolclass=NullPool)
        try:
            with engine.connect() as conn:
                context = MigrationContext.configure(
                    conn,
                    opts={
                        "include_name": lambda name, type_, _parents: only_listings(name, type_),
                        "include_object": lambda _obj, name, type_, *_: only_listings(name, type_),
                    },
                )
                diff = compare_metadata(context, Base.metadata)
        finally:
            engine.dispose()

        drift = [entry for entry in diff if "property_listings" in repr(entry)]
        assert drift == [], drift


class TestRealNormalizeRescrape:
    """A fee-only change on real ``normalize()`` output must reach the cost columns.

    ZapImóveis' headline is the bare rent, so a condo change leaves every price
    equal; the write happens only because the dedupe change check sees the fee.
    """

    @staticmethod
    def _candidate(condominium: int) -> PropertyCandidate:
        from adapters.scrapers.zapimoveis import ZapImoveisScraper

        scraper = ZapImoveisScraper(
            "zapimoveis",
            {
                "rate_limit": 20,
                "jitter_min": 0,
                "jitter_max": 0.1,
                "extra": {"city_slug": "mg+belo-horizonte"},
            },
        )
        raw = {
            "id": "900000099",
            "title": "Apartamento para alugar",
            "href": "https://www.zapimoveis.com.br/imovel/aluguel-apartamento-id-900000099/",
            "prices": {
                "rental": {"value": 3500, "condominium": condominium, "iptu": 273},
                "sale": None,
            },
            "address": {
                "city": "Belo Horizonte",
                "stateAcronym": "MG",
                "neighborhood": "Savassi",
                "coordinates": {"latitude": -19.9, "longitude": -43.9},
            },
            "amenities": {"usableAreas": [75], "bedrooms": [2], "bathrooms": [1]},
            "medias": {"images": ["https://example.com/a.jpg"]},
            "unitType": "APARTMENT",
        }
        return PropertyCandidate(**scraper.normalize(raw))

    def test_fee_only_change_updates_cost_and_updated_at(self, session):
        created = match_or_create_property(session, self._candidate(400))
        session.flush()
        assert _listing_row(session, created.property_id).total_monthly_cost == pytest.approx(4173.0)
        _pin_updated_at(session, created.property_id)

        unchanged = match_or_create_property(session, self._candidate(400))
        session.flush()
        assert unchanged.action == "noop"
        assert _listing_row(session, created.property_id).updated_at == _EPOCH

        changed = match_or_create_property(session, self._candidate(450))
        session.flush()
        assert changed.action == "updated"
        row = _listing_row(session, created.property_id)
        assert row.price == pytest.approx(3500.0)
        assert row.condo_fee_monthly == pytest.approx(450.0)
        assert row.total_monthly_cost == pytest.approx(4223.0)
        assert row.updated_at > _EPOCH
