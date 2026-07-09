"""Tests for AI client — deal verdict template and synthesis."""

from __future__ import annotations

import pytest

from adapters.ai.client import (
    DealVerdictResult,
    OllamaClient,
    template_deal_verdict,
)

# ---------------------------------------------------------------------------
# template_deal_verdict — deterministic path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTemplateDealVerdict:
    """Unit tests for the deterministic PT-BR verdict template."""

    def test_full_signals(self):
        result = template_deal_verdict(
            stat_analysis={"category": "Slightly Undervalued", "reasoning": "Below median"},
            visual={"category": "Good", "reasoning": "Well-maintained"},
            sentiment={"category": "Highly Desirable", "reasoning": "Great location",
                       "green_flags": ["close to metro"], "red_flags": []},
            neighborhood_name="Savassi",
        )
        assert "Ligeiramente subvalorizado" in result
        assert "boa condição" in result
        assert "sem alertas" in result

    def test_stat_only(self):
        result = template_deal_verdict(
            stat_analysis={"category": "Highly Undervalued", "reasoning": "..."},
            visual=None,
            sentiment=None,
        )
        assert result == "Altamente subvalorizado"

    def test_visual_only(self):
        result = template_deal_verdict(
            stat_analysis=None,
            visual={"category": "Needs Renovation", "reasoning": "..."},
            sentiment=None,
        )
        assert result == "precisa de reforma"

    def test_sentiment_with_red_flags(self):
        result = template_deal_verdict(
            stat_analysis=None,
            visual=None,
            sentiment={"red_flags": ["noisy avenue", "no parking"], "green_flags": []},
        )
        assert "2 preocupações" in result

    def test_sentiment_single_red_flag(self):
        result = template_deal_verdict(
            stat_analysis=None,
            visual=None,
            sentiment={"red_flags": ["noise"], "green_flags": ["metro nearby"]},
        )
        assert "1 preocupação" in result
        assert "1 aspecto positivo" not in result  # green_flags < 2
        assert "1 aspectos positivos" not in result

    def test_sentiment_many_green_flags(self):
        result = template_deal_verdict(
            stat_analysis=None,
            visual=None,
            sentiment={"red_flags": [], "green_flags": ["metro", "park", "school"]},
        )
        assert "3 aspectos positivos" in result
        assert "sem alertas" in result

    def test_no_signals(self):
        result = template_deal_verdict()
        assert result == "Sem dados suficientes para avaliação"

    def test_empty_dicts(self):
        result = template_deal_verdict(
            stat_analysis={},
            visual={},
            sentiment={},
        )
        assert result == "Sem dados suficientes para avaliação"

    def test_overvalued_category(self):
        result = template_deal_verdict(
            stat_analysis={"category": "Highly Overvalued", "reasoning": "Above median"},
        )
        assert result == "Altamente acima da média"

    def test_pristine_condition(self):
        result = template_deal_verdict(
            visual={"category": "Pristine", "reasoning": "Fully renovated"},
        )
        assert result == "excelente estado"

    def test_poor_condition(self):
        result = template_deal_verdict(
            visual={"category": "Poor", "reasoning": "Major issues"},
        )
        assert result == "estado precário"

    def test_average_condition(self):
        result = template_deal_verdict(
            visual={"category": "Average", "reasoning": "Fair condition"},
        )
        assert result == "estado razoável"


# ---------------------------------------------------------------------------
# DealVerdictResult model
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# summarize_deal — mocked client tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSummarizeDeal:
    """Tests for the summarize_deal method with mocked LLM."""

    @pytest.mark.asyncio
    async def test_ollama_verdict_calls_llm(self):
        """OllamaClient.summarize_deal calls the LLM and returns its verdict."""
        client = OllamaClient.__new__(OllamaClient)
        client.base_url = "http://fake"
        client.timeout = None
        client.session = None
        client.visual_model = "llava"
        client.text_model = "llama3"

        # Mock _llm_verdict to return a canned result
        async def mock_llm(prompt):
            return DealVerdictResult(verdict="Mocked verdict from LLM", confidence=0.9)

        client._llm_verdict = mock_llm

        result = await client.summarize_deal(
            stat_analysis={"category": "Average", "reasoning": "..."},
            visual={"category": "Good", "reasoning": "..."},
            sentiment={"red_flags": [], "green_flags": ["metro"]},
        )
        assert result.verdict == "Mocked verdict from LLM"
        assert result.confidence == 0.9

    @pytest.mark.asyncio
    async def test_fallback_to_template_on_llm_error(self):
        """When LLM fails, summarize_deal falls back to the deterministic template."""
        client = OllamaClient.__new__(OllamaClient)
        client.base_url = "http://fake"
        client.timeout = None
        client.session = None
        client.visual_model = "llava"
        client.text_model = "llama3"

        # Mock _llm_verdict to raise
        async def mock_llm_error(prompt):
            raise ConnectionError("LLM unavailable")

        client._llm_verdict = mock_llm_error

        result = await client.summarize_deal(
            stat_analysis={"category": "Slightly Undervalued", "reasoning": "..."},
            visual={"category": "Good", "reasoning": "..."},
            sentiment={"red_flags": [], "green_flags": []},
        )
        # Should fall back to template
        assert "Ligeiramente subvalorizado" in result.verdict
        assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# build_deal_verdict_prompt
# ---------------------------------------------------------------------------


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
        )
        assert "Savassi" in prompt
        assert "Average" in prompt
        assert "Good" in prompt
        assert "metro" in prompt
        assert "noise" in prompt
        assert "JSON" in prompt or "json" in prompt

    def test_defaults_handled(self):
        from adapters.ai.prompts import build_deal_verdict_prompt

        prompt = build_deal_verdict_prompt()
        assert "N/A" in prompt  # default values
