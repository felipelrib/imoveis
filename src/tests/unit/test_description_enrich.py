"""Unit tests for scrape-time description enrichment (BIN-105)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from adapters.queue.tasks import _enrich_candidate_description
from core.entities import PropertyCandidate


def _candidate(**overrides) -> PropertyCandidate:
    data = {
        "platform": "quintoandar",
        "platform_id": "895549038",
        "title": "Apartamento in Alvorada",
        "description": "",
        "price": 929.0,
        "listings": [
            {
                "platform": "quintoandar",
                "platform_listing_id": "895549038",
                "listing_type": "rent",
                "price": 929.0,
                "currency": "BRL",
                "url": "https://www.quintoandar.com.br/imovel/895549038",
            }
        ],
    }
    data.update(overrides)
    return PropertyCandidate(**data)


def test_enrich_skips_when_candidate_already_has_description():
    session = MagicMock()
    scraper = MagicMock()
    candidate = _candidate(description="already here")
    _enrich_candidate_description(session, scraper, candidate)
    scraper.fetch_description.assert_not_called()
    assert candidate.description == "already here"


def test_enrich_reuses_db_description_without_http():
    session = MagicMock()
    session.execute.return_value.fetchone.return_value = ("DB remarks text",)
    scraper = MagicMock()
    candidate = _candidate(description="")
    _enrich_candidate_description(session, scraper, candidate)
    scraper.fetch_description.assert_not_called()
    assert candidate.description == "DB remarks text"


def test_enrich_fetches_detail_when_db_empty():
    session = MagicMock()
    session.execute.return_value.fetchone.return_value = None
    scraper = MagicMock()
    scraper.fetch_description.return_value = "Seller remarks from detail"
    candidate = _candidate(description="")
    _enrich_candidate_description(session, scraper, candidate)
    scraper.fetch_description.assert_called_once_with(
        "https://www.quintoandar.com.br/imovel/895549038"
    )
    assert candidate.description == "Seller remarks from detail"


def test_enrich_noop_when_fetch_returns_empty():
    session = MagicMock()
    session.execute.return_value.fetchone.return_value = ("",)
    scraper = MagicMock()
    scraper.fetch_description.return_value = ""
    candidate = _candidate(description="")
    _enrich_candidate_description(session, scraper, candidate)
    assert candidate.description == ""


def test_enrich_handles_missing_fetch_method():
    session = MagicMock()
    session.execute.return_value.fetchone.return_value = None
    scraper = SimpleNamespace()  # no fetch_description
    candidate = _candidate(description="")
    _enrich_candidate_description(session, scraper, candidate)
    assert candidate.description == ""
