"""Unit tests for shared Next.js Flight HTML helpers (BIN-127)."""

from __future__ import annotations

import json

from adapters.scrapers.flight_html import (
    extract_json_array_after,
    extract_json_object_after,
    iter_flight_chunks,
    unescape_js_string,
)


class TestUnescapeJsString:
    def test_common_escapes(self):
        assert unescape_js_string('a\\nb\\tc\\r\\"d\\\\e') == 'a\nb\tc\r"d\\e'

    def test_unicode_escape(self):
        assert unescape_js_string("caf\\u00e9") == "café"

    def test_invalid_unicode_escape_is_kept_literal(self):
        assert unescape_js_string("\\uZZZZ") == "uZZZZ"

    def test_trailing_backslash_is_kept(self):
        assert unescape_js_string("abc\\") == "abc\\"

    def test_unknown_escape_keeps_next_char(self):
        assert unescape_js_string("a\\qb") == "aqb"

    def test_no_escapes_passthrough(self):
        assert unescape_js_string("plain text") == "plain text"


class TestExtractJsonArrayAfter:
    def test_extracts_simple_array(self):
        haystack = '{"listings":[{"id":"1"},{"id":"2"}],"other":1}'
        result = extract_json_array_after(haystack, '"listings":')
        assert result == [{"id": "1"}, {"id": "2"}]

    def test_handles_nested_brackets_and_strings(self):
        payload = [{"id": "1", "tags": ["a]", "b["], "note": 'has "quotes"'}]
        haystack = '"ads":' + json.dumps(payload) + ",\"trailer\":true"
        result = extract_json_array_after(haystack, '"ads":')
        assert result == payload

    def test_missing_marker_returns_none(self):
        assert extract_json_array_after('{"other":1}', '"listings":') is None

    def test_marker_without_array_returns_none(self):
        assert extract_json_array_after('"listings":null', '"listings":') is None

    def test_malformed_json_returns_none(self):
        assert extract_json_array_after('"listings":[1,2,', '"listings":') is None


class TestExtractJsonObjectAfter:
    def test_extracts_simple_object(self):
        haystack = '{"listing":{"id":"1","nested":{"a":1}},"trailer":true}'
        result = extract_json_object_after(haystack, '"listing":')
        assert result == {"id": "1", "nested": {"a": 1}}

    def test_missing_marker_returns_none(self):
        assert extract_json_object_after("{}", '"listing":') is None

    def test_marker_without_object_returns_none(self):
        assert extract_json_object_after('"listing":null', '"listing":') is None

    def test_result_must_be_dict(self):
        # `extract_json_array_after`-shaped payload passed to the object helper.
        assert extract_json_object_after('"listing":[1,2]', '"listing":') is None


class TestIterFlightChunks:
    def test_yields_unescaped_chunks_from_push_calls(self):
        inner = '{"listings":[{"id":"1"}]}'
        escaped = inner.replace("\\", "\\\\").replace('"', '\\"')
        html = f'<script>self.__next_f.push([1,"{escaped}"])</script>'
        chunks = list(iter_flight_chunks(html))
        assert chunks == [inner]

    def test_no_push_calls_yields_nothing(self):
        assert list(iter_flight_chunks("<html></html>")) == []

    def test_multiple_push_calls_yield_each_chunk(self):
        html = (
            '<script>self.__next_f.push([1,"a"])</script>'
            '<script>self.__next_f.push([1,"b"])</script>'
        )
        assert list(iter_flight_chunks(html)) == ["a", "b"]
