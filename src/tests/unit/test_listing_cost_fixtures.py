"""Labelled cross-platform fixture set for Total Monthly Cost (Story 1.1, AC 4).

Raw payloads for the three platforms go through the real scraper
``normalize()`` and then through the one cost mapping the persist path uses.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from adapters.scrapers.olx import OLXScraper
from adapters.scrapers.quintoandar import QuintoAndarScraper
from adapters.scrapers.zapimoveis import ZapImoveisScraper
from core.listing_cost import COST_COLUMNS, COST_SOURCE_KEY, listing_cost_columns

pytestmark = pytest.mark.unit

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "cost" / "labelled_listings.json"
CASES = {case["id"]: case for case in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]}

_SCRAPERS = {
    "quintoandar": lambda: QuintoAndarScraper(
        "quintoandar", {"rate_limit": 30, "extra": {"city_slug": "belo-horizonte-mg-brasil"}}
    ),
    "olx": lambda: OLXScraper("olx", {"rate_limit": 20, "jitter_min": 0, "jitter_max": 0.1}),
    "zapimoveis": lambda: ZapImoveisScraper(
        "zapimoveis",
        {"rate_limit": 20, "jitter_min": 0, "jitter_max": 0.1, "extra": {"city_slug": "mg+belo-horizonte"}},
    ),
}


def _normalized_listing(case: dict) -> dict:
    """The case's listing as the real platform ``normalize()`` emits it."""
    result = _SCRAPERS[case["platform"]]().normalize(copy.deepcopy(case["raw"]))
    return next(row for row in result["listings"] if row["listing_type"] == case["listing_type"])


def _as_stored_before_the_story(listing: dict) -> dict:
    """The row a pre-story scrape of the same figures left in the DB.

    Same legacy columns, ``raw_json`` round-tripped through JSON as the persist
    path stores it, and no ``cost_source`` stamp.
    """
    raw_json = {k: v for k, v in (listing.get("raw_json") or {}).items() if k != COST_SOURCE_KEY}
    return {**listing, "raw_json": json.dumps(raw_json)}


def _cost(case_id: str) -> dict:
    return listing_cost_columns(_normalized_listing(CASES[case_id]))


def test_fixture_covers_the_three_platforms():
    assert {case["platform"] for case in CASES.values()} == {"quintoandar", "olx", "zapimoveis"}


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_normalized_listing_matches_its_label(case_id):
    case = CASES[case_id]
    listing = _normalized_listing(case)
    cost = listing_cost_columns(listing)
    assert tuple(cost) == COST_COLUMNS
    assert cost == case["expected"], case["label"]


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_scraper_stamps_the_raw_cost_figures(case_id):
    listing = _normalized_listing(CASES[case_id])
    stamp = listing["raw_json"][COST_SOURCE_KEY]
    assert set(stamp) == {"rent", "condo_fee", "iptu", "fees_combined", "iptu_periodicity"}
    json.dumps(listing["raw_json"], allow_nan=False)


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_legacy_headline_and_bundled_key_are_untouched(case_id):
    """The story changes no legacy value: headline ``price`` and ``raw_json.fees_bundled``."""
    case = CASES[case_id]
    listing = _normalized_listing(case)
    assert listing["price"] == pytest.approx(case["headline_price"])
    assert isinstance(listing["raw_json"]["fees_bundled"], bool)


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_stored_row_yields_what_a_fresh_scrape_does(case_id):
    listing = _normalized_listing(CASES[case_id])
    stored = _as_stored_before_the_story(listing)
    assert COST_SOURCE_KEY not in json.loads(stored["raw_json"])
    assert listing_cost_columns(stored) == listing_cost_columns(listing)


def test_same_home_on_three_platforms_has_one_total():
    """Identical components: the totals agree and rent is counted once."""
    costs = [_cost(case_id) for case_id in ("home-a-quintoandar", "home-a-olx", "home-a-zapimoveis")]
    assert {cost["total_monthly_cost"] for cost in costs} == {4173.0}
    for cost in costs:
        assert cost["total_monthly_cost"] == pytest.approx(
            cost["rent_monthly"] + cost["condo_fee_monthly"] + cost["iptu_monthly"]
        )
        assert cost["rent_monthly"] == 3500.0


def test_same_home_headlines_disagree_while_totals_agree():
    """The hazard the story corrects: the legacy headline is not comparable."""
    headlines = {
        _normalized_listing(CASES[case_id])["price"]
        for case_id in ("home-a-quintoandar", "home-a-olx", "home-a-zapimoveis")
    }
    assert len(headlines) == 3


def test_same_home_on_two_platforms_differs_by_exactly_the_published_component():
    quintoandar, zap = _cost("home-b-quintoandar"), _cost("home-b-zapimoveis")
    assert quintoandar["rent_monthly"] == zap["rent_monthly"]
    assert quintoandar["iptu_monthly"] == zap["iptu_monthly"]
    condo_difference = quintoandar["condo_fee_monthly"] - zap["condo_fee_monthly"]
    assert condo_difference == pytest.approx(20.0)
    assert quintoandar["total_monthly_cost"] - zap["total_monthly_cost"] == pytest.approx(
        condo_difference
    )


def test_olx_zero_for_missing_fee_regression():
    """OLX sums a missing fee as zero in the headline; the total must not."""
    listing = _normalized_listing(CASES["olx-zero-for-missing-fee"])
    assert listing["price"] == pytest.approx(4150.0)
    assert listing["iptu"] == 0.0
    cost = listing_cost_columns(listing)
    assert cost["iptu_monthly"] is None
    assert cost["total_monthly_cost"] is None
    assert cost["cost_complete"] is False


def test_zap_annual_iptu_regression():
    """Zap stores the annual IPTU as published; the monthly component is a twelfth."""
    listing = _normalized_listing(CASES["home-b-zapimoveis"])
    assert listing["iptu"] == pytest.approx(4940.0)
    cost = listing_cost_columns(listing)
    assert cost["iptu_periodicity_source"] == "annual"
    assert cost["iptu_monthly"] == 411.67
    assert cost["total_monthly_cost"] == 5591.67


def test_quintoandar_remainder_is_legacy_only():
    """``totalCost - rentPrice`` still feeds the legacy ``condo_fee``, never the new columns."""
    listing = _normalized_listing(CASES["quintoandar-remainder-only"])
    assert listing["condo_fee"] == pytest.approx(35.0)
    assert listing["raw_json"]["fees_bundled"] is True
    assert listing["raw_json"][COST_SOURCE_KEY]["condo_fee"] is None
    assert listing_cost_columns(listing)["condo_fee_monthly"] is None


def test_dual_listing_stamps_do_not_share_state():
    """A rent+sale ad: the sale Listing carries no rent, and each has its own stamp."""
    raw = copy.deepcopy(CASES["home-a-zapimoveis"]["raw"])
    raw["prices"]["sale"] = {"value": 450000, "condominium": 400, "iptu": 3276}
    listings = _SCRAPERS["zapimoveis"]().normalize(raw)["listings"]
    rent = next(row for row in listings if row["listing_type"] == "rent")
    sale = next(row for row in listings if row["listing_type"] == "sale")
    assert rent["raw_json"] is not sale["raw_json"]
    assert rent["raw_json"][COST_SOURCE_KEY]["rent"] == 3500.0
    assert sale["raw_json"][COST_SOURCE_KEY]["rent"] is None
    assert listing_cost_columns(sale)["total_monthly_cost"] is None
    assert listing_cost_columns(rent)["total_monthly_cost"] == 4173.0
