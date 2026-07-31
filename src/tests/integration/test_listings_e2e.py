"""
Integration tests for PropertyListing persistence through the dedupe pipeline.

Tests that scraping a property creates the correct listing rows in the
property_listings table and that the API subqueries return them.

Run with: pytest src/tests/integration/test_listings_e2e.py -v
"""

from __future__ import annotations

import pytest

from adapters.db.models import Property, PropertyListing
from core.dedupe import match_or_create_property
from core.entities import PropertyCandidate


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
