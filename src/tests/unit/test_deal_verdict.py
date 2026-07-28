"""Deal verdict template tests (BIN-69 / BIN-101)."""

from __future__ import annotations

import pytest

from adapters.ai.client import DealVerdictResult, OllamaClient, template_deal_verdict


@pytest.mark.unit
class TestTemplateDealVerdict:
    """Unit tests for the deterministic verdict template (codes + legacy EN)."""

    def test_full_signals(self):
        result = template_deal_verdict(
            stat_analysis={"category": "Slightly Undervalued", "reasoning": "Below median"},
            visual={"category": "Good", "reasoning": "Well-maintained"},
            sentiment={"category": "Highly Desirable", "reasoning": "Great location",
                       "green_flags": ["close to metro"], "red_flags": []},
            neighborhood_name="Savassi",
        )
        assert "Slightly undervalued" in result
        assert "good condition" in result
        assert "no listing claim alerts" in result

    def test_full_signals_with_codes(self):
        result = template_deal_verdict(
            stat_analysis={"category": "slightly_undervalued"},
            visual={"category": "good"},
            sentiment={"green_flags": ["metro"], "red_flags": []},
        )
        assert "Slightly undervalued" in result
        assert "good condition" in result

    def test_pt_br_template(self):
        result = template_deal_verdict(
            stat_analysis={"category": "highly_undervalued"},
            visual={"category": "needs_renovation"},
            sentiment={"red_flags": [], "green_flags": []},
            output_language="pt-BR",
        )
        assert "Muito abaixo do mercado" in result
        assert "precisa de reforma" in result
        assert "sem alertas" in result

    def test_stat_only(self):
        result = template_deal_verdict(
            stat_analysis={"category": "Highly Undervalued", "reasoning": "..."},
            visual=None,
            sentiment=None,
        )
        assert result == "Highly undervalued"

    def test_visual_only(self):
        result = template_deal_verdict(
            stat_analysis=None,
            visual={"category": "Needs Renovation", "reasoning": "..."},
            sentiment=None,
        )
        assert result == "needs renovation"

    def test_sentiment_with_red_flags(self):
        result = template_deal_verdict(
            stat_analysis=None,
            visual=None,
            sentiment={"red_flags": ["noisy avenue", "no parking"], "green_flags": []},
        )
        assert "2 listing claim concerns" in result

    def test_sentiment_single_red_flag(self):
        result = template_deal_verdict(
            stat_analysis=None,
            visual=None,
            sentiment={"red_flags": ["noise"], "green_flags": ["metro nearby"]},
        )
        assert "1 listing claim concern" in result
        assert "positive listing claims" not in result

    def test_sentiment_many_green_flags(self):
        result = template_deal_verdict(
            stat_analysis=None,
            visual=None,
            sentiment={"red_flags": [], "green_flags": ["metro", "park", "school"]},
        )
        assert "3 positive listing claims" in result
        assert "no listing claim alerts" in result

    def test_neighbourhood_quality_in_template(self):
        result = template_deal_verdict(
            stat_analysis={"category": "Average", "reasoning": "..."},
            visual={"category": "Good", "reasoning": "..."},
            sentiment={"red_flags": [], "green_flags": []},
            neighbourhood_quality={
                "neighbourhood_score": 0.8,
                "risk_flags": ["flood"],
            },
        )
        assert "neighbourhood quality 80%" in result
        assert "1 neighbourhood risk (flood)" in result
        assert "no listing claim alerts" in result

    def test_no_signals(self):
        result = template_deal_verdict()
        assert result == "Not enough data for a deal verdict"

    def test_empty_dicts(self):
        result = template_deal_verdict(
            stat_analysis={},
            visual={},
            sentiment={},
        )
        assert result == "Not enough data for a deal verdict"

    def test_overvalued_category(self):
        result = template_deal_verdict(
            stat_analysis={"category": "Highly Overvalued", "reasoning": "Above median"},
        )
        assert result == "Highly above neighbourhood average"

    def test_pristine_condition(self):
        result = template_deal_verdict(
            visual={"category": "Pristine", "reasoning": "Fully renovated"},
        )
        assert result == "excellent condition"

    def test_poor_condition(self):
        result = template_deal_verdict(
            visual={"category": "Poor", "reasoning": "Major issues"},
        )
        assert result == "poor condition"

    def test_average_condition(self):
        result = template_deal_verdict(
            visual={"category": "Average", "reasoning": "Fair condition"},
        )
        assert result == "average condition"


@pytest.mark.unit
class TestDealVerdictResult:
    def test_default_values(self):
        r = DealVerdictResult()
        assert r.verdict == ""
        assert r.confidence == 0.0

    def test_with_values(self):
        r = DealVerdictResult(verdict="Great deal", confidence=0.85)
        assert r.verdict == "Great deal"
        assert r.confidence == 0.85

    def test_from_dict(self):
        r = DealVerdictResult.model_validate({"verdict": "test", "confidence": 0.5})
        assert r.verdict == "test"


@pytest.mark.unit
class TestSummarizeDeal:
    """Tests for the summarize_deal method with mocked LLM."""

    @pytest.mark.asyncio
    async def test_ollama_verdict_calls_llm(self, monkeypatch: pytest.MonkeyPatch):
        """OllamaClient.summarize_deal calls the LLM and returns its verdict."""
        client = OllamaClient.__new__(OllamaClient)
        client.base_url = "http://fake"
        client.timeout = None
        client.session = None
        client.visual_model = "llava"
        client.text_model = "llama3"

        async def mock_llm(prompt):
            return DealVerdictResult(verdict="Mocked verdict from LLM", confidence=0.9)

        client._llm_verdict = mock_llm

        monkeypatch.setattr(
            "infra.ui_locale.resolve_ai_output_language",
            lambda: "en",
        )

        result = await client.summarize_deal(
            stat_analysis={"category": "Average", "reasoning": "..."},
            visual={"category": "Good", "reasoning": "..."},
            sentiment={"red_flags": [], "green_flags": ["metro"]},
        )
        assert result.verdict == "Mocked verdict from LLM"
        assert result.confidence == 0.9

    @pytest.mark.asyncio
    async def test_fallback_to_template_on_llm_error(self, monkeypatch: pytest.MonkeyPatch):
        """When LLM fails, summarize_deal falls back to the deterministic template."""
        client = OllamaClient.__new__(OllamaClient)
        client.base_url = "http://fake"
        client.timeout = None
        client.session = None
        client.visual_model = "llava"
        client.text_model = "llama3"

        async def mock_llm_error(prompt):
            raise ConnectionError("LLM unavailable")

        client._llm_verdict = mock_llm_error
        monkeypatch.setattr(
            "infra.ui_locale.resolve_ai_output_language",
            lambda: "en",
        )

        result = await client.summarize_deal(
            stat_analysis={"category": "Slightly Undervalued", "reasoning": "..."},
            visual={"category": "Good", "reasoning": "..."},
            sentiment={"red_flags": [], "green_flags": []},
        )
        assert "Slightly undervalued" in result.verdict
        assert result.confidence == 0.0


@pytest.mark.unit
class TestBuildDealVerdictPrompt:
    def test_contains_all_signals(self):
        from adapters.ai.prompts import build_deal_verdict_prompt

        prompt = build_deal_verdict_prompt(
            stat_analysis={"category": "Average", "reasoning": "Near median"},
            visual={"category": "Good", "reasoning": "Well-kept"},
            sentiment={"category": "Good", "reasoning": "Nice area",
                       "green_flags": ["metro"], "red_flags": ["noise"]},
            neighborhood_name="Savassi",
            neighbourhood_quality={
                "neighbourhood_score": 0.75,
                "amenity_score": 0.8,
                "risk_flags": ["flood"],
            },
        )
        assert "Savassi" in prompt
        assert "Average" in prompt
        assert "Good" in prompt
        assert "metro" in prompt
        assert "noise" in prompt
        assert "Ad Claims from Listing" in prompt
        assert "Objective Neighbourhood Quality" in prompt
        assert "flood" in prompt
        assert "JSON" in prompt or "json" in prompt

    def test_defaults_handled(self):
        from adapters.ai.prompts import build_deal_verdict_prompt

        prompt = build_deal_verdict_prompt()
        assert "N/A" in prompt
        assert "Ad Claims from Listing" in prompt
