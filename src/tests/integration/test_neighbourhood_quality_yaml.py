"""Integration: curated YAML neighbourhood quality loader (BIN-87)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from adapters.db.models import Neighborhood
from core.neighbourhood_quality_yaml import (
    CURATED_SOURCE,
    load_curated_neighbourhood_quality,
    parse_curated_yaml,
)

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "neighbourhood_quality_tiny.yaml"
)


@pytest.fixture(scope="function")
def db_session(wipe_safe_db_session):
    yield wipe_safe_db_session


def _seed_neighbourhood(session, *, name: str, city: str = "Belo Horizonte", state: str = "MG"):
    row = Neighborhood(name=name, city=city, state=state)
    session.add(row)
    session.flush()
    return row


@pytest.mark.integration
class TestLoadCuratedNeighbourhoodQuality:
    def test_load_sets_scores_and_curated_source(self, db_session):
        savassi = _seed_neighbourhood(db_session, name="Savassi")
        efigenia = _seed_neighbourhood(db_session, name="Santa Efigênia")
        db_session.commit()

        result = load_curated_neighbourhood_quality(db_session, FIXTURE)
        db_session.commit()

        assert result.updated == 2
        assert result.skipped == 1  # Unknown Bairro

        db_session.refresh(savassi)
        db_session.refresh(efigenia)
        assert savassi.amenity_score == pytest.approx(0.90)
        assert savassi.transit_score == pytest.approx(0.85)
        assert savassi.access_score == pytest.approx(0.88)
        assert savassi.safety_score == pytest.approx(0.72)
        assert savassi.risk_flags == []
        assert savassi.quality_meta["source"] == CURATED_SOURCE
        assert "refreshed_at" in savassi.quality_meta
        assert "Central" in (savassi.quality_notes or "")

        assert efigenia.amenity_score == pytest.approx(0.65)
        assert efigenia.quality_meta["source"] == CURATED_SOURCE

        assert db_session.query(Neighborhood).filter_by(name="Unknown Bairro").count() == 0

    def test_unknown_name_skipped_no_insert(self, db_session):
        before = db_session.query(Neighborhood).count()
        result = load_curated_neighbourhood_quality(db_session, FIXTURE)
        db_session.commit()

        assert result.updated == 0
        assert result.skipped == 3
        assert db_session.query(Neighborhood).count() == before

    def test_reload_identical_is_idempotent(self, db_session):
        _seed_neighbourhood(db_session, name="Savassi")
        _seed_neighbourhood(db_session, name="Santa Efigênia")
        db_session.commit()

        first = load_curated_neighbourhood_quality(db_session, FIXTURE)
        db_session.commit()
        meta_first = (
            db_session.query(Neighborhood).filter_by(name="Savassi").one().quality_meta
        )

        second = load_curated_neighbourhood_quality(db_session, FIXTURE)
        db_session.commit()

        assert first.updated == 2
        assert second.updated == 0
        assert second.skipped == 3  # 2 unchanged + 1 unknown
        meta_second = (
            db_session.query(Neighborhood).filter_by(name="Savassi").one().quality_meta
        )
        assert meta_second["refreshed_at"] == meta_first["refreshed_at"]

    def test_reload_changed_score_updates(self, db_session):
        row = _seed_neighbourhood(db_session, name="Savassi")
        db_session.commit()

        load_curated_neighbourhood_quality(db_session, FIXTURE)
        db_session.commit()
        original_id = row.id

        data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
        for profile in data["profiles"]:
            if profile.get("name") == "Savassi":
                profile["amenity_score"] = 0.41

        result = load_curated_neighbourhood_quality(db_session, data)
        db_session.commit()

        assert result.updated == 1
        updated = db_session.query(Neighborhood).filter_by(name="Savassi").one()
        assert updated.id == original_id
        assert updated.amenity_score == pytest.approx(0.41)
        assert updated.quality_meta["source"] == CURATED_SOURCE

    def test_fold_match_accented_name(self, db_session):
        """DB may store unaccented spelling; YAML uses accents — fold must match."""
        row = _seed_neighbourhood(db_session, name="Santa Efigenia")
        db_session.commit()

        result = load_curated_neighbourhood_quality(db_session, FIXTURE)
        db_session.commit()

        assert result.updated == 1
        db_session.refresh(row)
        assert row.amenity_score == pytest.approx(0.65)
        assert row.quality_meta["source"] == CURATED_SOURCE

    def test_parse_seed_file_has_expected_size(self):
        from core.neighbourhood_quality_yaml import DEFAULT_YAML_PATH

        rows = parse_curated_yaml(DEFAULT_YAML_PATH)
        assert len(rows) >= 35
        assert all(r.city == "Belo Horizonte" for r in rows)
        assert all(r.state == "MG" for r in rows)
