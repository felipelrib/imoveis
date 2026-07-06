"""Local AI / VLM client adapters.

Provides an abstract ``LocalAIClient`` interface with concrete implementations
for **Ollama** (``/api/generate``) and **LM Studio** (OpenAI-compatible
``/v1/chat/completions``).  A ``create_ai_client()`` factory selects the
backend based on ``get_config().ai.backend``.
"""
from __future__ import annotations

import base64
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from core.entities import SentimentAnalysisResult, VisualAnalysisResult
from infra.config import get_config
from infra.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class LocalAIClient(ABC):
    """Abstract client for local LLM/VLM HTTP services (Ollama, LM Studio, etc.)."""

    @abstractmethod
    async def analyze_visuals(
        self, image_paths: List[str], prompt: str
    ) -> VisualAnalysisResult:
        ...

    @abstractmethod
    async def analyze_text(
        self, text: str, prompt: str
    ) -> SentimentAnalysisResult:
        ...

    @abstractmethod
    async def close(self) -> None:
        ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _encode_image_b64(file_path: str) -> str:
    """Read a local image file and return its base64 string."""
    data = Path(file_path).read_bytes()
    return base64.b64encode(data).decode("utf-8")


def _safe_parse_json(raw: str) -> Dict[str, Any]:
    """Attempt to extract and parse a JSON object from *raw*.

    The model may wrap JSON in markdown fences or conversational text,
    so we extract the substring from the first '{' to the last '}'.
    Returns an empty dict on failure.
    """
    start_idx = raw.find('{')
    end_idx = raw.rfind('}')
    
    if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
        cleaned = raw[start_idx:end_idx + 1]
    else:
        cleaned = raw.strip()

    try:
        return json.loads(cleaned)  # type: ignore[no-any-return]
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("failed_json_parse", error=str(exc), raw_snippet=cleaned[:200])
        return {}


# ---------------------------------------------------------------------------
# Ollama implementation
# ---------------------------------------------------------------------------


class OllamaClient(LocalAIClient):
    """Client for the Ollama REST API (``/api/generate``)."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2-vision",
        timeout: int = 120,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_keepalive_connections=0)
        )

    # -- visuals -------------------------------------------------------------

    async def analyze_visuals(
        self, image_paths: List[str], prompt: str
    ) -> VisualAnalysisResult:
        images_b64: List[str] = []
        for p in image_paths:
            try:
                images_b64.append(_encode_image_b64(p))
            except Exception as exc:
                logger.warning("image_encode_failed", path=p, error=str(exc))

        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "images": images_b64,
            "stream": False,
            "format": "json",
        }

        logger.info(
            "ollama_visual_request",
            model=self.model,
            num_images=len(images_b64),
        )

        try:
            resp = await self._client.post(
                f"{self.base_url}/api/generate", json=payload
            )
            resp.raise_for_status()
            body = resp.json()
            parsed = _safe_parse_json(body.get("response", ""))
            logger.info("ollama_visual_response", parsed_keys=list(parsed.keys()))
        except Exception as exc:
            import traceback
            logger.error("ollama_visual_error", error=str(exc), traceback=traceback.format_exc())
            parsed = {}

        return VisualAnalysisResult(
            condition_score=float(parsed.get("condition_score", 0.5)),
            features_detected=parsed.get("features_detected", []),
            issues_detected=parsed.get("issues_detected", []),
        )

    # -- text ----------------------------------------------------------------

    async def analyze_text(
        self, text: str, prompt: str
    ) -> SentimentAnalysisResult:
        full_prompt = f"{prompt}\n\n---\n{text}"
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": full_prompt,
            "stream": False,
            "format": "json",
        }

        logger.info(
            "ollama_text_request",
            model=self.model,
            text_length=len(text),
        )

        try:
            resp = await self._client.post(
                f"{self.base_url}/api/generate", json=payload
            )
            resp.raise_for_status()
            body = resp.json()
            parsed = _safe_parse_json(body.get("response", ""))
            logger.info("ollama_text_response", parsed_keys=list(parsed.keys()))
        except Exception as exc:
            import traceback
            logger.error("ollama_text_error", error=str(exc), traceback=traceback.format_exc())
            parsed = {}

        return SentimentAnalysisResult(
            sentiment_score=float(parsed.get("sentiment_score", 0.5)),
            green_flags=parsed.get("green_flags", []),
            red_flags=parsed.get("red_flags", []),
        )

    # -- lifecycle -----------------------------------------------------------

    async def close(self) -> None:
        await self._client.aclose()
        logger.info("ollama_client_closed")


# ---------------------------------------------------------------------------
# LM Studio implementation (OpenAI-compatible)
# ---------------------------------------------------------------------------


class LMStudioClient(LocalAIClient):
    """Client for LM Studio using the OpenAI-compatible chat completions API."""

    def __init__(
        self,
        base_url: str = "http://localhost:1234",
        model: str = "llama3.2-vision",
        timeout: int = 120,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._max_tokens = get_config().ai.max_tokens
        self._client = httpx.AsyncClient(timeout=timeout)

    # -- helpers -------------------------------------------------------------

    def _build_content(
        self, prompt: str, image_paths: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Build an OpenAI-style ``content`` array (text + optional images)."""
        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for path in image_paths or []:
            try:
                b64 = _encode_image_b64(path)
                mime = "image/jpeg"
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    }
                )
            except Exception as exc:
                logger.warning("lmstudio_image_encode_failed", path=path, error=str(exc))
        return content

    def _build_payload(
        self, content: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        return {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": self._max_tokens,
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        }

    async def _chat(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        resp = await self._client.post(
            f"{self.base_url}/v1/chat/completions", json=payload
        )
        resp.raise_for_status()
        body = resp.json()
        raw_text: str = body["choices"][0]["message"]["content"]
        return _safe_parse_json(raw_text)

    # -- visuals -------------------------------------------------------------

    async def analyze_visuals(
        self, image_paths: List[str], prompt: str
    ) -> VisualAnalysisResult:
        logger.info(
            "lmstudio_visual_request",
            model=self.model,
            num_images=len(image_paths),
        )

        try:
            content = self._build_content(prompt, image_paths)
            parsed = await self._chat(self._build_payload(content))
            logger.info("lmstudio_visual_response", parsed_keys=list(parsed.keys()))
        except Exception as exc:
            logger.error("lmstudio_visual_error", error=str(exc))
            parsed = {}

        return VisualAnalysisResult(
            condition_score=float(parsed.get("condition_score", 0.5)),
            features_detected=parsed.get("features_detected", []),
            issues_detected=parsed.get("issues_detected", []),
        )

    # -- text ----------------------------------------------------------------

    async def analyze_text(
        self, text: str, prompt: str
    ) -> SentimentAnalysisResult:
        full_prompt = f"{prompt}\n\n---\n{text}"

        logger.info(
            "lmstudio_text_request",
            model=self.model,
            text_length=len(text),
        )

        try:
            content = self._build_content(full_prompt)
            parsed = await self._chat(self._build_payload(content))
            logger.info("lmstudio_text_response", parsed_keys=list(parsed.keys()))
        except Exception as exc:
            logger.error("lmstudio_text_error", error=str(exc))
            parsed = {}

        return SentimentAnalysisResult(
            sentiment_score=float(parsed.get("sentiment_score", 0.5)),
            green_flags=parsed.get("green_flags", []),
            red_flags=parsed.get("red_flags", []),
        )

    # -- lifecycle -----------------------------------------------------------

    async def close(self) -> None:
        await self._client.aclose()
        logger.info("lmstudio_client_closed")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_ai_client() -> LocalAIClient:
    """Instantiate the AI client selected by ``get_config().ai.backend``."""
    cfg = get_config().ai
    if cfg.backend == "lmstudio":
        logger.info("ai_client_factory", backend="lmstudio", model=cfg.model)
        return LMStudioClient(
            base_url=cfg.lmstudio_url, model=cfg.model, timeout=cfg.timeout_seconds
        )
    logger.info("ai_client_factory", backend="ollama", model=cfg.model)
    return OllamaClient(
        base_url=cfg.ollama_url, model=cfg.model, timeout=cfg.timeout_seconds
    )
