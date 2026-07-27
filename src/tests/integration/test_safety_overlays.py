"""Integration: apply safety rate overlays onto neighbourhoods (BIN-92)."""

from __future__ import annotations

from pathlib import Path

import pytest

from adapters.db.models import Neighborhood
from core.safety_overlay import (
    DEFAULT_PROVIDER,
    load_and_apply_safety_rates,
    parse_safety_rates,
)

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "safety"
    / "sp_safety_rates_tiny.yaml"
)
BH_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "safety"
    / "bh_safety_rates_tiny.yaml"
)
BH_GENERATED = (
    Path(__file__).resolve().parents[3] / "configs" / "bh_safety_rates.yaml"
)
FIXED_TS = "2026-07-27T12:00:00+00:00"


@pytest.fixture(scope="function")
def db_session(wipe_safe_db_session):
    yield wipe_safe_db_session


def _seed(
    session,
    *,
    name: str,
    city: str = "São Paulo",
    state: str = "SP",
    **kwargs,
):
    row = Neighborhood(name=name, city=city, state=state, **kwargs)
    session.add(row)
    session.flush()
    return row


@pytest.mark.integration
class TestApplySafetyOverlays:
    def test_sets_scores_meta_and_skips_unknown(self, db_session):
        pinheiros = _seed(db_session, name="Pinheiros", amenity_score=0.9)
        moema = _seed(
            db_session,
            name="Moema",
            transit_score=0.8,
            quality_meta={"risk": {"provider": "geojson-overlay"}},
        )
        db_session.commit()

        result = load_and_apply_safety_rates(
            db_session,
            FIXTURE,
            city="São Paulo",
            state="SP",
            refreshed_at=FIXED_TS,
        )
        db_session.commit()

        assert result.updated == 2
        assert result.skipped_unknown == 1  # Unknown Bairro
        assert result.files_skipped_missing == 0

        db_session.refresh(pinheiros)
        db_session.refresh(moema)
        # Pinheiros highest rate → lowest safety; Moema opposite
        assert pinheiros.safety_score == pytest.approx(0.0)
        assert moema.safety_score == pytest.approx(1.0)
        assert pinheiros.amenity_score == pytest.approx(0.9)
        assert moema.transit_score == pytest.approx(0.8)
        assert moema.quality_meta["risk"]["provider"] == "geojson-overlay"
        safety = pinheiros.quality_meta["safety"]
        assert safety["provider"] == DEFAULT_PROVIDER
        assert safety["refreshed_at"] == FIXED_TS
        assert safety["rate_per_100k"] == pytest.approx(200.0)
        assert safety["period_start"] == "2024-01"
        assert "not absolute safety" in safety["attribution"]
        assert db_session.query(Neighborhood).filter_by(
            name="Unknown Bairro"
        ).count() == 0

    def test_idempotent_reload(self, db_session):
        _seed(db_session, name="Pinheiros")
        _seed(db_session, name="Moema")
        db_session.commit()

        first = load_and_apply_safety_rates(
            db_session, FIXTURE, refreshed_at=FIXED_TS
        )
        db_session.commit()
        meta_first = (
            db_session.query(Neighborhood).filter_by(name="Pinheiros").one()
            .quality_meta
        )

        second = load_and_apply_safety_rates(
            db_session, FIXTURE, refreshed_at=FIXED_TS
        )
        db_session.commit()

        assert first.updated == 2
        assert second.updated == 0
        assert second.unchanged == 2
        assert second.skipped_unknown == 1
        meta_second = (
            db_session.query(Neighborhood).filter_by(name="Pinheiros").one()
            .quality_meta
        )
        assert meta_second["safety"]["refreshed_at"] == meta_first["safety"][
            "refreshed_at"
        ]

    def test_missing_file_skipped(self, db_session):
        _seed(db_session, name="Pinheiros")
        db_session.commit()
        result = load_and_apply_safety_rates(
            db_session,
            Path("/nonexistent/sp_crime_rates.yaml"),
            city="São Paulo",
            state="SP",
        )
        assert result.files_skipped_missing == 1
        assert result.updated == 0
        row = db_session.query(Neighborhood).filter_by(name="Pinheiros").one()
        assert row.safety_score is None

    def test_parse_fixture_matches_apply_inputs(self):
        rows = parse_safety_rates(FIXTURE)
        assert {r.name for r in rows} >= {"Pinheiros", "Moema"}


@pytest.mark.integration
class TestApplyBhSafetyOverlays:
    def test_bh_fixture_sets_relative_regional_scores(self, db_session):
        savassi = _seed(
            db_session,
            name="Savassi",
            city="Belo Horizonte",
            state="MG",
            amenity_score=0.9,
        )
        venda_nova = _seed(
            db_session,
            name="Venda Nova",
            city="Belo Horizonte",
            state="MG",
        )
        db_session.commit()

        result = load_and_apply_safety_rates(
            db_session,
            BH_FIXTURE,
            city="Belo Horizonte",
            state="MG",
            default_city="Belo Horizonte",
            default_state="MG",
            refreshed_at=FIXED_TS,
        )
        db_session.commit()

        assert result.updated == 2
        assert result.skipped_unknown == 1
        db_session.refresh(savassi)
        db_session.refresh(venda_nova)
        # Higher regional count → lower safety
        assert savassi.safety_score == pytest.approx(0.0)
        assert venda_nova.safety_score == pytest.approx(1.0)
        assert savassi.amenity_score == pytest.approx(0.9)
        safety = savassi.quality_meta["safety"]
        assert safety["provider"] == "sejusp-mg-regional"
        assert safety["grain"] == "regional"
        assert "not absolute safety" in safety["attribution"]

    def test_generated_bh_rates_apply_to_seeded_subset(self, db_session):
        _seed(db_session, name="Savassi", city="Belo Horizonte", state="MG")
        _seed(db_session, name="Barreiro", city="Belo Horizonte", state="MG")
        db_session.commit()

        result = load_and_apply_safety_rates(
            db_session,
            BH_GENERATED,
            city="Belo Horizonte",
            state="MG",
            default_city="Belo Horizonte",
            default_state="MG",
            refreshed_at=FIXED_TS,
        )
        db_session.commit()
        assert result.updated == 2
        assert result.skipped_unknown == 34  # remaining curated names not seeded
        savassi = (
            db_session.query(Neighborhood)
            .filter_by(name="Savassi", city="Belo Horizonte")
            .one()
        )
        assert savassi.quality_meta["safety"]["provider"] == "sejusp-mg-regional"
