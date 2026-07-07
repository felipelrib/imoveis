import asyncio
import base64
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

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
        pass

    async def _ensure_session(self):
        """Ensure HTTP session is initialized."""
        if self.session is None:
            self.session = aiohttp.ClientSession(timeout=self.timeout)


class OllamaClient(LocalAIClient):
    """Client for the Ollama REST API (``/api/generate``)."""

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

            res = await self.generate("llava", prompt, images=images, stream=False, format="json")
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
            res = await self.generate("llama3", full_prompt, stream=False, format="json")
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
    """Client for LM Studio using the OpenAI-compatible chat completions API."""

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


def create_ai_client() -> LocalAIClient:
    """Factory to create an AI client based on configuration."""
    from infra.config import get_config

    cfg = get_config()
    provider = getattr(cfg.ai, "provider", "ollama")

    if provider == "lmstudio":
        return LMStudioClient(base_url=cfg.ai.ollama_url)  # Reusing URL config for now
    else:
        # Default to Ollama
        return OllamaClient(base_url=cfg.ai.ollama_url)
