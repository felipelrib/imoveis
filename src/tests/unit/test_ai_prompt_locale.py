"""BIN-101 — prompt builders expose output_language + category codes."""

from __future__ import annotations

import pytest

from adapters.ai.prompts import (
    build_deal_verdict_prompt,
    build_sentiment_prompt,
    build_visual_condition_prompt,
)


@pytest.mark.unit
class TestVisualPromptLocale:
    def test_includes_language_and_codes(self):
        prompt = build_visual_condition_prompt(2, output_language="pt-BR")
        assert "pt-BR" in prompt
        assert "needs_renovation" in prompt
        assert '"pristine"' in prompt or "'pristine'" in prompt or "pristine" in prompt
        assert "LANGUAGE RULE" in prompt
        assert "Needs Renovation" not in prompt  # enum is codes, not EN titles


@pytest.mark.unit
class TestSentimentPromptLocale:
    def test_includes_language_and_codes(self):
        prompt = build_sentiment_prompt("Apartamento em Savassi", output_language="pt-BR")
        assert "pt-BR" in prompt
        assert "highly_desirable" in prompt
        assert "LANGUAGE RULE" in prompt
        assert "Highly Desirable" not in prompt


@pytest.mark.unit
class TestDealVerdictPromptLocale:
    def test_output_language_in_prompt(self):
        prompt = build_deal_verdict_prompt(output_language="pt-BR")
        assert "pt-BR" in prompt
