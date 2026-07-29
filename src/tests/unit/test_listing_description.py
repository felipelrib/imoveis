"""Unit tests for listing description extractors (BIN-105)."""

from __future__ import annotations

from pathlib import Path

from adapters.scrapers.listing_description import (
    _unescape_js_string,
    candidate_listing_url,
    extract_olx_description,
    extract_quintoandar_description,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "scrapers"


def test_extract_quintoandar_description_prefers_remarks():
    html = (FIXTURES / "quintoandar_detail.html").read_text(encoding="utf-8")
    text = extract_quintoandar_description(html)
    assert "Alvorada" in text
    assert "metrô" in text or "metro" in text.lower() or "compacto" in text


def test_extract_quintoandar_description_empty_html():
    assert extract_quintoandar_description("") == ""
    assert extract_quintoandar_description("<html></html>") == ""


def test_extract_olx_description_from_next_data():
    html = (FIXTURES / "olx_detail.html").read_text(encoding="utf-8")
    text = extract_olx_description(html)
    assert "vista panorâmica" in text
    assert "armários" in text


def test_extract_olx_description_from_flight():
    html = (FIXTURES / "olx_detail_flight.html").read_text(encoding="utf-8")
    text = extract_olx_description(html)
    assert "praia" in text
    assert len(text) > 20


def test_extract_olx_description_empty_html():
    assert extract_olx_description("") == ""


def test_flight_search_cassette_has_no_body():
    """Live OLX search Flight ads omit body — enrich must come from detail."""
    html = (FIXTURES / "olx_search_flight.html").read_text(encoding="utf-8")
    # Search page may still match short strings; extractor should not invent body.
    # If the fixture has no body field, result is empty.
    from adapters.scrapers.olx import OLXScraper

    scraper = OLXScraper("olx", {"rate_limit": 20, "jitter_min": 0, "jitter_max": 0.01})
    ads = scraper._extract_flight_ads(html)
    assert ads
    assert not (ads[0].get("body") or ads[0].get("description"))
    result = scraper.normalize(ads[0])
    assert (result.get("description") or "") == ""


def test_candidate_listing_url():
    class C:
        listings = [{"url": "https://example.test/a"}, {"url": "https://example.test/b"}]

    assert candidate_listing_url(C()) == "https://example.test/a"
    assert candidate_listing_url({"listings": []}) == ""


def test_unescape_js_string_falls_back_on_invalid_escape():
    """BIN-143: a truncated/invalid \\u escape makes unicode_escape decoding
    raise; the crude fallback replacements should still run without error."""
    result = _unescape_js_string('trailing backslash \\')
    assert isinstance(result, str)
