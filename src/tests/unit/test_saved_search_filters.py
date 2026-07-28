"""Unit tests for saved-search EN wire filters (BIN-100)."""

from __future__ import annotations

from api.saved_searches import SavedSearchFilters


def test_camel_case_filters_normalize_to_snake_en_wire():
    filters = SavedSearchFilters.model_validate(
        {
            "sortBy": "price",
            "sortDir": "asc",
            "listingType": "rent",
            "propertyType": "apartment",
            "platform": "olx",
            "maxPrice": "5000",
            "priceType": "rent",
            "minBedrooms": "2",
            "minParking": "1",
            "minScore": "0.5",
            "neighborhood": "Savassi",
            "city": "Belo Horizonte",
            "isFurnished": True,
            "acceptsPets": True,
            "q": "varanda",
        }
    )
    wire = filters.to_wire()
    assert wire == {
        "sort_by": "price",
        "sort_dir": "asc",
        "listing_type": "rent",
        "property_type": "apartment",
        "platform": "olx",
        "max_price": 5000.0,
        "price_type": "rent",
        "min_bedrooms": 2,
        "min_parking": 1,
        "min_score": 0.5,
        "neighborhood": "Savassi",
        "city": "Belo Horizonte",
        "is_furnished": True,
        "accepts_pets": True,
        "q": "varanda",
    }


def test_pt_listing_and_property_aliases_normalize_on_save():
    filters = SavedSearchFilters.model_validate(
        {
            "listing_type": "aluguel",
            "price_type": "venda",
            "property_type": "apartamento",
        }
    )
    wire = filters.to_wire()
    assert wire["listing_type"] == "rent"
    assert wire["price_type"] == "sale"
    assert wire["property_type"] == "apartment"


def test_legacy_furnished_pets_neighbourhood_aliases():
    filters = SavedSearchFilters.model_validate(
        {
            "furnished": True,
            "pets": False,
            "neighbourhood": ["Savassi", "Lourdes"],
        }
    )
    wire = filters.to_wire()
    assert wire["is_furnished"] is True
    assert "accepts_pets" not in wire  # false flags omitted (SPA default)
    assert wire["neighborhood"] == "Savassi,Lourdes"


def test_empty_strings_excluded_from_wire():
    filters = SavedSearchFilters.model_validate(
        {
            "listingType": "both",
            "propertyType": "",
            "platform": "",
            "maxPrice": "",
            "isFurnished": False,
            "acceptsPets": False,
            "q": "",
        }
    )
    wire = filters.to_wire()
    assert wire.get("listing_type") == "both"
    assert "property_type" not in wire
    assert "platform" not in wire
    assert "max_price" not in wire
    assert "is_furnished" not in wire
    assert "accepts_pets" not in wire
    assert "q" not in wire
