"""Golden-file tests for AI output quality validation.

These tests compare AI-generated scores against known baselines to detect
regression after prompt or model changes.  Requires Ollama to be reachable
— skipped gracefully in CI environments where OLLAMA_HOST is not available.
"""

from __future__ import annotations

import os

import pytest

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
CONDITION_SCORE_TOLERANCE = 0.15  # max allowed deviation from golden value
SENTIMENT_SCORE_TOLERANCE = 0.15


@pytest.fixture(autouse=True)
def _skip_if_ollama_unavailable():
    """Skip all tests in this module if Ollama is not reachable."""
    ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    import urllib.request

    try:
        req = urllib.request.Request(f"{ollama_host}/api/tags")
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pytest.skip(f"Ollama not reachable at {ollama_host}")


# ---------------------------------------------------------------------------
# Golden-file fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def golden_samples():
    """A hand-curated set of property descriptions with expected AI scores."""
    return [
        {
            "description": (
                "Apartamento de 2 quartos em Savassi, 75m², bem localizado, "
                "próximo a restaurantes e shoppings. Prédio com portaria 24h, "
                "piscina e academia. Imóvel bem conservado, recém-pintado."
            ),
            "expected_condition": 0.75,
            "expected_sentiment": 0.70,
        },
        {
            "description": (
                "Casa antiga em bairro afastado, precisa de reforma geral. "
                "Telhado com infiltração, pintura descascada, piso danificado. "
                "Sem garagem, rua sem asfalto. Venda urgente."
            ),
            "expected_condition": 0.20,
            "expected_sentiment": 0.15,
        },
        {
            "description": (
                "Cobertura duplex de alto padrão, 200m², 3 suítes, vista "
                "panorâmica. Acabamento em mármore, cozinha planejada, "
                "4 vagas de garagem. Condomínio com piscina aquecida, "
                "sauna, salão de festas e espaço gourmet. Imóvel novo."
            ),
            "expected_condition": 0.95,
            "expected_sentiment": 0.92,
        },
        {
            "description": (
                "Kitnet pequena no centro, 25m², ideal para estudante. "
                "Prédio simples sem elevador. Imóvel funcional mas "
                "compacto. Banheiro pequeno, sem vaga de garagem."
            ),
            "expected_condition": 0.40,
            "expected_sentiment": 0.45,
        },
        {
            "description": (
                "Sobrado médio em bairro residencial, 3 quartos, "
                "120m², garagem para 2 carros. Casa arejada com quintal. "
                "Precisa de pequenos reparos na pintura externa. "
                "Bom estado geral, bem cuidada."
            ),
            "expected_condition": 0.60,
            "expected_sentiment": 0.65,
        },
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAIGoldenFiles:
    """Regression tests comparing AI output to golden baseline scores."""

    def test_condition_scores_within_tolerance(self, golden_samples):
        """Each golden sample's condition score must be within ±0.15."""
        from adapters.ai.client import OllamaClient
        from adapters.ai.prompts import CONDITION_ANALYSIS_PROMPT

        failures = []
        async def _run():
            client = OllamaClient(base_url=os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
            async with client:
                for i, sample in enumerate(golden_samples):
                    result = await client.analyze_text(
                        sample["description"], CONDITION_ANALYSIS_PROMPT
                    )
                    deviation = abs(result.sentiment_score - sample["expected_condition"])
                    if deviation > CONDITION_SCORE_TOLERANCE:
                        failures.append(
                            f"Sample {i}: expected {sample['expected_condition']:.2f}, "
                            f"got {result.sentiment_score:.2f} (deviation {deviation:.2f})"
                        )

        import asyncio
        asyncio.run(_run())

        if failures:
            pytest.fail(
                f"AI condition scores deviated >{CONDITION_SCORE_TOLERANCE} for {len(failures)} samples:\n"
                + "\n".join(failures)
            )

    def test_ai_client_imports_and_types(self):
        """Ensure AI client models are importable and correctly typed."""
        from adapters.ai.client import SentimentResult, VisualResult

        # Instantiate default results without errors
        v = VisualResult(condition_score=0.5)
        assert isinstance(v.condition_score, float)

        s = SentimentResult(sentiment_score=0.5)
        assert isinstance(s.sentiment_score, float)