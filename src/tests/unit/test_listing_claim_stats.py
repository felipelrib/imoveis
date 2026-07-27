"""Unit tests for listing LLM sentiment flag aggregation (BIN-93)."""

from __future__ import annotations

from collections import Counter


class TestNormalizeFlag:
    def test_strips_and_collapses_whitespace(self):
        from core.listing_claim_stats import normalize_flag

        assert normalize_flag("  Near   Metro  ") == "near metro"

    def test_empty_and_non_string(self):
        from core.listing_claim_stats import normalize_flag

        assert normalize_flag("") is None
        assert normalize_flag("   ") is None
        assert normalize_flag(None) is None
        assert normalize_flag(12) is None


class TestExtractFlagsFromSentiment:
    def test_extracts_green_and_red(self):
        from core.listing_claim_stats import extract_flags_from_sentiment

        green, red = extract_flags_from_sentiment(
            {
                "green_flags": ["Near metro", "park"],
                "red_flags": ["Noise"],
            }
        )
        assert green == ["near metro", "park"]
        assert red == ["noise"]

    def test_missing_or_invalid_lists(self):
        from core.listing_claim_stats import extract_flags_from_sentiment

        assert extract_flags_from_sentiment(None) == ([], [])
        assert extract_flags_from_sentiment("x") == ([], [])
        assert extract_flags_from_sentiment({"green_flags": "metro"}) == ([], [])
        assert extract_flags_from_sentiment({"green_flags": [""], "red_flags": [None]}) == (
            [],
            [],
        )


class TestTopFlagFrequencies:
    def test_orders_by_count_then_flag(self):
        from core.listing_claim_stats import top_flag_frequencies

        counts = Counter({"park": 3, "metro": 3, "school": 1, "noise": 5})
        top = top_flag_frequencies(counts, limit=3)
        assert top == [
            {"flag": "noise", "count": 5},
            {"flag": "metro", "count": 3},
            {"flag": "park", "count": 3},
        ]

    def test_limit_zero_or_empty(self):
        from core.listing_claim_stats import top_flag_frequencies

        assert top_flag_frequencies(Counter(), limit=5) == []
        assert top_flag_frequencies(Counter({"a": 1}), limit=0) == []


class TestBuildListingClaimStats:
    def test_payload_includes_source_disclaimer_and_tops(self):
        from core.listing_claim_stats import (
            LISTING_CLAIM_DISCLAIMER,
            LISTING_CLAIM_SOURCE,
            build_listing_claim_stats,
        )

        payload = build_listing_claim_stats(
            sample_size=4,
            green_counts=Counter({"metro": 2, "park": 1}),
            red_counts=Counter({"noise": 3}),
            top_n=2,
            refreshed_at="2026-07-27T12:00:00+00:00",
        )
        assert payload["source"] == LISTING_CLAIM_SOURCE
        assert payload["disclaimer"] == LISTING_CLAIM_DISCLAIMER
        assert payload["sample_size"] == 4
        assert payload["refreshed_at"] == "2026-07-27T12:00:00+00:00"
        assert payload["top_green_flags"] == [
            {"flag": "metro", "count": 2},
            {"flag": "park", "count": 1},
        ]
        assert payload["top_red_flags"] == [{"flag": "noise", "count": 3}]


class TestMergeListingClaimStats:
    def test_nests_without_wiping_siblings_or_scores(self):
        from core.listing_claim_stats import merge_listing_claim_stats

        existing = {
            "provider": "curated-yaml",
            "access": {"hub_id": "savassi"},
            "amenity_counts": {"shop": 2},
        }
        stats = {
            "source": "listing_llm_aggregate",
            "sample_size": 1,
            "top_green_flags": [],
            "top_red_flags": [],
            "disclaimer": "bias",
            "refreshed_at": "t0",
        }
        merged = merge_listing_claim_stats(existing, stats)
        assert merged["provider"] == "curated-yaml"
        assert merged["access"]["hub_id"] == "savassi"
        assert merged["amenity_counts"]["shop"] == 2
        assert merged["listing_claim_stats"] == stats
        # Original untouched
        assert "listing_claim_stats" not in existing

    def test_non_dict_existing(self):
        from core.listing_claim_stats import merge_listing_claim_stats

        merged = merge_listing_claim_stats(None, {"source": "listing_llm_aggregate"})
        assert merged == {"listing_claim_stats": {"source": "listing_llm_aggregate"}}


class TestAggregateSentimentRows:
    def test_groups_by_neighbourhood(self):
        from core.listing_claim_stats import aggregate_sentiment_rows

        rows = [
            {
                "neighborhood_id": "n1",
                "meta": {
                    "sentiment": {
                        "green_flags": ["Metro", "Park"],
                        "red_flags": ["Noise"],
                    }
                },
            },
            {
                "neighborhood_id": "n1",
                "meta": {
                    "sentiment": {
                        "green_flags": ["metro"],
                        "red_flags": [],
                    }
                },
            },
            {
                "neighborhood_id": "n2",
                "meta": {"sentiment": {"green_flags": [], "red_flags": ["Flood"]}},
            },
            {"neighborhood_id": "n3", "meta": {}},  # no sentiment — skip
            {"neighborhood_id": None, "meta": {"sentiment": {"green_flags": ["x"]}}},
        ]
        by_nhood = aggregate_sentiment_rows(rows)
        assert set(by_nhood) == {"n1", "n2"}
        assert by_nhood["n1"].sample_size == 2
        assert by_nhood["n1"].green_counts["metro"] == 2
        assert by_nhood["n1"].green_counts["park"] == 1
        assert by_nhood["n1"].red_counts["noise"] == 1
        assert by_nhood["n2"].sample_size == 1
        assert by_nhood["n2"].red_counts["flood"] == 1


class TestConfigDefaults:
    def test_listing_claim_stats_config_defaults(self):
        from infra.config import ListingClaimStatsConfig, NeighbourhoodQualityConfig

        cfg = ListingClaimStatsConfig()
        assert cfg.enabled is False
        assert cfg.top_n == 10
        assert cfg.interval_hours == 24.0
        assert cfg.min_sample_size == 1

        nq = NeighbourhoodQualityConfig()
        assert nq.listing_claim_stats.enabled is False
