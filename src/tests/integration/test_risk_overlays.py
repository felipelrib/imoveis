"""Integration: apply risk overlays onto neighbourhood polygons (BIN-91)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.neighbourhood_geojson import load_neighbourhood_geojson
from core.neighbourhood_quality import normalize_risk_flags
from core.risk_overlay import (
    RiskOverlayLayer,
    load_and_apply_risk_overlays,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "geo"
NHOOD_FIXTURE = FIXTURES / "bh_neighbourhoods_tiny.geojson"
FLOOD_FIXTURE = FIXTURES / "bh_risk_flood_tiny.geojson"
INDUSTRIAL_FIXTURE = FIXTURES / "bh_risk_industrial_tiny.geojson"

FIXED_TS = "2026-07-27T12:00:00+00:00"


@pytest.fixture(scope="function")
def db_session(wipe_safe_db_session):
    yield wipe_safe_db_session


def _by_name(session):
    from adapters.db.models import Neighborhood

    return {r.name: r for r in session.query(Neighborhood).all()}


@pytest.mark.integration
class TestApplyRiskOverlays:
    def test_intersects_set_flags_and_severity(self, db_session):
        load_neighbourhood_geojson(db_session, NHOOD_FIXTURE)
        db_session.commit()

        layers = [
            RiskOverlayLayer(path=FLOOD_FIXTURE, risk_type="flood_zone"),
            RiskOverlayLayer(
                path=INDUSTRIAL_FIXTURE, risk_type="industrial_adjacent"
            ),
        ]
        result = load_and_apply_risk_overlays(
            db_session,
            layers,
            city="Belo Horizonte",
            state="MG",
            refreshed_at=FIXED_TS,
        )
        db_session.commit()

        assert result.updated == 3
        assert result.layers_skipped_missing == 0

        rows = _by_name(db_session)
        assert normalize_risk_flags(rows["FixtureA"].risk_flags) == ["flood_zone"]
        assert rows["FixtureA"].quality_meta["risk"]["severity"]["flood_zone"] == "high"
        assert rows["FixtureA"].quality_meta["risk"]["provider"] == "geojson-overlay"
        assert rows["FixtureA"].quality_meta["risk"]["refreshed_at"] == FIXED_TS

        assert normalize_risk_flags(rows["FixtureB"].risk_flags) == [
            "industrial_adjacent"
        ]
        assert (
            rows["FixtureB"].quality_meta["risk"]["severity"]["industrial_adjacent"]
            == "medium"
        )

        assert normalize_risk_flags(rows["FixtureC"].risk_flags) == []
        assert rows["FixtureC"].quality_meta["risk"]["severity"] == {}

    def test_preserves_unrelated_flags(self, db_session):
        from adapters.db.models import Neighborhood

        load_neighbourhood_geojson(db_session, NHOOD_FIXTURE)
        db_session.commit()
        row = (
            db_session.query(Neighborhood).filter_by(name="FixtureA").one()
        )
        row.risk_flags = ["seller_reported_noise", "flood_zone"]
        row.quality_meta = {"provider": "curated-yaml"}
        db_session.commit()

        result = load_and_apply_risk_overlays(
            db_session,
            [RiskOverlayLayer(path=FLOOD_FIXTURE, risk_type="flood_zone")],
            city="Belo Horizonte",
            state="MG",
            refreshed_at=FIXED_TS,
        )
        db_session.commit()
        assert result.updated >= 1

        row = (
            db_session.query(Neighborhood).filter_by(name="FixtureA").one()
        )
        flags = normalize_risk_flags(row.risk_flags)
        assert "seller_reported_noise" in flags
        assert "flood_zone" in flags
        assert row.quality_meta["provider"] == "curated-yaml"
        assert row.quality_meta["risk"]["severity"]["flood_zone"] == "high"

    def test_missing_layer_skipped_no_hard_fail(self, db_session):
        load_neighbourhood_geojson(db_session, NHOOD_FIXTURE)
        db_session.commit()

        layers = [
            RiskOverlayLayer(
                path=Path("/nonexistent/bh_flood.geojson"),
                risk_type="flood_zone",
            ),
            RiskOverlayLayer(
                path=INDUSTRIAL_FIXTURE, risk_type="industrial_adjacent"
            ),
        ]
        result = load_and_apply_risk_overlays(
            db_session,
            layers,
            city="Belo Horizonte",
            state="MG",
            refreshed_at=FIXED_TS,
        )
        db_session.commit()

        assert result.layers_skipped_missing == 1
        rows = _by_name(db_session)
        assert "industrial_adjacent" in normalize_risk_flags(
            rows["FixtureB"].risk_flags
        )
        assert "flood_zone" not in normalize_risk_flags(rows["FixtureA"].risk_flags)

    def test_all_missing_leaves_flags_unchanged(self, db_session):
        from adapters.db.models import Neighborhood

        load_neighbourhood_geojson(db_session, NHOOD_FIXTURE)
        db_session.commit()
        row = (
            db_session.query(Neighborhood).filter_by(name="FixtureA").one()
        )
        row.risk_flags = ["flood_zone"]
        db_session.commit()

        result = load_and_apply_risk_overlays(
            db_session,
            [
                RiskOverlayLayer(
                    path=Path("/missing/a.geojson"), risk_type="flood_zone"
                )
            ],
            city="Belo Horizonte",
            state="MG",
        )
        db_session.commit()

        assert result.updated == 0
        assert result.layers_skipped_missing == 1
        row = (
            db_session.query(Neighborhood).filter_by(name="FixtureA").one()
        )
        assert normalize_risk_flags(row.risk_flags) == ["flood_zone"]

    def test_idempotent_rerun(self, db_session):
        load_neighbourhood_geojson(db_session, NHOOD_FIXTURE)
        db_session.commit()
        layers = [
            RiskOverlayLayer(path=FLOOD_FIXTURE, risk_type="flood_zone"),
            RiskOverlayLayer(
                path=INDUSTRIAL_FIXTURE, risk_type="industrial_adjacent"
            ),
        ]
        first = load_and_apply_risk_overlays(
            db_session,
            layers,
            city="Belo Horizonte",
            state="MG",
            refreshed_at=FIXED_TS,
        )
        db_session.commit()
        second = load_and_apply_risk_overlays(
            db_session,
            layers,
            city="Belo Horizonte",
            state="MG",
            refreshed_at=FIXED_TS,
        )
        db_session.commit()

        assert first.updated == 3
        assert second.updated == 0
        assert second.unchanged == 3
