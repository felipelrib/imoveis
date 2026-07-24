"""Unit tests for scraper funnel helpers."""

from __future__ import annotations

import pytest

from adapters.scrapers.funnel import bisect_price, listing_id_from_raw, unique_by


@pytest.mark.unit
class TestBisectPrice:
    def test_splits_range(self):
        assert bisect_price(100, 200) == ((100, 150), (151, 200))

    def test_none_when_equal(self):
        assert bisect_price(100, 100) is None

    def test_none_when_min_greater(self):
        assert bisect_price(200, 100) is None

    def test_none_when_adjacent(self):
        # mid = 100 → collapses onto min
        assert bisect_price(100, 101) is None

    def test_splits_wide_range(self):
        left, right = bisect_price(500, 15000)
        assert left[0] == 500
        assert right[1] == 15000
        assert left[1] + 1 == right[0]


@pytest.mark.unit
class TestUniqueBy:
    def test_dedupes_by_key(self):
        items = [{"id": "a"}, {"id": "b"}, {"id": "a"}, {"id": "c"}]
        out = list(unique_by(items, lambda x: x["id"]))
        assert [x["id"] for x in out] == ["a", "b", "c"]

    def test_none_keys_always_yielded(self):
        items = [{"id": None}, {"id": None}]
        out = list(unique_by(items, lambda x: x["id"]))
        assert len(out) == 2

    def test_mutates_shared_seen(self):
        seen: set = set()
        first = list(unique_by([{"id": "a"}], lambda x: x["id"], seen=seen))
        second = list(unique_by([{"id": "a"}, {"id": "b"}], lambda x: x["id"], seen=seen))
        assert first == [{"id": "a"}]
        assert second == [{"id": "b"}]
        assert seen == {"a", "b"}


@pytest.mark.unit
class TestListingIdFromRaw:
    def test_olx_list_id(self):
        assert listing_id_from_raw({"list_id": "123"}) == "123"

    def test_olx_list_id_camel(self):
        assert listing_id_from_raw({"listId": 42}) == "42"

    def test_quintoandar_id(self):
        assert listing_id_from_raw({"id": 99}) == "99"

    def test_missing(self):
        assert listing_id_from_raw({}) is None
