"""Unit tests for canonical property-type normalization (BIN-75)."""

from __future__ import annotations

import pytest

from core.property_type import (
    infer_property_type_from_text,
    match_values_for_filter,
    normalize_property_type,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Apartamento", "apartment"),
        ("apartamento", "apartment"),
        ("apartment", "apartment"),
        ("Casa", "house"),
        ("casas", "house"),
        ("CasaCondominio", "condo_house"),
        ("casa em condomínio", "condo_house"),
        ("Studio", "studio"),
        ("kitnet", "studio"),
        ("", None),
        (None, None),
        ("unknown-type", None),
    ],
)
def test_normalize_property_type(raw, expected):
    assert normalize_property_type(raw) == expected


def test_infer_from_title():
    assert infer_property_type_from_text("Apartamento 2 quartos em Savassi") == "apartment"
    assert infer_property_type_from_text("Vendo casa em Cabo Frio") == "house"
    assert infer_property_type_from_text("Cobertura no Itapoã") is None


def test_match_values_include_legacy_aliases():
    values = match_values_for_filter("apartment")
    assert "apartment" in values
    assert "apartamento" in values
    assert "Apartamento".lower() in values
