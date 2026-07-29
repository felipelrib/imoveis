"""Shared Next.js Flight (``__next_f.push``) HTML helpers for scrapers."""

from __future__ import annotations

import json
import re
from typing import Any

_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')


def unescape_js_string(value: str) -> str:
    """Decode escapes used inside ``self.__next_f.push([1, \"...\"])`` payloads."""
    out: list[str] = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            mapping = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}
            if nxt in mapping:
                out.append(mapping[nxt])
                i += 2
            elif nxt == "u" and i + 5 < len(value):
                try:
                    out.append(chr(int(value[i + 2 : i + 6], 16)))
                    i += 6
                except ValueError:
                    out.append(nxt)
                    i += 2
            else:
                out.append(nxt)
                i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _scan_json_value(
    haystack: str, start: int, open_ch: str, close_ch: str
) -> Any | None:
    """Parse a JSON array/object starting at ``start`` (must be open_ch)."""
    depth = 0
    in_string = False
    escape = False
    for pos in range(start, len(haystack)):
        ch = haystack[pos]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(haystack[start : pos + 1])
                except json.JSONDecodeError:
                    return None
    return None


def extract_json_array_after(haystack: str, marker: str) -> list | None:
    """Return the JSON array that follows ``marker`` (e.g. ``\"ads\":``)."""
    idx = haystack.find(marker)
    if idx < 0:
        return None
    start = haystack.find("[", idx + len(marker))
    if start < 0:
        return None
    parsed = _scan_json_value(haystack, start, "[", "]")
    return parsed if isinstance(parsed, list) else None


def extract_json_object_after(haystack: str, marker: str) -> dict | None:
    """Return the JSON object that follows ``marker`` (e.g. ``\"listing\":``)."""
    idx = haystack.find(marker)
    if idx < 0:
        return None
    start = haystack.find("{", idx + len(marker))
    if start < 0:
        return None
    parsed = _scan_json_value(haystack, start, "{", "}")
    return parsed if isinstance(parsed, dict) else None


def iter_flight_chunks(html: str):
    """Yield unescaped payload strings from ``__next_f.push`` scripts."""
    for match in _PUSH_RE.finditer(html or ""):
        yield unescape_js_string(match.group(1))
