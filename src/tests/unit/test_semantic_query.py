"""Unit tests for PT↔EN semantic query synonym expansion (BIN-102)."""

from __future__ import annotations

import pytest

from core.semantic_query import normalize_semantic_query


@pytest.mark.parametrize(
    "query,must_contain",
    [
        ("luxury penthouse", ["cobertura", "luxo"]),
        ("house with backyard", ["quintal"]),
        ("apartment near metro with doorman", ["portaria", "metrô"]),
        ("townhouse with backyard and garage", ["sobrado", "quintal", "garagem"]),
        ("luxury duplex penthouse with garage", ["cobertura", "luxo", "garagem"]),
    ],
)
def test_en_query_expands_pt_counterparts(query: str, must_contain: list[str]) -> None:
    out = normalize_semantic_query(query)
    assert out.startswith(query) or query in out
    folded = out.casefold()
    for term in must_contain:
        assert term.casefold() in folded, f"expected {term!r} in {out!r}"


@pytest.mark.parametrize(
    "query,must_contain",
    [
        ("casa com quintal", ["backyard"]),
        ("cobertura duplex alto padrão com garagem", ["penthouse", "garage"]),
        ("apartamento perto do metrô com portaria", ["doorman", "metro"]),
        ("sobrado com quintal e garagem", ["townhouse", "backyard", "garage"]),
    ],
)
def test_pt_query_expands_en_counterparts(query: str, must_contain: list[str]) -> None:
    out = normalize_semantic_query(query)
    folded = out.casefold()
    for term in must_contain:
        assert term.casefold() in folded, f"expected {term!r} in {out!r}"


def test_already_bilingual_is_idempotent() -> None:
    bilingual = "luxury penthouse cobertura luxo"
    once = normalize_semantic_query(bilingual)
    twice = normalize_semantic_query(once)
    assert once == twice
    # Original terms preserved; no duplicate append spam
    assert once.lower().count("cobertura") == 1
    assert once.lower().count("penthouse") == 1


def test_empty_and_no_match_passthrough() -> None:
    assert normalize_semantic_query("") == ""
    assert normalize_semantic_query("   ") == ""
    assert normalize_semantic_query("savassi 2 bedrooms") == "savassi 2 bedrooms"


def test_preserves_user_words() -> None:
    q = "Luxury Penthouse near park"
    out = normalize_semantic_query(q)
    assert "Luxury Penthouse near park" in out or out.startswith("Luxury Penthouse")
    assert "cobertura" in out.casefold()
