"""Cohort price/m² percentile (Story 1.6, FR-30) — written before ``core/cohort_percentile.py``.

Percentile = cohort members priced at or below this one ÷ cohort size, in
(0, 1]; lower is cheaper; tied members share the inclusive count; a cohort
below the minimum size has no percentile.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from core.cohort_percentile import (
    COHORT_CITY_SQL,
    COHORT_NEIGHBOURHOOD_SQL,
    MIN_COHORT_SIZE_FLOOR,
    cohort_percentile,
    cohort_percentiles,
    validate_min_cohort_size,
)
from infra.config import ConfigError, ScoringConfig, load_config

pytestmark = pytest.mark.unit

MODULE_PATH = Path(__file__).resolve().parents[2] / "core" / "cohort_percentile.py"


class TestCohortPercentile:
    def test_inclusive_share(self):
        assert cohort_percentile(1, 4, 3) == 0.25
        assert cohort_percentile(2, 4, 3) == 0.5
        assert cohort_percentile(4, 4, 3) == 1.0

    def test_cheapest_of_twenty_is_among_the_five_percent_cheapest(self):
        assert cohort_percentile(1, 20, 10) == 0.05

    def test_exactly_at_the_minimum_has_a_value(self):
        assert cohort_percentile(1, 3, 3) == pytest.approx(1 / 3)

    def test_one_below_the_minimum_has_none(self):
        assert cohort_percentile(1, 2, 3) is None
        assert cohort_percentile(2, 2, 3) is None

    @pytest.mark.parametrize("minimum", [2, 3, 10])
    def test_a_cohort_of_one_never_has_a_percentile(self, minimum):
        assert cohort_percentile(1, 1, minimum) is None

    @pytest.mark.parametrize("at_or_below", [0, -1, 5])
    def test_counts_outside_the_cohort_are_rejected(self, at_or_below):
        with pytest.raises(ValueError):
            cohort_percentile(at_or_below, 4, 3)

    def test_inconsistent_counts_are_rejected_below_the_minimum_too(self):
        with pytest.raises(ValueError):
            cohort_percentile(0, 2, 3)
        with pytest.raises(ValueError):
            cohort_percentile(3, 2, 3)

    @pytest.mark.parametrize("cohort_size", [0, -3])
    def test_an_empty_cohort_is_rejected(self, cohort_size):
        with pytest.raises(ValueError):
            cohort_percentile(1, cohort_size, 3)

    @pytest.mark.parametrize("minimum", [1, 0, -5])
    def test_a_minimum_below_two_is_rejected(self, minimum):
        with pytest.raises(ValueError):
            cohort_percentile(1, 4, minimum)

    def test_result_is_never_zero_and_never_above_one(self):
        for size in range(2, 40):
            for at_or_below in range(1, size + 1):
                value = cohort_percentile(at_or_below, size, 2)
                assert value is not None and 0.0 < value <= 1.0


class TestValidateMinCohortSize:
    def test_floor_is_two(self):
        assert MIN_COHORT_SIZE_FLOOR == 2
        assert validate_min_cohort_size(2) == 2
        assert validate_min_cohort_size(10) == 10

    @pytest.mark.parametrize("value", [1, 0, -1])
    def test_below_the_floor_raises(self, value):
        with pytest.raises(ValueError):
            validate_min_cohort_size(value)


class TestWholeCohortReference:
    def test_distinct_prices(self):
        assert cohort_percentiles([30, 40, 50, 70], 3) == [0.25, 0.5, 0.75, 1.0]

    def test_ties_share_the_inclusive_count(self):
        assert cohort_percentiles([30, 40, 40, 50], 3) == [0.25, 0.75, 0.75, 1.0]

    def test_all_tied(self):
        assert cohort_percentiles([40, 40, 40], 3) == [1.0, 1.0, 1.0]

    def test_exactly_at_the_minimum(self):
        assert cohort_percentiles([30, 40, 50], 3) == pytest.approx([1 / 3, 2 / 3, 1.0])

    def test_one_below_the_minimum(self):
        assert cohort_percentiles([30, 40], 3) == [None, None]

    def test_single_member(self):
        assert cohort_percentiles([30], 2) == [None]

    def test_empty_cohort(self):
        assert cohort_percentiles([], 3) == []

    def test_order_of_the_input_is_kept(self):
        assert cohort_percentiles([70, 30, 50, 40], 3) == [1.0, 0.25, 0.75, 0.5]

    def test_minimum_below_two_is_rejected_even_for_an_empty_cohort(self):
        with pytest.raises(ValueError):
            cohort_percentiles([], 1)

    def test_agrees_with_the_single_member_function(self):
        values = [12.5, 80.0, 33.3, 33.3, 41.0, 12.5, 12.5, 99.0, 55.5, 60.0, 61.0]
        expected = [
            cohort_percentile(sum(1 for other in values if other <= value), len(values), 10)
            for value in values
        ]
        assert cohort_percentiles(values, 10) == expected
        assert cohort_percentiles(values, 12) == [None] * len(values)


class TestConfigOwnedThreshold:
    """``scoring.percentile_min_cohort_size`` (AD-2)."""

    def test_committed_default_is_ten(self):
        assert load_config().scoring.percentile_min_cohort_size == 10
        assert ScoringConfig().percentile_min_cohort_size == 10

    def test_floor_matches_the_pure_module(self):
        assert ScoringConfig(percentile_min_cohort_size=MIN_COHORT_SIZE_FLOOR)
        with pytest.raises(ValueError):
            ScoringConfig(percentile_min_cohort_size=MIN_COHORT_SIZE_FLOOR - 1)

    def test_a_changed_value_is_read_without_a_code_change(self, monkeypatch):
        monkeypatch.setenv("IMOVEIS_SCORING__PERCENTILE_MIN_COHORT_SIZE", "25")
        assert load_config().scoring.percentile_min_cohort_size == 25

    def test_a_value_below_two_fails_config_validation(self, monkeypatch):
        monkeypatch.setenv("IMOVEIS_SCORING__PERCENTILE_MIN_COHORT_SIZE", "1")
        with pytest.raises(ConfigError):
            load_config()


class TestContract:
    def test_module_imports_no_adapters_api_or_infra(self):
        """AD-1: the definition is pure."""
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"), filename=str(MODULE_PATH))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        for name in imported:
            assert name.split(".")[0] not in {"adapters", "api", "infra", "sqlalchemy"}, name

    def test_sql_expressions_are_static_text_without_parameters(self):
        for sql in (COHORT_CITY_SQL, COHORT_NEIGHBOURHOOD_SQL):
            assert ":" not in sql
            assert "%" not in sql
            assert "{" not in sql

    def test_neighbourhood_prefers_the_spatial_fk_and_reads_no_price(self):
        assert "n.name" in COHORT_NEIGHBOURHOOD_SQL
        assert "props_json->>'neighborhood'" in COHORT_NEIGHBOURHOOD_SQL
        assert "n.city" in COHORT_CITY_SQL
        assert "props_json->>'city'" in COHORT_CITY_SQL
        for sql in (COHORT_CITY_SQL, COHORT_NEIGHBOURHOOD_SQL):
            assert "price" not in sql

    def test_key_expressions_fold_accents_and_whitespace(self):
        for sql in (COHORT_CITY_SQL, COHORT_NEIGHBOURHOOD_SQL):
            assert "TRANSLATE(LOWER(NORMALIZE(" in sql
            assert "REGEXP_REPLACE(" in sql and "BTRIM(" in sql
        assert COHORT_NEIGHBOURHOOD_SQL.startswith("NULLIF(")
        assert COHORT_CITY_SQL.startswith("COALESCE(")

    def test_module_reads_no_price_column(self):
        """The price comes from core.price_basis in the caller, never from here."""
        source = MODULE_PATH.read_text(encoding="utf-8")
        for forbidden in ("pl.price", "p.price", "properties.price", "total_monthly_cost"):
            assert forbidden not in source, forbidden
