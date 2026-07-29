"""Unit tests for curated neighbourhood quality YAML parsing (BIN-87)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import yaml

from core.neighbourhood_quality_yaml import (
    CURATED_SOURCE,
    CuratedProfile,
    LoadResult,
    NeighbourhoodQualityYamlError,
    apply_curated_profiles,
    load_curated_neighbourhood_quality,
    parse_curated_yaml,
)

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "neighbourhood_quality_tiny.yaml"
)
SEED = (
    Path(__file__).resolve().parents[3]
    / "configs"
    / "neighbourhood_quality.yaml"
)
APP_CONFIG = (
    Path(__file__).resolve().parents[3] / "configs" / "app_config.yaml"
)


def _profile(**overrides) -> CuratedProfile:
    base = dict(
        name="Savassi",
        city="Belo Horizonte",
        state="MG",
        amenity_score=0.9,
        transit_score=0.85,
        access_score=0.88,
        safety_score=0.72,
        risk_flags=(),
        notes="Central",
        slug="savassi",
    )
    base.update(overrides)
    return CuratedProfile(**base)


def _row(**overrides) -> SimpleNamespace:
    base = dict(
        name="Savassi",
        city="Belo Horizonte",
        state="MG",
        amenity_score=None,
        transit_score=None,
        access_score=None,
        safety_score=None,
        risk_flags=[],
        quality_meta=None,
        quality_notes=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestParseCuratedYaml:
    def test_parses_tiny_fixture(self):
        rows = parse_curated_yaml(FIXTURE)
        assert len(rows) == 3
        by_name = {r.name: r for r in rows}
        savassi = by_name["Savassi"]
        assert isinstance(savassi, CuratedProfile)
        assert savassi.city == "Belo Horizonte"
        assert savassi.state == "MG"
        assert savassi.amenity_score == pytest.approx(0.90)
        assert savassi.transit_score == pytest.approx(0.85)
        assert savassi.access_score == pytest.approx(0.88)
        assert savassi.safety_score == pytest.approx(0.72)
        assert savassi.risk_flags == ()
        assert savassi.slug == "savassi"
        assert "Central" in (savassi.notes or "")

        efigenia = by_name["Santa Efigênia"]
        assert efigenia.slug == "santa-efigenia"
        assert efigenia.amenity_score == pytest.approx(0.65)

    def test_defaults_city_state_when_omitted(self):
        data = {
            "version": 1,
            "defaults": {"city": "Campinas", "state": "sp"},
            "profiles": [
                {
                    "name": "Cambuí",
                    "amenity_score": 0.8,
                    "transit_score": 0.7,
                    "access_score": 0.75,
                    "safety_score": 0.6,
                }
            ],
        }
        rows = parse_curated_yaml(data)
        assert rows[0].city == "Campinas"
        assert rows[0].state == "SP"

    def test_invalid_score_becomes_none(self):
        data = {
            "version": 1,
            "defaults": {"city": "Belo Horizonte", "state": "MG"},
            "profiles": [
                {
                    "name": "Savassi",
                    "amenity_score": 1.5,
                    "transit_score": "bad",
                    "access_score": 0.5,
                    "safety_score": -0.1,
                }
            ],
        }
        rows = parse_curated_yaml(data)
        assert rows[0].amenity_score is None
        assert rows[0].transit_score is None
        assert rows[0].access_score == pytest.approx(0.5)
        assert rows[0].safety_score is None

    def test_missing_name_raises(self):
        data = {
            "version": 1,
            "profiles": [{"amenity_score": 0.5}],
        }
        with pytest.raises(NeighbourhoodQualityYamlError, match="missing name"):
            parse_curated_yaml(data)

    def test_wrong_root_raises(self):
        with pytest.raises(NeighbourhoodQualityYamlError, match="profiles"):
            parse_curated_yaml({"version": 1})

    def test_risk_flags_normalized(self):
        data = {
            "version": 1,
            "defaults": {"city": "Belo Horizonte", "state": "MG"},
            "profiles": [
                {
                    "name": "Centro",
                    "amenity_score": 0.6,
                    "risk_flags": [" flood ", "industrial"],
                }
            ],
        }
        rows = parse_curated_yaml(data)
        assert rows[0].risk_flags == ("flood", "industrial")

    def test_bad_state_and_non_object_profile_raise(self):
        with pytest.raises(NeighbourhoodQualityYamlError, match="2-letter"):
            parse_curated_yaml(
                {
                    "profiles": [
                        {"name": "X", "city": "BH", "state": "Minas"}
                    ]
                }
            )
        with pytest.raises(NeighbourhoodQualityYamlError, match="must be an object"):
            parse_curated_yaml({"profiles": ["not-an-object"]})

    def test_yaml_root_must_be_object(self, tmp_path: Path):
        path = tmp_path / "bad.yaml"
        path.write_text("- just a list\n", encoding="utf-8")
        with pytest.raises(NeighbourhoodQualityYamlError, match="root must be an object"):
            parse_curated_yaml(path)

    def test_defaults_must_be_object(self):
        with pytest.raises(NeighbourhoodQualityYamlError, match="defaults must be an object"):
            parse_curated_yaml({"defaults": ["nope"], "profiles": []})


class TestApplyCuratedProfiles:
    def test_updates_matching_row_and_skips_unknown(self):
        row = _row()
        session = MagicMock()
        session.query.return_value.all.return_value = [row]
        stamp = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)

        result = apply_curated_profiles(
            session,
            [_profile(), _profile(name="Missing", slug="missing")],
            refreshed_at=stamp,
        )

        assert result == LoadResult(updated=1, skipped=1)
        assert row.amenity_score == pytest.approx(0.9)
        assert row.quality_meta["source"] == CURATED_SOURCE
        assert row.quality_meta["refreshed_at"] == "2026-07-27T12:00:00Z"
        assert row.quality_notes == "Central"
        session.flush.assert_called_once()

    def test_fold_match_and_idempotent_skip(self):
        row = _row(
            name="Santa Efigenia",
            amenity_score=0.65,
            transit_score=0.7,
            access_score=0.68,
            safety_score=0.55,
            risk_flags=[],
            quality_notes="East of centre (fixture).",
            quality_meta={"source": CURATED_SOURCE, "refreshed_at": "old"},
        )
        session = MagicMock()
        session.query.return_value.all.return_value = [row]
        profiles = parse_curated_yaml(FIXTURE)
        efigenia = next(p for p in profiles if p.slug == "santa-efigenia")

        result = apply_curated_profiles(session, [efigenia])
        assert result.updated == 0
        assert result.skipped == 1
        session.flush.assert_not_called()

    def test_changed_score_updates_even_if_source_curated(self):
        row = _row(
            amenity_score=0.1,
            transit_score=0.85,
            access_score=0.88,
            safety_score=0.72,
            quality_meta={"source": CURATED_SOURCE},
            quality_notes="Central",
        )
        session = MagicMock()
        session.query.return_value.all.return_value = [row]
        result = apply_curated_profiles(session, [_profile()])
        assert result.updated == 1
        assert row.amenity_score == pytest.approx(0.9)

    def test_null_vs_score_is_not_unchanged(self):
        row = _row(
            amenity_score=None,
            transit_score=0.85,
            access_score=0.88,
            safety_score=0.72,
            quality_meta={"source": CURATED_SOURCE},
            quality_notes="Central",
        )
        session = MagicMock()
        session.query.return_value.all.return_value = [row]
        result = apply_curated_profiles(session, [_profile(amenity_score=0.9)])
        assert result.updated == 1

    def test_both_null_scores_can_be_idempotent(self):
        row = _row(
            amenity_score=None,
            transit_score=None,
            access_score=None,
            safety_score=None,
            quality_meta={"source": CURATED_SOURCE},
            quality_notes=None,
        )
        session = MagicMock()
        session.query.return_value.all.return_value = [row]
        result = apply_curated_profiles(
            session,
            [
                _profile(
                    amenity_score=None,
                    transit_score=None,
                    access_score=None,
                    safety_score=None,
                    notes=None,
                )
            ],
        )
        assert result.skipped == 1
        assert result.updated == 0

    def test_load_curated_parses_then_applies(self):
        row = _row(name="Savassi")
        session = MagicMock()
        session.query.return_value.all.return_value = [row]
        result = load_curated_neighbourhood_quality(session, FIXTURE)
        assert result.updated == 1
        assert result.skipped == 2
        assert row.quality_meta["source"] == CURATED_SOURCE

    def test_load_result_total(self):
        assert LoadResult(updated=2, skipped=3).total == 5


class TestSeedCoversFanOut:
    def test_seed_covers_qa_and_olx_slugs(self):
        assert SEED.is_file(), f"missing seed YAML at {SEED}"
        rows = parse_curated_yaml(SEED)
        seed_slugs = {r.slug for r in rows if r.slug}
        assert len(rows) >= 35
        assert None not in seed_slugs

        app = yaml.safe_load(APP_CONFIG.read_text(encoding="utf-8"))
        platforms = app["scraping"]["platforms"]

        def _fan_out_slugs(extra: dict) -> set[str]:
            cities = extra.get("cities") or []
            if cities:
                return {
                    n["slug"]
                    for city in cities
                    for n in (city.get("neighborhoods") or [])
                    if isinstance(n, dict) and n.get("slug")
                }
            return {
                n["slug"]
                for n in (extra.get("neighborhoods") or [])
                if isinstance(n, dict) and n.get("slug")
            }

        qa_slugs = _fan_out_slugs(platforms["quintoandar"]["extra"])
        olx_slugs = _fan_out_slugs(platforms["olx"]["extra"])
        fan_out = qa_slugs | olx_slugs
        missing = fan_out - seed_slugs
        assert not missing, f"seed missing fan-out slugs: {sorted(missing)}"
        assert "horto" in seed_slugs
        assert len(seed_slugs) >= len(fan_out)


class TestLoadCli:
    def test_dry_run_exits_zero(self, capsys):
        import importlib.util
        import sys

        path = (
            Path(__file__).resolve().parents[3]
            / "scripts"
            / "dev"
            / "load_neighbourhood_quality.py"
        )
        spec = importlib.util.spec_from_file_location("load_nhood_quality_cli", path)
        cli = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = cli
        spec.loader.exec_module(cli)

        rc = cli.main(["--yaml", str(FIXTURE), "--dry-run"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Parsed 3" in out
        assert "Dry-run" in out

    def test_missing_file_exits_one(self, capsys):
        import importlib.util
        import sys

        path = (
            Path(__file__).resolve().parents[3]
            / "scripts"
            / "dev"
            / "load_neighbourhood_quality.py"
        )
        spec = importlib.util.spec_from_file_location("load_nhood_quality_cli2", path)
        cli = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = cli
        spec.loader.exec_module(cli)

        rc = cli.main(["--yaml", "/no/such/file.yaml"])
        assert rc == 1
        assert "error:" in capsys.readouterr().err

    def test_write_path_commits(self, capsys):
        import importlib.util
        import sys

        path = (
            Path(__file__).resolve().parents[3]
            / "scripts"
            / "dev"
            / "load_neighbourhood_quality.py"
        )
        spec = importlib.util.spec_from_file_location("load_nhood_quality_cli3", path)
        cli = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = cli
        spec.loader.exec_module(cli)

        session = MagicMock()
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)

        with (
            patch("infra.db.SessionLocal", return_value=session),
            patch.object(
                cli,
                "load_curated_neighbourhood_quality",
                return_value=LoadResult(updated=2, skipped=1),
            ),
        ):
            rc = cli.main(["--yaml", str(FIXTURE)])

        assert rc == 0
        session.commit.assert_called_once()
        assert "updated=2" in capsys.readouterr().out
