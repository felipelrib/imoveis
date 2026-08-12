"""Unit tests for the pure enrichment-coverage math (v0.13-s1.6, FR-29).

TDD tier: this is ``src/core`` domain logic, so every row of the story's I/O
matrix that concerns arithmetic is asserted here rather than through the route.
The two rules the endpoint exists to protect are:

* **absence over zero** — an empty denominator is ``None``, never ``0.0``;
* **never fabricate** — no throughput, ETA or completion date is produced from
  a run that is not live or from history that cannot support one.

"Today" is injected everywhere, so the projected date is deterministic.
"""

from __future__ import annotations

from datetime import date

import pytest

from core.enrichment import EnrichmentTaskClass
from core.enrichment_coverage import (
    BackfillProgress,
    CoverageReport,
    SignalCoverage,
    build_coverage_report,
    coverage_fraction,
)

pytestmark = pytest.mark.unit

TODAY = date(2026, 8, 11)


def _report(**overrides) -> CoverageReport:
    kwargs = {
        "enriched_by_task_class": {},
        "total_properties": 0,
        "active": False,
        "remaining": 0,
        "throughput_per_day": None,
        "today": TODAY,
    }
    kwargs.update(overrides)
    return build_coverage_report(**kwargs)


class TestCoverageFraction:
    def test_zero_total_is_undefined_not_zero(self):
        """An empty denominator means "unknown", and 0% would be a lie."""
        assert coverage_fraction(0, 0) is None

    def test_negative_total_is_undefined(self):
        assert coverage_fraction(0, -1) is None

    def test_partial_coverage(self):
        assert coverage_fraction(1234, 2000) == pytest.approx(0.617)

    def test_complete_coverage_is_exactly_one(self):
        assert coverage_fraction(2000, 2000) == 1.0

    def test_no_coverage_on_a_populated_db_is_zero_not_none(self):
        assert coverage_fraction(0, 2000) == 0.0

    def test_over_count_is_clamped_into_range(self):
        """The wire type is ``ge=0 le=1``; a duplicate metrics row must not 422."""
        assert coverage_fraction(2500, 2000) == 1.0


class TestSignalSet:
    def test_every_task_class_is_reported_in_declaration_order(self):
        report = _report(total_properties=10, enriched_by_task_class={"visual": 5})
        assert [s.task_class for s in report.signals] == [
            tc.value for tc in EnrichmentTaskClass
        ]

    def test_a_missing_count_reads_as_zero_enriched(self):
        report = _report(total_properties=10, enriched_by_task_class={"visual": 5})
        by_class = {s.task_class: s for s in report.signals}
        assert by_class["visual"] == SignalCoverage(
            task_class="visual", enriched=5, total=10, fraction=0.5
        )
        assert by_class["embedding"].enriched == 0
        assert by_class["embedding"].fraction == 0.0

    def test_total_is_the_same_denominator_for_every_signal(self):
        report = _report(total_properties=10, enriched_by_task_class={"visual": 5})
        assert {s.total for s in report.signals} == {10}
        assert report.total_properties == 10


class TestMinimumFraction:
    def test_empty_db_has_no_minimum(self):
        """Matrix: zero active properties -> every fraction null, minimum null."""
        report = _report(total_properties=0)
        assert all(s.fraction is None for s in report.signals)
        assert all(s.enriched == 0 and s.total == 0 for s in report.signals)
        assert report.minimum_fraction is None

    def test_minimum_is_the_worst_measured_signal(self):
        report = _report(
            total_properties=2000,
            enriched_by_task_class={
                "visual": 1234,
                "sentiment": 1800,
                "deal_verdict": 1200,
                "valuation": 1900,
                "embedding": 1950,
            },
        )
        assert report.minimum_fraction == pytest.approx(0.6)

    def test_complete_coverage_yields_a_minimum_of_one(self):
        report = _report(
            total_properties=4,
            enriched_by_task_class={tc.value: 4 for tc in EnrichmentTaskClass},
        )
        assert report.minimum_fraction == 1.0
        assert all(s.fraction == 1.0 for s in report.signals)


class TestBackfillProgressWithoutARun:
    def test_no_run_means_no_projection_at_all(self):
        """Matrix: no run -> throughput/ETA/date all null, even with history."""
        report = _report(
            total_properties=2000, active=False, remaining=766, throughput_per_day=4600.0
        )
        assert report.backfill == BackfillProgress(
            active=False,
            remaining=766,
            throughput_per_day=None,
            eta_days=None,
            projected_completion_date=None,
        )


class TestBackfillProgressWithALiveRun:
    def test_usable_history_projects_throughput_eta_and_date(self):
        report = _report(active=True, remaining=766, throughput_per_day=4600.0)
        progress = report.backfill
        assert progress.active is True
        assert progress.remaining == 766
        assert progress.throughput_per_day == pytest.approx(4600.0)
        assert progress.eta_days == pytest.approx(0.17, abs=0.005)
        # Under a day of work left, so it lands tomorrow — days are rounded up.
        assert progress.projected_completion_date == "2026-08-12"

    def test_multi_day_eta_lands_on_a_whole_day_boundary(self):
        report = _report(active=True, remaining=9000, throughput_per_day=3000.0)
        assert report.backfill.eta_days == pytest.approx(3.0)
        assert report.backfill.projected_completion_date == "2026-08-14"

    @pytest.mark.parametrize("throughput", [None, 0.0, -5.0])
    def test_unusable_history_never_extrapolates(self, throughput):
        """Matrix: <2 snapshots (None) or a non-positive delta -> null, not 0."""
        report = _report(active=True, remaining=766, throughput_per_day=throughput)
        progress = report.backfill
        assert progress.active is True
        assert progress.remaining == 766
        assert progress.throughput_per_day is None
        assert progress.eta_days is None
        assert progress.projected_completion_date is None

    def test_nothing_left_to_enrich_finishes_today(self):
        """Matrix: remaining == 0 with a live run -> 0.0 days, dated today."""
        report = _report(active=True, remaining=0, throughput_per_day=4600.0)
        assert report.backfill.eta_days == 0.0
        assert report.backfill.projected_completion_date == TODAY.isoformat()

    def test_infinite_eta_never_reaches_the_wire(self):
        """``estimate_eta_days`` returns ``inf`` at rate<=0; JSON has no inf."""
        report = _report(active=True, remaining=5000, throughput_per_day=0.0)
        assert report.backfill.eta_days is None
        assert report.backfill.projected_completion_date is None

    def test_an_absurd_eta_keeps_the_number_but_drops_the_date(self):
        """A date beyond ``datetime.date``'s range is omitted, not clamped."""
        report = _report(active=True, remaining=10**9, throughput_per_day=0.001)
        assert report.backfill.eta_days is not None
        assert report.backfill.projected_completion_date is None

    def test_today_is_injected_not_read_from_the_clock(self):
        other_day = date(2030, 1, 31)
        report = _report(
            active=True, remaining=0, throughput_per_day=10.0, today=other_day
        )
        assert report.backfill.projected_completion_date == "2030-01-31"


class TestDeterminism:
    def test_identical_inputs_produce_identical_reports(self):
        """AC: repeated calls over an unchanged DB return the same figures."""
        args = {
            "total_properties": 2000,
            "enriched_by_task_class": {"visual": 1234, "sentiment": 1800},
            "active": True,
            "remaining": 766,
            "throughput_per_day": 4600.0,
        }
        assert _report(**args) == _report(**args)
