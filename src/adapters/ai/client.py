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
from typing import Any, Dict, List

import aiohttp
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class VisualResult(BaseModel):
    condition_score: float
    analysis: str = ""
    category: str = "Standard"
    reasoning: str = ""
    features_detected: List[str] = []
    issues_detected: List[str] = []


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

    async def _ensure_session(self):
        """Ensure HTTP session is initialized."""
        if self.session is None:
            self.session = aiohttp.ClientSession(timeout=self.timeout)


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
    ):
        super().__init__(base_url, timeout)
        self.visual_model = visual_model
        self.text_model = text_model

    async def close(self) -> None:
        """Close any open connections."""
        try:
            if self.session:
                await self.session.close()
            logger.info("Closed Ollama client connection")
        except Exception as e:
            logger.error(f"Error closing Ollama client: {e}")

    async def generate(self, model: str, prompt: str, **kwargs) -> Dict[str, Any]:
        """Generate text using Ollama."""
        try:
            await self._ensure_session()

            url = f"{self.base_url}/api/generate"
            data = {"model": model, "prompt": prompt, **kwargs}

            async with self.session.post(url, json=data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Ollama API error: {response.status} - {error_text}")
                    raise Exception(f"Ollama API error: {response.status}")

                result = await response.json()
                return result

        except asyncio.TimeoutError:
            logger.error("Timeout while calling Ollama API")
            raise
        except Exception as e:
            logger.error(f"Error calling Ollama API: {e}")
            raise

    async def analyze_visuals(self, local_paths: List[str], prompt: str) -> VisualResult:
        try:
            images = []
            for path in local_paths:
                with open(path, "rb") as f:
                    images.append(base64.b64encode(f.read()).decode("utf-8"))

            res = await self.generate(self.visual_model, prompt, images=images, stream=False, format="json")
            data = json.loads(res.get("response", "{}"))
            return VisualResult(
                condition_score=data.get("condition_score", 0.5),
                analysis=res.get("response", ""),
                category=data.get("category", "Average"),
                reasoning=data.get("reasoning", ""),
                features_detected=data.get("features_detected", []),
                issues_detected=data.get("issues_detected", []),
            )
        except Exception as e:
            logger.error(f"Error in analyze_visuals: {e}")
            return VisualResult(condition_score=0.5, analysis="Error")

    async def analyze_text(self, description: str, prompt: str) -> SentimentResult:
        try:
            full_prompt = f"{prompt}\n\nDescription: {description}"
            res = await self.generate(self.text_model, full_prompt, stream=False, format="json")
            data = json.loads(res.get("response", "{}"))
            return SentimentResult(
                sentiment_score=data.get("sentiment_score", 0.5),
                analysis=res.get("response", ""),
                category=data.get("category", "Average"),
                reasoning=data.get("reasoning", ""),
                green_flags=data.get("green_flags", []),
                red_flags=data.get("red_flags", []),
            )
        except Exception as e:
            logger.error(f"Error in analyze_text: {e}")
            return SentimentResult(sentiment_score=0.5, analysis="Error")


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
    ):
        super().__init__(base_url, timeout)
        self.visual_model = visual_model
        self.text_model = text_model

    async def close(self) -> None:
        """Close any open connections."""
        try:
            if self.session:
                await self.session.close()
            logger.info("Closed LM Studio client connection")
        except Exception as e:
            logger.error(f"Error closing LM Studio client: {e}")

    async def chat_completions(self, model: str, messages: list, **kwargs) -> Dict[str, Any]:
        """Get chat completions from LM Studio."""
        try:
            await self._ensure_session()

            url = f"{self.base_url}/v1/chat/completions"
            data = {"model": model, "messages": messages, **kwargs}

            async with self.session.post(url, json=data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"LM Studio API error: {response.status} - {error_text}")
                    raise Exception(f"LM Studio API error: {response.status}")

                result = await response.json()
                return result

        except asyncio.TimeoutError:
            logger.error("Timeout while calling LM Studio API")
            raise
        except Exception as e:
            logger.error(f"Error calling LM Studio API: {e}")
            raise

    async def analyze_visuals(self, local_paths: List[str], prompt: str) -> VisualResult:
        """Analyze property images using LM Studio VLM via chat completions."""
        try:
            # Build message content with text prompt + base64 images
            content: list = [{"type": "text", "text": prompt}]
            for path in local_paths:
                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                # Determine media type from extension
                ext = path.rsplit(".", 1)[-1].lower() if "." in path else "jpeg"
                media_map = {
                    "jpg": "image/jpeg",
                    "jpeg": "image/jpeg",
                    "png": "image/png",
                    "gif": "image/gif",
                    "webp": "image/webp",
                }
                media_type = media_map.get(ext, "image/jpeg")
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{b64}"},
                })

            messages = [{"role": "user", "content": content}]
            result = await self.chat_completions(
                model=self.visual_model,
                messages=messages,
                max_tokens=1024,
            )
            text = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
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
            logger.warning("LM Studio visual analysis returned non-JSON, using raw text")
            return VisualResult(condition_score=0.5, analysis=text if "text" in dir() else "")
        except Exception as e:
            logger.error(f"Error in LMStudioClient.analyze_visuals: {e}")
            return VisualResult(condition_score=0.5, analysis="Error")

    async def analyze_text(self, description: str, prompt: str) -> SentimentResult:
        """Analyze property description text using LM Studio via chat completions."""
        try:
            full_prompt = f"{prompt}\n\nDescription: {description}"
            messages = [{"role": "user", "content": full_prompt}]
            result = await self.chat_completions(
                model=self.text_model,
                messages=messages,
                max_tokens=1024,
            )
            text = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
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
            logger.warning("LM Studio text analysis returned non-JSON, using raw text")
            return SentimentResult(sentiment_score=0.5, analysis=text if "text" in dir() else "")
        except Exception as e:
            logger.error(f"Error in LMStudioClient.analyze_text: {e}")
            return SentimentResult(sentiment_score=0.5, analysis="Error")


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
        )
    else:
        # Default to Ollama
        return OllamaClient(
            base_url=cfg.ai.ollama_url,
            timeout=cfg.ai.timeout,
            visual_model=cfg.ai.visual_model,
            text_model=cfg.ai.text_model,
        )
