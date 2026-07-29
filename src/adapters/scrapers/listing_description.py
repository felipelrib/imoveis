"""Extract listing body text from platform detail HTML (BIN-105).

Search cards often omit descriptions; detail pages carry seller remarks / ad body.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

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


def extract_quintoandar_description(html: str) -> str:
    """Pull description from a QuintoAndar detail ``__NEXT_DATA__`` payload."""
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


def extract_olx_description(html: str) -> str:
    """Pull ad body from an OLX detail page (``__NEXT_DATA__`` or Flight)."""
    data = _load_next_data(html)
    if data:
        found = _olx_from_next_data(data)
        if found:
            return found

    found = _olx_from_flight(html)
    if found:
        return found
    return _first_body_in_text(html or "")


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
