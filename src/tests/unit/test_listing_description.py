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


def test_extract_quintoandar_description_from_dom_fallback():
    """BIN-245: real QA detail pages render the seller description in the DOM
    (``DescriptionsSection`` block), not always in ``__NEXT_DATA__``. The
    fixture is a byte-exact capture of listing 894353786, whose description is
    absent from the JSON blob — the extractor must fall back to the DOM."""
    html = (FIXTURES / "quintoandar_detail_dom.html").read_text(encoding="utf-8")
    text = extract_quintoandar_description(html)
    assert "aconchegante" in text
    assert "Greenwich Schools" in text
    assert "Santo Antônio" in text
    assert "Colégio Santa Dorotéia" in text
    assert "<" not in text and ">" not in text  # tags stripped
    assert "Belo Horizonte." in text  # spacing normalized around nested links
    assert len(text) > 300


def test_extract_quintoandar_description_json_precedes_dom():
    """When the JSON blob carries the description, it wins over any DOM block."""
    json_html = (FIXTURES / "quintoandar_detail.html").read_text(encoding="utf-8")
    dom_block = (
        '<div class="DescriptionsSection_wrapper__x"><p><span>'
        "SHOULD NOT WIN dom text</span></p></div>"
    )
    combined = json_html.replace("</body>", f"{dom_block}</body>")
    text = extract_quintoandar_description(combined)
    assert "Alvorada" in text
    assert "SHOULD NOT WIN" not in text


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


def test_extract_olx_description_from_real_captured_page():
    """BIN-246/BIN-244: byte-exact slice of a real OLX detail page fetched via
    the headless-browser bypass. The real oracle carries the ad body in a
    JSON-LD ``RentAction`` block whose ``description`` is HTML (``<br>``-laden),
    not in ``__NEXT_DATA__`` / Flight. Confirm extract_olx_description returns
    the body AND cleans the markup (BIN-244) so downstream sentiment (BIN-242)
    and the dashboard get plain text."""
    html = (FIXTURES / "olx_detail_real.html").read_text(encoding="utf-8")
    text = extract_olx_description(html)
    assert "Excelente Apartamento" in text
    assert "Lagoa Santa" in text
    assert "Campinho" in text
    assert len(text) > 500
    # BIN-244: markup must be stripped — no raw HTML tags leak into the corpus.
    assert "<br>" not in text
    assert "<" not in text and ">" not in text
    # Words that were separated only by <br> must not glue together.
    assert "com:2 quartos" not in text
    assert "2 quartos" in text


def test_extract_olx_description_from_json_ld_prefers_ad_over_decoy():
    """BIN-244: real OLX detail pages expose the ad body in a schema.org
    ``RentAction``/``SaleAction`` JSON-LD block (``Object.description``). Parse it
    explicitly rather than grabbing the first ``"description"`` in the page — an
    earlier decoy (meta / breadcrumb) must not win, and the ``<br>`` markup that
    OLX ships inside that field must be cleaned."""
    html = (
        "<html><head>"
        '<script type="application/ld+json">'
        '{"@type":"WebPage","description":"DECOY meta description that must not win here."}'
        "</script>"
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"RentAction",'
        '"identifier":1497362999,"Object":{"@type":"Product",'
        '"name":"Aluguel: Apartamento 2 quartos",'
        '"description":"Excelente apartamento no Campinho.<br><br>2 quartos;<br>Sala."}}'
        "</script>"
        "</head><body></body></html>"
    )
    text = extract_olx_description(html)
    assert text.startswith("Excelente apartamento no Campinho.")
    assert "DECOY" not in text
    assert "<br>" not in text
    assert "Campinho. 2 quartos" in text  # <br> became a separator, words not glued


def test_extract_olx_description_next_data_body_is_cleaned():
    """A ``__NEXT_DATA__`` body carrying inline ``<br>`` markup is cleaned too."""
    html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"ad":{"listId":1,'
        '"body":"Linha um.<br>Linha dois com bastante texto aqui."}}}}'
        "</script>"
    )
    text = extract_olx_description(html)
    assert "<br>" not in text
    assert "Linha um. Linha dois" in text


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
