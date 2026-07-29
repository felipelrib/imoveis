"""Unit tests for Fogo Cruzado geographic coverage lock (BIN-120)."""

from __future__ import annotations

import pytest

from core.fogo_cruzado_coverage import (
    COVERED_STATE_CODES,
    FogoCruzadoCoverageError,
    assert_supported_for_overlay,
    supports_state,
)


@pytest.mark.parametrize(
    "state",
    ["RJ", "PE", "BA", "PA", "rj", "pernambuco", "Bahia", "Pará", "Para"],
)
def test_supports_covered_states(state: str) -> None:
    assert supports_state(state) is True


@pytest.mark.parametrize(
    "state",
    ["MG", "SP", "mg", "sp", "Minas Gerais", "São Paulo", "Sao Paulo"],
)
def test_rejects_operator_cities_states(state: str) -> None:
    assert supports_state(state) is False


def test_covered_codes_are_rj_pe_ba_pa_only() -> None:
    assert COVERED_STATE_CODES == frozenset({"RJ", "PE", "BA", "PA"})


@pytest.mark.parametrize("state", ["MG", "SP", "Minas Gerais", "São Paulo"])
def test_assert_supported_raises_for_mg_sp(state: str) -> None:
    with pytest.raises(FogoCruzadoCoverageError, match="not covered"):
        assert_supported_for_overlay(state)


def test_assert_supported_passes_for_covered() -> None:
    assert_supported_for_overlay("RJ")


def test_supports_state_blank_is_false() -> None:
    assert supports_state("") is False
    assert supports_state("   ") is False
