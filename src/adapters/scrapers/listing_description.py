"""Extract listing body text from platform detail HTML (BIN-105).

Search cards often omit descriptions; detail pages carry seller remarks / ad body.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from bs4 import BeautifulSoup

# BIN-245: QuintoAndar renders the seller description in a CSS-module DOM block
# whose class name starts with ``DescriptionsSection`` (the hashed suffix, e.g.
# ``DescriptionsSection_descriptionsWrapper__HNAzX``, is build-specific and must
# not be matched literally). Many real listings carry this text ONLY in the DOM,
# not in ``__NEXT_DATA__``, so the JSON-only extractor missed them.
_QA_DESCRIPTION_CLASS_RE = re.compile(r"DescriptionsSection")

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_FLIGHT_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')
_BODY_IN_JSON_RE = re.compile(
    r'"(?:body|description)"\s*:\s*"((?:\\.|[^"\\]){20,})"',
)
_OLX_AD_KEYS = ("ad", "adData", "listing", "detail")
_OLX_ID_KEYS = ("listId", "list_id", "id", "adId")

# BIN-244: real OLX detail pages carry the seller's ad body in a schema.org
# JSON-LD block (``RentAction``/``SaleAction`` → ``Object`` → ``description``, or
# a bare ``Product`` with a top-level ``description``), NOT in ``__NEXT_DATA__``
# or the Flight payload. The field is HTML (``<br>``-separated lines), so it must
# be tag-stripped before it enters the corpus. Nested-entity keys are checked
# before an object's own ``description`` so the ad's Product wins over the
# enclosing action.
_LD_JSON_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_LD_NESTED_KEYS = ("Object", "mainEntity", "item", "itemOffered")
_LD_AD_TYPES = frozenset(
    {
        "rentaction",
        "saleaction",
        "product",
        "offer",
        "realestatelisting",
        "residence",
        "apartment",
        "house",
        "singlefamilyresidence",
    }
)
_BR_RE = re.compile(r"(?i)<br\s*/?>")


def _strip_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _first_nonempty(*values: Any) -> str:
    for value in values:
        text = _strip_text(value)
        if text:
            return text
    return ""


def _load_next_data(html: str) -> Optional[dict]:
    match = _NEXT_DATA_RE.search(html or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _qa_long_description(generated: Any) -> str:
    if isinstance(generated, dict):
        return _strip_text(generated.get("longDescription"))
    return _strip_text(generated)


def _qa_from_house_info(house_info: dict) -> str:
    """Prefer seller remarks, then generated long text, then legacy description."""
    return _first_nonempty(
        house_info.get("remarks"),
        _qa_long_description(house_info.get("generatedDescription")),
        house_info.get("description"),
    )


def _qa_from_house_blob(house: dict) -> str:
    house_info = house.get("houseInfo")
    if isinstance(house_info, dict):
        found = _qa_from_house_info(house_info)
        if found:
            return found
    return _first_nonempty(house.get("remarks"), house.get("description"))


def _qa_from_houses_map(houses: Any) -> str:
    if not isinstance(houses, dict):
        return ""
    for value in houses.values():
        if not isinstance(value, dict):
            continue
        found = _first_nonempty(value.get("remarks"), value.get("description"))
        if found:
            return found
    return ""


def _qa_from_next_data(html: str) -> str:
    """Description from the QuintoAndar detail ``__NEXT_DATA__`` payload, if any."""
    data = _load_next_data(html)
    if not data:
        return ""

    initial = (
        data.get("props", {})
        .get("pageProps", {})
        .get("initialState", {})
    )
    if not isinstance(initial, dict):
        return ""

    house = initial.get("house")
    if isinstance(house, dict):
        found = _qa_from_house_blob(house)
        if found:
            return found
    return _qa_from_houses_map(initial.get("houses"))


def _normalize_dom_text(text: str) -> str:
    """Collapse whitespace and tidy spaces left before punctuation by inline links."""
    collapsed = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s+([.,;:!?])", r"\1", collapsed)


def _qa_from_dom(html: str) -> str:
    """Seller description rendered in the ``DescriptionsSection`` DOM block (BIN-245).

    Real QA detail pages often carry the description only here, not in
    ``__NEXT_DATA__``. Class suffixes are build-hashed, so match on the stable
    ``DescriptionsSection`` prefix and take the first (outermost) match.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    node = soup.find(class_=_QA_DESCRIPTION_CLASS_RE)
    if node is None:
        return ""
    return _normalize_dom_text(node.get_text(" ", strip=True))


def extract_quintoandar_description(html: str) -> str:
    """Description from a QuintoAndar detail page.

    JSON (``__NEXT_DATA__``) first; falls back to the ``DescriptionsSection``
    DOM block when the JSON payload carries no description (BIN-245).
    """
    found = _qa_from_next_data(html)
    if found:
        return found
    return _qa_from_dom(html)


def _olx_body_from_mapping(obj: Any) -> str:
    if not isinstance(obj, dict):
        return ""
    return _first_nonempty(obj.get("body"), obj.get("description"))


def _olx_body_from_known_keys(container: dict) -> str:
    for key in _OLX_AD_KEYS:
        found = _olx_body_from_mapping(container.get(key))
        if found:
            return found
    return ""


def _olx_looks_like_ad(obj: dict) -> bool:
    return any(obj.get(k) for k in _OLX_ID_KEYS)


def _olx_walk_for_body(obj: Any, *, depth: int = 0) -> str:
    if depth > 6:
        return ""
    if isinstance(obj, dict):
        body = _olx_body_from_mapping(obj)
        if body and (_olx_looks_like_ad(obj) or depth <= 2):
            return body
        found = _olx_body_from_known_keys(obj)
        if found:
            return found
        for value in obj.values():
            if isinstance(value, (dict, list)):
                found = _olx_walk_for_body(value, depth=depth + 1)
                if found:
                    return found
    elif isinstance(obj, list):
        for item in obj[:20]:
            found = _olx_walk_for_body(item, depth=depth + 1)
            if found:
                return found
    return ""


def _unescape_js_string(value: str) -> str:
    try:
        return bytes(value, "utf-8").decode("unicode_escape")
    except Exception:  # fall back to crude unescape
        return (
            value.replace(r"\\\"", '"')
            .replace(r"\\n", "\n")
            .replace(r"\\/", "/")
            .replace(r"\\\\", "\\")
        )


def _decode_json_string_fragment(raw: str) -> str:
    try:
        return _strip_text(json.loads(f'"{raw}"'))
    except (json.JSONDecodeError, TypeError):
        return _strip_text(_unescape_js_string(raw))


def _first_body_in_text(blob: str) -> str:
    for match in _BODY_IN_JSON_RE.finditer(blob or ""):
        text = _decode_json_string_fragment(match.group(1))
        if text:
            return text
    return ""


def _olx_from_flight(html: str) -> str:
    for match in _FLIGHT_PUSH_RE.finditer(html or ""):
        chunk = _unescape_js_string(match.group(1))
        if "body" not in chunk and "description" not in chunk:
            continue
        found = _first_body_in_text(chunk)
        if found:
            return found
    return ""


def _olx_from_next_data(data: dict) -> str:
    page_props = data.get("props", {}).get("pageProps", {})
    if not isinstance(page_props, dict):
        return ""
    found = _olx_body_from_known_keys(page_props)
    if found:
        return found
    state = page_props.get("initialState") or page_props.get("state") or {}
    if isinstance(state, dict):
        found = _olx_body_from_known_keys(state)
        if found:
            return found
    return _olx_walk_for_body(page_props)


def _ld_type_is_ad(obj: dict) -> bool:
    raw = obj.get("@type")
    types = raw if isinstance(raw, list) else [raw]
    return any(isinstance(t, str) and t.lower() in _LD_AD_TYPES for t in types)


def _ld_ad_description(obj: Any) -> str:
    """Description reachable only through a nested ad entity or an ad-typed node.

    Prefers the ad's ``Product`` under a Rent/Sale action; a generic ``WebPage``
    / breadcrumb ``description`` (SEO decoys) is ignored by this pass.
    """
    if isinstance(obj, list):
        for item in obj:
            found = _ld_ad_description(item)
            if found:
                return found
        return ""
    if not isinstance(obj, dict):
        return ""
    for key in _LD_NESTED_KEYS:
        if key in obj:
            found = _ld_ad_description(obj.get(key))
            if found:
                return found
    if _ld_type_is_ad(obj):
        return _strip_text(obj.get("description"))
    return ""


def _ld_any_description(obj: Any) -> str:
    """Fallback: the first ``description`` anywhere in a JSON-LD node."""
    if isinstance(obj, list):
        for item in obj:
            found = _ld_any_description(item)
            if found:
                return found
        return ""
    if not isinstance(obj, dict):
        return ""
    for key in _LD_NESTED_KEYS:
        if key in obj:
            found = _ld_any_description(obj.get(key))
            if found:
                return found
    return _strip_text(obj.get("description"))


def _olx_from_json_ld(html: str) -> str:
    """Ad body from a schema.org JSON-LD block (BIN-244 real-page oracle).

    Two passes across all blocks: the ad-typed/nested description wins over any
    generic top-level ``description`` (meta/breadcrumb SEO decoys).
    """
    blocks = []
    for match in _LD_JSON_RE.finditer(html or ""):
        try:
            blocks.append(json.loads(match.group(1)))
        except (json.JSONDecodeError, TypeError):
            continue
    for block in blocks:
        found = _ld_ad_description(block)
        if found:
            return found
    for block in blocks:
        found = _ld_any_description(block)
        if found:
            return found
    return ""


def _clean_olx_body(text: str) -> str:
    """Strip HTML markup OLX ships inside description fields (BIN-244).

    OLX ad bodies (JSON-LD or, occasionally, ``__NEXT_DATA__``) are HTML with
    ``<br>`` line breaks. Turn breaks into separators so words don't glue,
    drop any remaining tags, then collapse whitespace — matching the plain-text
    contract the QuintoAndar extractor already honours.
    """
    if not text:
        return ""
    if "<" not in text:
        return _normalize_dom_text(text)
    with_breaks = _BR_RE.sub("\n", text)
    stripped = BeautifulSoup(with_breaks, "html.parser").get_text(" ")
    return _normalize_dom_text(stripped)


def _olx_raw_description(html: str) -> str:
    data = _load_next_data(html)
    if data:
        found = _olx_from_next_data(data)
        if found:
            return found

    found = _olx_from_flight(html)
    if found:
        return found
    found = _olx_from_json_ld(html)
    if found:
        return found
    return _first_body_in_text(html or "")


def extract_olx_description(html: str) -> str:
    """Pull the ad body from an OLX detail page and return clean plain text.

    Sources, in order: ``__NEXT_DATA__`` → Flight payload → schema.org JSON-LD
    (the real-page location, BIN-244) → a crude whole-page regex fallback (for
    truncated captures). Whatever is found is tag-stripped (BIN-244) so ``<br>``
    markup never reaches sentiment enrichment or the dashboard.
    """
    return _clean_olx_body(_olx_raw_description(html))


def candidate_listing_url(candidate: Any) -> str:
    """Best detail URL from a PropertyCandidate (or dict-like)."""
    listings = getattr(candidate, "listings", None)
    if listings is None and isinstance(candidate, dict):
        listings = candidate.get("listings")
    if not isinstance(listings, list):
        return ""
    for row in listings:
        if not isinstance(row, dict):
            continue
        url = (row.get("url") or "").strip()
        if url:
            return url
    return ""
