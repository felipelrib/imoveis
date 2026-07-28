"""Unit tests for listing_type / price_type PT→EN synonym normalization (BIN-100)."""

from __future__ import annotations

import pytest

from api.properties import PropertyExportFilters, PropertyListFilters
from core.listing_type import normalize_listing_type, normalize_price_type


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("rent", "rent"),
        ("Rent", "rent"),
        ("aluguel", "rent"),
        ("Aluguel", "rent"),
        ("alugar", "rent"),
        ("sale", "sale"),
        ("venda", "sale"),
        ("Venda", "sale"),
        ("vender", "sale"),
        ("comprar", "sale"),
        ("both", "both"),
        ("ambos", "both"),
        ("", None),
        (None, None),
        ("unknown", None),
    ],
)
def test_normalize_listing_type(raw, expected):
    assert normalize_listing_type(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("rent", "rent"),
        ("aluguel", "rent"),
        ("sale", "sale"),
        ("venda", "sale"),
        ("comprar", "sale"),
        ("both", None),
        ("ambos", None),
        ("", None),
        (None, None),
        ("unknown", None),
    ],
)
def test_normalize_price_type(raw, expected):
    assert normalize_price_type(raw) == expected


def test_property_list_filters_accepts_pt_listing_type_aliases():
    filters = PropertyListFilters(listing_type="aluguel", price_type="venda")
    assert filters.listing_type == "rent"
    assert filters.price_type == "sale"


def test_property_list_filters_accepts_ambos_as_both():
    filters = PropertyListFilters(listing_type="ambos")
    assert filters.listing_type == "both"


def test_property_export_filters_accepts_pt_aliases():
    filters = PropertyExportFilters(listing_type="venda", price_type="aluguel")
    assert filters.listing_type == "sale"
    assert filters.price_type == "rent"


def test_property_list_filters_rejects_unknown_listing_type():
    with pytest.raises(Exception):
        PropertyListFilters(listing_type="unknown-type")
