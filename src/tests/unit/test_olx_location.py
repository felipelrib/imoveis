"""Unit tests for OLX location reconciliation (BIN-72)."""

from __future__ import annotations

import pytest

from core.entities import PropertyCandidate
from core.olx_location import (
    apply_reconcile_to_candidate,
    reconcile_olx_location,
    suspect_location_mismatch,
)

ALLOWED = ["Belo Horizonte", "São Paulo", "Campinas"]
STATES = ["MG", "SP"]
NEIGHBORHOODS = ["Itapoã", "Savassi", "São Tomáz", "Lourdes", "Pampulha", "Sion"]


@pytest.mark.unit
class TestSuspectLocationMismatch:
    def test_itapoa_in_title_vs_sao_tomaz(self):
        suspected, city, nb, reason = suspect_location_mismatch(
            title="Cobertura no Itapoã",
            description="",
            scraped_city="Belo Horizonte",
            scraped_neighborhood="São Tomáz",
            allowed_cities=ALLOWED,
            known_neighborhoods=NEIGHBORHOODS,
        )
        assert suspected is True
        assert nb == "Itapoã"
        assert reason == "neighborhood_mismatch"

    def test_cabo_frio_city_mismatch(self):
        suspected, city, nb, reason = suspect_location_mismatch(
            title="Vendo casa em Cabo Frio - RJ PRÓXIMO PRAIA DO FORTE",
            description="",
            scraped_city="Belo Horizonte",
            scraped_neighborhood="São Tomáz",
            allowed_cities=ALLOWED,
            known_neighborhoods=NEIGHBORHOODS,
        )
        assert suspected is True
        assert city is not None
        assert "cabo" in city.casefold()
        assert reason == "city_mismatch"

    def test_matching_neighborhood_ok(self):
        suspected, *_ = suspect_location_mismatch(
            title="Apto Savassi 2 quartos",
            description="Ótimo imóvel na Savassi",
            scraped_city="Belo Horizonte",
            scraped_neighborhood="Savassi",
            allowed_cities=ALLOWED,
            known_neighborhoods=NEIGHBORHOODS,
        )
        assert suspected is False

    def test_sao_paulo_as_neighborhood_with_sion_title(self):
        suspected, city, nb, reason = suspect_location_mismatch(
            title="Cobertura Duplex 5 quartos Sion",
            description="",
            scraped_city="São Paulo",
            scraped_neighborhood="São Paulo",
            allowed_cities=ALLOWED,
            known_neighborhoods=NEIGHBORHOODS,
        )
        assert suspected is True
        assert reason == "neighborhood_is_city"
        assert nb == "Sion"


@pytest.mark.unit
class TestReconcileOlxLocation:
    def test_heuristic_corrects_neighborhood_without_ai(self):
        result = reconcile_olx_location(
            title="Cobertura no Itapoã",
            description="",
            scraped_city="Belo Horizonte",
            scraped_neighborhood="São Tomáz",
            scraped_state="MG",
            scraped_address="São Tomáz, Belo Horizonte, MG",
            allowed_cities=ALLOWED,
            allowed_states=STATES,
            known_neighborhoods=NEIGHBORHOODS,
            ai_extract=None,
        )
        assert result.action == "corrected"
        assert result.neighborhood == "Itapoã"
        assert result.city == "Belo Horizonte"
        assert result.clear_coords is True
        assert "Itapoã" in (result.address or "")

    def test_sao_paulo_neighborhood_sion_title_becomes_bh(self):
        result = reconcile_olx_location(
            title="Apartamento 4 quartos Sion",
            description="",
            scraped_city="São Paulo",
            scraped_neighborhood="São Paulo",
            scraped_state="MG",
            scraped_address="São Paulo, SP",
            allowed_cities=ALLOWED,
            allowed_states=STATES,
            known_neighborhoods=NEIGHBORHOODS,
            ai_extract=None,
        )
        assert result.action == "corrected"
        assert result.neighborhood == "Sion"
        assert result.city == "Belo Horizonte"
        assert result.reason == "neighborhood_is_city"

    def test_out_of_geo_cabo_frio_with_ai(self):
        def fake_ai(_prompt: str):
            return {
                "city": "Cabo Frio",
                "state": "RJ",
                "neighborhood": None,
                "confidence": 0.95,
                "reason": "title",
            }

        result = reconcile_olx_location(
            title="Vendo casa em Cabo Frio - RJ",
            description="",
            scraped_city="Belo Horizonte",
            scraped_neighborhood="São Tomáz",
            scraped_state="MG",
            scraped_address="São Tomáz, Belo Horizonte, MG",
            allowed_cities=ALLOWED,
            allowed_states=STATES,
            known_neighborhoods=NEIGHBORHOODS,
            ai_extract=fake_ai,
        )
        assert result.action == "out_of_geo"
        assert result.city == "Cabo Frio"

    def test_ai_corrects_when_heuristic_empty_neighborhood(self):
        def fake_ai(_prompt: str):
            return {
                "city": "Belo Horizonte",
                "state": "MG",
                "neighborhood": "Itapoã",
                "confidence": 0.9,
                "reason": "title",
            }

        result = reconcile_olx_location(
            title="Cobertura no Itapoã",
            description="",
            scraped_city="Belo Horizonte",
            scraped_neighborhood=None,
            scraped_state="MG",
            scraped_address="Belo Horizonte, MG",
            allowed_cities=ALLOWED,
            allowed_states=STATES,
            known_neighborhoods=NEIGHBORHOODS,
            ai_extract=fake_ai,
        )
        assert result.action == "corrected"
        assert result.neighborhood == "Itapoã"

    def test_apply_to_candidate_clears_coords(self):
        candidate = PropertyCandidate(
            platform="olx",
            platform_id="1",
            price=250000.0,
            title="Cobertura no Itapoã",
            address="São Tomáz, Belo Horizonte, MG",
            location={"lat": -19.9, "lon": -43.9},
            props_json={
                "city": "Belo Horizonte",
                "state": "MG",
                "neighborhood": "São Tomáz",
            },
        )
        result = reconcile_olx_location(
            title=candidate.title,
            description="",
            scraped_city="Belo Horizonte",
            scraped_neighborhood="São Tomáz",
            scraped_state="MG",
            scraped_address=candidate.address,
            allowed_cities=ALLOWED,
            allowed_states=STATES,
            known_neighborhoods=NEIGHBORHOODS,
        )
        apply_reconcile_to_candidate(candidate, result)
        assert candidate.location is None
        assert candidate.props_json["neighborhood"] == "Itapoã"
        assert candidate.props_json["olx_location_corrected"] is True


def test_reconcile_olx_location_ai_extract_raising_returns_ai_failed():
    """BIN-143: ai_extract errors must not abort backfill/ingest."""

    def _raising_ai(_prompt: str):
        raise RuntimeError("model unavailable")

    result = reconcile_olx_location(
        title="Vendo casa",
        description="",
        scraped_city="Belo Horizonte",
        scraped_neighborhood="Sion",
        scraped_state="MG",
        scraped_address="Sion, Belo Horizonte, MG",
        allowed_cities=ALLOWED,
        allowed_states=STATES,
        known_neighborhoods=NEIGHBORHOODS,
        ai_extract=_raising_ai,
        force_ai=True,
    )
    assert result.action == "ai_failed"
    assert result.city == "Belo Horizonte"
    assert result.neighborhood == "Sion"
