"""Unit tests for geo allowlist (BIN-68)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.entities import PropertyCandidate
from core.geo_allowlist import extract_city_state, passes_geo_allowlist


@pytest.mark.unit
class TestGeoAllowlist:
    def test_rejects_porto_alegre(self):
        cand = PropertyCandidate(
            platform="olx",
            platform_id="poa-1",
            price=3000.0,
            address="Rua X, Centro, Porto Alegre - RS",
            props_json={"city": "Porto Alegre", "state": "RS"},
        )
        ok, reason = passes_geo_allowlist(
            cand, cities=["Belo Horizonte"], states=["MG"], enabled=True
        )
        assert ok is False
        assert reason and "city_not_allowed" in reason

    def test_allows_belo_horizonte(self):
        cand = PropertyCandidate(
            platform="olx",
            platform_id="bh-1",
            price=3000.0,
            address="Savassi, Belo Horizonte - MG",
            props_json={"city": "Belo Horizonte", "state": "MG"},
        )
        ok, reason = passes_geo_allowlist(
            cand, cities=["Belo Horizonte"], states=["MG"], enabled=True
        )
        assert ok is True
        assert reason is None

    def test_accent_insensitive_city(self):
        cand = SimpleNamespace(
            props_json={"city": "Belo Horizonte", "state": "mg"},
            address=None,
        )
        ok, _ = passes_geo_allowlist(
            cand, cities=["belo horizonte"], states=["MG"], enabled=True
        )
        assert ok is True

    def test_unknown_city_allowed(self):
        cand = PropertyCandidate(
            platform="olx",
            platform_id="unk-1",
            price=3000.0,
            address="Some street",
            props_json={},
        )
        ok, _ = passes_geo_allowlist(
            cand, cities=["Belo Horizonte"], states=["MG"], enabled=True
        )
        assert ok is True

    def test_disabled_allows_all(self):
        cand = PropertyCandidate(
            platform="olx",
            platform_id="poa-2",
            price=3000.0,
            props_json={"city": "Porto Alegre", "state": "RS"},
        )
        ok, _ = passes_geo_allowlist(
            cand, cities=["Belo Horizonte"], states=["MG"], enabled=False
        )
        assert ok is True

    def test_bh_alias_allowed(self):
        cand = SimpleNamespace(
            props_json={"city": "BH", "state": "MG"},
            address=None,
        )
        ok, _ = passes_geo_allowlist(
            cand, cities=["Belo Horizonte"], states=["MG"], enabled=True
        )
        assert ok is True

    def test_extract_from_address_tail(self):
        cand = SimpleNamespace(
            props_json={},
            address="Rua A, Centro, Porto Alegre - RS",
        )
        city, state = extract_city_state(cand)
        assert city == "Porto Alegre"
        assert state == "RS"
