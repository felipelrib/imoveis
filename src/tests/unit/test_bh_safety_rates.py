"""Unit tests for BH regional → neighbourhood safety rates (BIN-96)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.bh_safety_rates import (
    DEFAULT_COUNTS_PATH,
    DEFAULT_REGIONALS_PATH,
    aggregate_bairro_extract_csv,
    build_bh_regional_safety_rates,
    expand_regional_counts_to_rates,
    parse_neighbourhood_regionals,
    parse_regional_counts,
    rates_to_yaml_dict,
)
from core.safety_overlay import SafetyOverlayError, parse_safety_rates

REPO = Path(__file__).resolve().parents[3]
GENERATED = REPO / "configs" / "bh_safety_rates.yaml"
FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "safety"
    / "bh_safety_rates_tiny.yaml"
)


class TestParseBhConfigs:
    def test_parse_regionals_and_counts(self):
        regionals = parse_neighbourhood_regionals(DEFAULT_REGIONALS_PATH)
        assert regionals["savassi"] == "Centro-Sul"
        assert regionals["venda nova"] == "Venda Nova"
        assert regionals["barreiro"] == "Barreiro"

        payload = parse_regional_counts(DEFAULT_COUNTS_PATH)
        assert payload["counts_folded"]["centro-sul"] == pytest.approx(658.0)
        assert payload["counts_folded"]["barreiro"] == pytest.approx(260.0)
        assert payload["period_start"] == "2026-01"

    def test_missing_regional_raises(self):
        with pytest.raises(SafetyOverlayError, match="no count"):
            expand_regional_counts_to_rates(
                neighbourhood_regionals={"savassi": "Atlantis"},
                regional_payload={
                    "counts_folded": {"centro-sul": 10.0},
                    "rate_definition": "x",
                    "provider": "y",
                    "attribution": "z",
                    "period_start": None,
                    "period_end": None,
                },
                display_names={"savassi": "Savassi"},
            )


class TestBuildBhRegionalRates:
    def test_builds_all_curated_neighbourhoods(self):
        rows = build_bh_regional_safety_rates()
        assert len(rows) == 36
        by_name = {r.name: r for r in rows}
        assert by_name["Savassi"].rate_per_100k == pytest.approx(658.0)
        assert by_name["Savassi"].grain == "regional"
        assert by_name["Savassi"].provider == "sejusp-mg-regional"
        assert by_name["Venda Nova"].rate_per_100k == pytest.approx(195.0)
        assert by_name["Barreiro"].rate_per_100k == pytest.approx(260.0)
        assert "not absolute safety" in by_name["Centro"].attribution

    def test_generated_yaml_roundtrips(self):
        assert GENERATED.is_file()
        rows = parse_safety_rates(GENERATED, default_city="Belo Horizonte", default_state="MG")
        assert len(rows) == 36
        assert rows[0].city == "Belo Horizonte"
        assert rows[0].state == "MG"

    def test_rates_to_yaml_dict(self):
        rows = build_bh_regional_safety_rates()
        payload = rates_to_yaml_dict(rows)
        assert payload["grain"] == "regional"
        assert len(payload["rates"]) == 36


class TestAggregateBairroExtract:
    def test_sums_by_bairro(self, tmp_path):
        path = tmp_path / "extract.csv"
        path.write_text(
            "bairro,registros\n"
            "Savassi,10\n"
            "Savassi,5\n"
            "Centro,100\n",
            encoding="utf-8",
        )
        rows = aggregate_bairro_extract_csv(path)
        by_name = {r.name: r for r in rows}
        assert by_name["Savassi"].rate_per_100k == pytest.approx(15.0)
        assert by_name["Centro"].rate_per_100k == pytest.approx(100.0)
        assert by_name["Savassi"].grain == "bairro"
        assert by_name["Savassi"].provider == "sejusp-mg-bairro-extract"

    def test_filter_allowlist(self, tmp_path):
        path = tmp_path / "extract.csv"
        path.write_text(
            "bairro,registros\nSavassi,10\nCentro,100\n",
            encoding="utf-8",
        )
        rows = aggregate_bairro_extract_csv(
            path, neighbourhood_names=["Savassi"]
        )
        assert len(rows) == 1
        assert rows[0].name == "Savassi"


def test_tiny_fixture_parses():
    rows = parse_safety_rates(FIXTURE)
    assert len(rows) == 3
    with FIXTURE.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert data["defaults"]["city"] == "Belo Horizonte"
