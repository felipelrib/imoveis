"""AI client abstraction for local LLM/VLM services (Ollama, LM Studio).

Supports configurable backends via ``infra.config.AIConfig``:

- ``backend`` selects Ollama or LM Studio.
- ``visual_model`` and ``text_model`` control which models are called for
  image analysis and text/sentiment analysis respectively.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import Any, Dict, List

import aiohttp
import anyio
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_INVALID_JSON_RETRY_HINT = "\n\nYour last response was invalid JSON. Return ONLY valid JSON."
_MEDIA_TYPE_JPEG = "image/jpeg"
_MEDIA_TYPE_BY_EXT = {
    "jpg": _MEDIA_TYPE_JPEG,
    "jpeg": _MEDIA_TYPE_JPEG,
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}


class AIClientError(RuntimeError):
    """Raised when a local AI backend returns a non-success response."""


class VisualResult(BaseModel):
    condition_score: float
    analysis: str = ""
    category: str = "Standard"
    reasoning: str = ""
    features_detected: List[str] = []
    issues_detected: List[str] = []


class DealVerdictResult(BaseModel):
    """Result of deal verdict synthesis combining all scoring signals."""
    verdict: str = ""
    confidence: float = 0.0


def _template_stat_part(stat_analysis: dict | None) -> str | None:
    category = (stat_analysis or {}).get("category")
    labels = {
        "Highly Undervalued": "Altamente subvalorizado",
        "Slightly Undervalued": "Ligeiramente subvalorizado",
        "Average": "Preço dentro da média",
        "Slightly Overvalued": "Ligeiramente acima da média",
        "Highly Overvalued": "Altamente acima da média",
    }
    return labels.get(category, category) if category else None


def _template_visual_part(visual: dict | None) -> str | None:
    category = (visual or {}).get("category")
    labels = {
        "Pristine": "excelente estado",
        "Good": "boa condição",
        "Average": "estado razoável",
        "Needs Renovation": "precisa de reforma",
        "Poor": "estado precário",
    }
    return labels.get(category, category.lower()) if category else None


def _template_sentiment_parts(sentiment: dict | None) -> list[str]:
    if not sentiment:
        return []
    red_flags = sentiment.get("red_flags")
    green_flags = sentiment.get("green_flags")
    red_flags = red_flags if isinstance(red_flags, list) else []
    green_flags = green_flags if isinstance(green_flags, list) else []
    location_part = (
        "sem alertas" if not red_flags
        else "1 preocupação na localização" if len(red_flags) == 1
        else f"{len(red_flags)} preocupações na localização"
    )
    return [location_part, *([f"{len(green_flags)} aspectos positivos"] if len(green_flags) >= 2 else [])]


def template_deal_verdict(
    stat_analysis: dict | None = None,
    visual: dict | None = None,
    sentiment: dict | None = None,
    neighborhood_name: str | None = None,
) -> str:
    """Deterministic PT-BR deal verdict from the three scoring signals.

    Works without GPU/LLM.  Returns a concise sentence combining:
    - Statistical positioning relative to neighbourhood median
    - Visual condition assessment
    - Location sentiment / red-flag count

    Examples
    --------
    >>> template_deal_verdict(
    ...     stat_analysis={"category": "Slightly Undervalued", "reasoning": "..."},
    ...     visual={"category": "Good", "reasoning": "..."},
    ...     sentiment={"category": "Highly Desirable", "reasoning": "...", "red_flags": []},
    ...     neighborhood_name="Savassi",
    ... )
    'Ligeiramente subvalorizado — boa condição, localização desejável, sem alertas'
    """
    del neighborhood_name  # The template intentionally remains neighborhood-agnostic.
    parts = [
        part
        for part in (_template_stat_part(stat_analysis), _template_visual_part(visual))
        if part
    ]
    parts.extend(_template_sentiment_parts(sentiment))

    if not parts:
        return "Sem dados suficientes para avaliação"

    # Join with em-dash for first part, commas for rest
    if len(parts) == 1:
        return parts[0]
    return parts[0] + " — " + ", ".join(parts[1:])


class SentimentResult(BaseModel):
    sentiment_score: float
    analysis: str = ""
    category: str = "Standard"
    reasoning: str = ""
    green_flags: List[str] = []
    red_flags: List[str] = []


class LocalAIClient(ABC):
    """Abstract client for local LLM/VLM HTTP services (Ollama, LM Studio, etc.)."""

    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session = None

    async def __aenter__(self):
        if self.session is None:
            self.session = aiohttp.ClientSession(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    @abstractmethod
    async def close(self) -> None:
        """Close any open connections."""

    async def summarize_deal(
        self,
        stat_analysis: dict | None = None,
        visual: dict | None = None,
        sentiment: dict | None = None,
        neighborhood_name: str | None = None,
    ) -> DealVerdictResult:
        """Generate a natural-language deal verdict.

        Tries the LLM first; falls back to deterministic template on failure.
        """
        try:
            from adapters.ai.prompts import build_deal_verdict_prompt
            from infra.config import get_config
            cfg = get_config()
            prompt = build_deal_verdict_prompt(
                stat_analysis=stat_analysis,
                visual=visual,
                sentiment=sentiment,
                neighborhood_name=neighborhood_name,
                output_language=cfg.ai.output_language,
            )
            # Subclasses override to call their specific LLM endpoint
            result = await self._llm_verdict(prompt)
            return result
        except Exception as exc:
            logger.warning("deal_verdict_llm_fallback: %s", str(exc))
            return DealVerdictResult(
                verdict=template_deal_verdict(stat_analysis, visual, sentiment, neighborhood_name),
                confidence=0.0,
            )

    async def _llm_verdict(self, prompt: str) -> DealVerdictResult:
        """LLM call — to be overridden by concrete clients."""
        raise NotImplementedError

    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """Return an embedding vector for ``text``."""

    def _ensure_session(self) -> None:
        """Ensure HTTP session is initialized."""
        if self.session is None:
            self.session = aiohttp.ClientSession(timeout=self.timeout)

    async def _read_image_b64(self, path: str) -> str:
        """Read an image file asynchronously and return base64 text."""
        async with await anyio.open_file(path, "rb") as image_file:
            raw = await image_file.read()
        return base64.b64encode(raw).decode("utf-8")

    @asynccontextmanager
    async def session_context(self):
        """Use client session as an async context manager."""
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            self.session = session
            try:
                yield session
            finally:
                self.session = None


class OllamaClient(LocalAIClient):
    """Client for the Ollama REST API (``/api/generate``).

    Parameters
    ----------
    base_url:
        Ollama server URL.
    visual_model:
        Model name for image analysis (VLM).
    text_model:
        Model name for text / sentiment analysis.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        timeout: int = 30,
        visual_model: str = "llava",
        text_model: str = "llama3",
        embedding_model: str = "nomic-embed-text",
    ):
        super().__init__(base_url, timeout)
        self.visual_model = visual_model
        self.text_model = text_model
        self.embedding_model = embedding_model

    async def _llm_verdict(self, prompt: str) -> DealVerdictResult:
        """Call Ollama for deal verdict synthesis."""
        try:
            for attempt in range(3):
                res = await self.generate(self.text_model, prompt, stream=False, format="json")
                try:
                    data = json.loads(res.get("response", "{}"))
                    return DealVerdictResult(
                        verdict=data.get("verdict", ""),
                        confidence=float(data.get("confidence", 0.8)),
                    )
                except json.JSONDecodeError:
                    if attempt == 2:
                        raise
                    prompt += _INVALID_JSON_RETRY_HINT
        except Exception as exc:
            logger.warning("ollama_verdict_error: %s", str(exc))
            return DealVerdictResult(
                verdict=template_deal_verdict(),
                confidence=0.0,
            )

    async def close(self) -> None:
        """Close any open connections."""
        try:
            if self.session:
                await self.session.close()
            logger.info("Closed Ollama client connection")
        except Exception:
            logger.exception("Error closing Ollama client")

    async def generate(self, model: str, prompt: str, **kwargs) -> Dict[str, Any]:
        """Generate text using Ollama."""
        try:
            self._ensure_session()

            url = f"{self.base_url}/api/generate"
            data = {"model": model, "prompt": prompt, **kwargs}

            async with self.session.post(url, json=data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error("Ollama API error: %s - %s", response.status, error_text)
                    raise AIClientError(f"Ollama API error: {response.status}")

                result = await response.json()
                return result

        except asyncio.TimeoutError:
            logger.exception("Timeout while calling Ollama API")
            raise
        except Exception:
            logger.exception("Error calling Ollama API")
            raise

    async def analyze_visuals(self, local_paths: List[str], prompt: str) -> VisualResult:
        try:
            images = [await self._read_image_b64(path) for path in local_paths]

            for attempt in range(3):
                res = await self.generate(self.visual_model, prompt, images=images, stream=False, format="json")
                try:
                    data = json.loads(res.get("response", "{}"))
                    return VisualResult(
                        condition_score=data.get("condition_score", 0.5),
                        analysis=res.get("response", ""),
                        category=data.get("category", "Average"),
                        reasoning=data.get("reasoning", ""),
                        features_detected=data.get("features_detected", []),
                        issues_detected=data.get("issues_detected", []),
                    )
                except json.JSONDecodeError:
                    if attempt == 2:
                        raise
                    prompt += _INVALID_JSON_RETRY_HINT
        except Exception:
            logger.exception("Error in analyze_visuals")
            return VisualResult(condition_score=0.5, analysis="Error")

    async def analyze_text(self, description: str, prompt: str) -> SentimentResult:
        try:
            full_prompt = f"{prompt}\n\nDescription: {description}"
            for attempt in range(3):
                res = await self.generate(self.text_model, full_prompt, stream=False, format="json")
                try:
                    data = json.loads(res.get("response", "{}"))
                    return SentimentResult(
                        sentiment_score=data.get("sentiment_score", 0.5),
                        analysis=res.get("response", ""),
                        category=data.get("category", "Average"),
                        reasoning=data.get("reasoning", ""),
                        green_flags=data.get("green_flags", []),
                        red_flags=data.get("red_flags", []),
                    )
                except json.JSONDecodeError:
                    if attempt == 2:
                        raise
                    full_prompt += _INVALID_JSON_RETRY_HINT
        except Exception:
            logger.exception("Error in analyze_text")
            return SentimentResult(sentiment_score=0.5, analysis="Error")

    async def embed(self, text: str) -> List[float]:
        """Embed text via Ollama ``POST /api/embeddings``."""
        self._ensure_session()
        url = f"{self.base_url}/api/embeddings"
        payload = {"model": self.embedding_model, "prompt": text}
        async with self.session.post(url, json=payload) as response:
            if response.status != 200:
                error_text = await response.text()
                logger.error("Ollama embeddings error: %s - %s", response.status, error_text)
                raise AIClientError(f"Ollama embeddings error: {response.status}")
            result = await response.json()
        embedding = result.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise ValueError("Ollama embeddings response missing embedding list")
        return [float(x) for x in embedding]


class LMStudioClient(LocalAIClient):
    """Client for LM Studio using the OpenAI-compatible chat completions API.

    Parameters
    ----------
    base_url:
        LM Studio server URL.
    visual_model:
        Model name for image analysis (VLM).
    text_model:
        Model name for text / sentiment analysis.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:1234",
        timeout: int = 30,
        visual_model: str = "llava",
        text_model: str = "llama3",
        embedding_model: str = "nomic-embed-text",
    ):
        super().__init__(base_url, timeout)
        self.visual_model = visual_model
        self.text_model = text_model
        self.embedding_model = embedding_model

    async def _llm_verdict(self, prompt: str) -> DealVerdictResult:
        """Call LM Studio for deal verdict synthesis."""
        try:
            for attempt in range(3):
                messages = [{"role": "user", "content": prompt}]
                result = await self.chat_completions(
                    model=self.text_model,
                    messages=messages,
                    max_tokens=256,
                )
                text = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                try:
                    data = json.loads(text)
                    return DealVerdictResult(
                        verdict=data.get("verdict", ""),
                        confidence=float(data.get("confidence", 0.8)),
                    )
                except json.JSONDecodeError:
                    if attempt == 2:
                        raise
                    prompt += _INVALID_JSON_RETRY_HINT
        except Exception as exc:
            logger.warning("lmstudio_verdict_error: %s", str(exc))
            return DealVerdictResult(
                verdict=template_deal_verdict(),
                confidence=0.0,
            )

    async def close(self) -> None:
        """Close any open connections."""
        try:
            if self.session:
                await self.session.close()
            logger.info("Closed LM Studio client connection")
        except Exception:
            logger.exception("Error closing LM Studio client")

    async def chat_completions(self, model: str, messages: list, **kwargs) -> Dict[str, Any]:
        """Get chat completions from LM Studio."""
        try:
            self._ensure_session()

            url = f"{self.base_url}/v1/chat/completions"
            data = {"model": model, "messages": messages, **kwargs}

            async with self.session.post(url, json=data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error("LM Studio API error: %s - %s", response.status, error_text)
                    raise AIClientError(f"LM Studio API error: {response.status}")

                result = await response.json()
                return result

        except asyncio.TimeoutError:
            logger.exception("Timeout while calling LM Studio API")
            raise
        except Exception:
            logger.exception("Error calling LM Studio API")
            raise

    async def analyze_visuals(self, local_paths: List[str], prompt: str) -> VisualResult:
        """Analyze property images using LM Studio VLM via chat completions."""
        text = "<unread>"
        try:
            # Build message content with text prompt + base64 images
            content: list = [{"type": "text", "text": prompt}]
            for path in local_paths:
                b64 = await self._read_image_b64(path)
                ext = path.rsplit(".", 1)[-1].lower() if "." in path else "jpeg"
                media_type = _MEDIA_TYPE_BY_EXT.get(ext, _MEDIA_TYPE_JPEG)
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{b64}"},
                })

            for attempt in range(3):
                messages = [{"role": "user", "content": content}]
                result = await self.chat_completions(
                    model=self.visual_model,
                    messages=messages,
                    max_tokens=1024,
                )
                text = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                try:
                    data = json.loads(text)
                    return VisualResult(
                        condition_score=data.get("condition_score", 0.5),
                        analysis=data.get("analysis", text),
                        category=data.get("category", "Average"),
                        reasoning=data.get("reasoning", ""),
                        features_detected=data.get("features_detected", []),
                        issues_detected=data.get("issues_detected", []),
                    )
                except json.JSONDecodeError:
                    if attempt == 2:
                        raise
                    if isinstance(content[0], dict) and content[0].get("type") == "text":
                        content[0]["text"] += _INVALID_JSON_RETRY_HINT
        except Exception:
            logger.exception("Error in LMStudioClient.analyze_visuals")
            return VisualResult(condition_score=0.5, analysis="Error")

    async def analyze_text(self, description: str, prompt: str) -> SentimentResult:
        """Analyze property description text using LM Studio via chat completions."""
        text = "<unread>"
        try:
            full_prompt = f"{prompt}\n\nDescription: {description}"
            for attempt in range(3):
                messages = [{"role": "user", "content": full_prompt}]
                result = await self.chat_completions(
                    model=self.text_model,
                    messages=messages,
                    max_tokens=1024,
                )
                text = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                try:
                    data = json.loads(text)
                    return SentimentResult(
                        sentiment_score=data.get("sentiment_score", 0.5),
                        analysis=data.get("analysis", text),
                        category=data.get("category", "Average"),
                        reasoning=data.get("reasoning", ""),
                        green_flags=data.get("green_flags", []),
                        red_flags=data.get("red_flags", []),
                    )
                except json.JSONDecodeError:
                    if attempt == 2:
                        raise
                    full_prompt += _INVALID_JSON_RETRY_HINT
        except Exception:
            logger.exception("Error in LMStudioClient.analyze_text")
            return SentimentResult(sentiment_score=0.5, analysis="Error")

    async def embed(self, text: str) -> List[float]:
        """Embed text via LM Studio OpenAI-compatible ``POST /v1/embeddings``."""
        self._ensure_session()
        url = f"{self.base_url}/v1/embeddings"
        payload = {"model": self.embedding_model, "input": text}
        async with self.session.post(url, json=payload) as response:
            if response.status != 200:
                error_text = await response.text()
                logger.error("LM Studio embeddings error: %s - %s", response.status, error_text)
                raise AIClientError(f"LM Studio embeddings error: {response.status}")
            result = await response.json()
        data = result.get("data") or []
        if not data or not isinstance(data[0].get("embedding"), list):
            raise ValueError("LM Studio embeddings response missing embedding list")
        return [float(x) for x in data[0]["embedding"]]


def create_ai_client() -> LocalAIClient:
    """Factory to create an AI client based on configuration.

    Reads ``cfg.ai.backend`` to select the provider and passes the
    corresponding base URL and model names to the client constructor.
    """
    from infra.config import get_config

    cfg = get_config()
    backend = cfg.ai.backend

    if backend == "lmstudio":
        return LMStudioClient(
            base_url=cfg.ai.lmstudio_url,
            timeout=cfg.ai.timeout,
            visual_model=cfg.ai.visual_model,
            text_model=cfg.ai.text_model,
            embedding_model=cfg.ai.embedding_model,
        )
    else:
        # Default to Ollama
        return OllamaClient(
            base_url=cfg.ai.ollama_url,
            timeout=cfg.ai.timeout,
            visual_model=cfg.ai.visual_model,
            text_model=cfg.ai.text_model,
            embedding_model=cfg.ai.embedding_model,
        )
