"""Unit tests for AI client configuration and provider selection.

Tests verify that:
- OllamaClient uses configurable visual_model and text_model (not hardcoded)
- LMStudioClient implements analyze_visuals and analyze_text correctly
- create_ai_client factory selects the right client based on config
- LMStudioClient sends correct chat-completions payloads
"""

from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

from adapters.ai.client import LMStudioClient, LocalAIClient, OllamaClient, SentimentResult, VisualResult, create_ai_client

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_VISUAL_RESPONSE = {
    "condition_score": 0.85,
    "analysis": "Good condition",
    "category": "Good",
    "reasoning": "Well maintained",
    "features_detected": ["pool", "garage"],
    "issues_detected": [],
}

FAKE_SENTIMENT_RESPONSE = {
    "sentiment_score": 0.70,
    "analysis": "Positive sentiment",
    "category": "Positive",
    "reasoning": "Good neighbourhood",
    "green_flags": ["near metro"],
    "red_flags": [],
}


def _make_ollama_response(payload: dict) -> dict:
    """Wrap a JSON payload as an Ollama generate response."""
    return {"response": json.dumps(payload)}


def _make_chat_completion(content: str) -> dict:
    """Wrap a JSON string as an OpenAI-compatible chat completion response."""
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}]
    }


# ---------------------------------------------------------------------------
# OllamaClient model configuration
# ---------------------------------------------------------------------------


class TestOllamaClientModels:
    """Verify OllamaClient uses configurable model names."""

    def test_default_models(self):
        client = OllamaClient(base_url="http://localhost:11434")
        assert client.visual_model == "llava"
        assert client.text_model == "llama3"

    def test_custom_models(self):
        client = OllamaClient(
            base_url="http://localhost:11434",
            visual_model="bakllava",
            text_model="mistral",
        )
        assert client.visual_model == "bakllava"
        assert client.text_model == "mistral"

    def test_analyze_visuals_uses_visual_model(self):
        """analyze_visuals should call generate() with self.visual_model."""
        import tempfile

        client = OllamaClient(
            base_url="http://localhost:11434",
            visual_model="custom-vlm",
        )
        client.generate = AsyncMock(return_value=_make_ollama_response(FAKE_VISUAL_RESPONSE))

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 10)
            tmp_path = f.name

        async def _run():
            try:
                result = await client.analyze_visuals([tmp_path], "test prompt")
                client.generate.assert_called_once()
                call_args = client.generate.call_args
                assert call_args[0][0] == "custom-vlm"  # positional: model
                return result
            finally:
                os.unlink(tmp_path)

        result = asyncio.run(_run())
        assert result.condition_score == 0.85

    def test_analyze_text_uses_text_model(self):
        """analyze_text should call generate() with self.text_model."""
        client = OllamaClient(
            base_url="http://localhost:11434",
            text_model="custom-text",
        )
        client.generate = AsyncMock(return_value=_make_ollama_response(FAKE_SENTIMENT_RESPONSE))

        async def _run():
            result = await client.analyze_text("nice apartment", "test prompt")
            client.generate.assert_called_once()
            call_args = client.generate.call_args
            assert call_args[0][0] == "custom-text"  # positional: model
            return result

        result = asyncio.run(_run())
        assert result.sentiment_score == 0.70


# ---------------------------------------------------------------------------
# LMStudioClient
# ---------------------------------------------------------------------------


class TestLMStudioClient:
    """Verify LMStudioClient implements analyze_visuals and analyze_text."""

    def test_has_required_methods(self):
        client = LMStudioClient()
        assert hasattr(client, "analyze_visuals")
        assert hasattr(client, "analyze_text")
        assert hasattr(client, "chat_completions")

    def test_default_models(self):
        client = LMStudioClient()
        assert client.visual_model == "llava"
        assert client.text_model == "llama3"

    def test_custom_models(self):
        client = LMStudioClient(visual_model="my-vlm", text_model="my-text")
        assert client.visual_model == "my-vlm"
        assert client.text_model == "my-text"

    def test_analyze_visuals_sends_correct_payload(self):
        """analyze_visuals should build chat-completions payload with base64 images."""
        client = LMStudioClient(visual_model="test-vlm")
        fake_response = _make_chat_completion(json.dumps(FAKE_VISUAL_RESPONSE))
        client.chat_completions = AsyncMock(return_value=fake_response)

        # Create a temporary image file
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 100)  # fake JPEG header
            tmp_path = f.name

        try:
            async def _run():
                result = await client.analyze_visuals([tmp_path], "analyze this")
                client.chat_completions.assert_called_once()
                call_args = client.chat_completions.call_args
                assert call_args[1]["model"] == "test-vlm"
                messages = call_args[1]["messages"]
                assert len(messages) == 1
                assert messages[0]["role"] == "user"
                content = messages[0]["content"]
                assert content[0]["type"] == "text"
                assert content[1]["type"] == "image_url"
                assert "data:image/jpeg;base64," in content[1]["image_url"]["url"]
                return result

            result = asyncio.run(_run())
            assert result.condition_score == 0.85
        finally:
            os.unlink(tmp_path)

    def test_analyze_text_sends_correct_payload(self):
        """analyze_text should build chat-completions payload with text prompt."""
        client = LMStudioClient(text_model="test-text")
        fake_response = _make_chat_completion(json.dumps(FAKE_SENTIMENT_RESPONSE))
        client.chat_completions = AsyncMock(return_value=fake_response)

        async def _run():
            result = await client.analyze_text("nice place", "sentiment prompt")
            client.chat_completions.assert_called_once()
            call_args = client.chat_completions.call_args
            assert call_args[1]["model"] == "test-text"
            messages = call_args[1]["messages"]
            assert len(messages) == 1
            assert messages[0]["role"] == "user"
            assert "sentiment prompt" in messages[0]["content"]
            assert "nice place" in messages[0]["content"]
            return result

        result = asyncio.run(_run())
        assert result.sentiment_score == 0.70

    def test_analyze_text_graceful_on_non_json(self):
        """analyze_text returns fallback when response is not JSON."""
        client = LMStudioClient()
        client.chat_completions = AsyncMock(
            return_value=_make_chat_completion("not json at all")
        )

        async def _run():
            return await client.analyze_text("desc", "prompt")

        result = asyncio.run(_run())
        assert result.sentiment_score == 0.5  # fallback

    def test_analyze_visuals_graceful_on_error(self):
        """analyze_visuals returns fallback on exception."""
        client = LMStudioClient()
        client.chat_completions = AsyncMock(side_effect=Exception("connection refused"))

        async def _run():
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                f.write(b"\xff\xd8" + b"\x00" * 10)
                tmp = f.name
            try:
                return await client.analyze_visuals([tmp], "prompt")
            finally:
                os.unlink(tmp)

        result = asyncio.run(_run())
        assert result.condition_score == 0.5  # fallback


# ---------------------------------------------------------------------------
# create_ai_client factory
# ---------------------------------------------------------------------------


class TestCreateAIClient:
    """Verify factory selects correct client based on config."""

    @patch("infra.config.get_config")
    def test_ollama_backend(self, mock_get_config):
        """backend=ollama should return OllamaClient with correct params."""
        mock_cfg = MagicMock()
        mock_cfg.ai.backend = "ollama"
        mock_cfg.ai.ollama_url = "http://ollama:11434"
        mock_cfg.ai.lmstudio_url = "http://lmstudio:1234"
        mock_cfg.ai.visual_model = "bakllava"
        mock_cfg.ai.text_model = "mistral"
        mock_cfg.ai.timeout = 60
        mock_get_config.return_value = mock_cfg

        client = create_ai_client()
        assert isinstance(client, OllamaClient)
        assert client.base_url == "http://ollama:11434"
        assert client.visual_model == "bakllava"
        assert client.text_model == "mistral"
        assert client.timeout.total == 60

    @patch("infra.config.get_config")
    def test_lmstudio_backend(self, mock_get_config):
        """backend=lmstudio should return LMStudioClient with correct params."""
        mock_cfg = MagicMock()
        mock_cfg.ai.backend = "lmstudio"
        mock_cfg.ai.ollama_url = "http://ollama:11434"
        mock_cfg.ai.lmstudio_url = "http://lmstudio:1234"
        mock_cfg.ai.visual_model = "my-vlm"
        mock_cfg.ai.text_model = "my-text"
        mock_cfg.ai.timeout = 90
        mock_get_config.return_value = mock_cfg

        client = create_ai_client()
        assert isinstance(client, LMStudioClient)
        assert client.base_url == "http://lmstudio:1234"
        assert client.visual_model == "my-vlm"
        assert client.text_model == "my-text"
        assert client.timeout.total == 90

    @patch("infra.config.get_config")
    def test_unknown_backend_defaults_to_ollama(self, mock_get_config):
        """Unknown backend should default to Ollama."""
        mock_cfg = MagicMock()
        mock_cfg.ai.backend = "unknown"
        mock_cfg.ai.ollama_url = "http://ollama:11434"
        mock_cfg.ai.lmstudio_url = "http://lmstudio:1234"
        mock_cfg.ai.visual_model = "llava"
        mock_cfg.ai.text_model = "llama3"
        mock_cfg.ai.timeout = 30
        mock_get_config.return_value = mock_cfg

        client = create_ai_client()
        assert isinstance(client, OllamaClient)


# ---------------------------------------------------------------------------
# Import / type sanity
# ---------------------------------------------------------------------------


class TestAIModels:
    """Basic model sanity checks (kept from original test_ai_quality.py)."""

    def test_visual_result_defaults(self):
        v = VisualResult(condition_score=0.5)
        assert isinstance(v.condition_score, float)
        assert v.category == "Standard"

    def test_sentiment_result_defaults(self):
        s = SentimentResult(sentiment_score=0.5)
        assert isinstance(s.sentiment_score, float)
        assert s.category == "Standard"

    def test_issubclass_local_ai_client(self):
        assert issubclass(OllamaClient, LocalAIClient)
        assert issubclass(LMStudioClient, LocalAIClient)
