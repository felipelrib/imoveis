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
import random
import re
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Tuple

import aiohttp
import anyio
from pydantic import BaseModel, field_validator

from core.ai_locale import normalize_sentiment_category, normalize_stat_category, normalize_visual_category

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

# Template phrase catalogs (closed vocab → localized free-text fallback)
_TEMPLATE_STAT = {
    "en": {
        "highly_undervalued": "Highly undervalued",
        "slightly_undervalued": "Slightly undervalued",
        "average": "Priced near the neighbourhood average",
        "slightly_overvalued": "Slightly above neighbourhood average",
        "highly_overvalued": "Highly above neighbourhood average",
    },
    "pt-BR": {
        "highly_undervalued": "Muito abaixo do mercado",
        "slightly_undervalued": "Ligeiramente abaixo do mercado",
        "average": "Preço próximo à média do bairro",
        "slightly_overvalued": "Ligeiramente acima da média do bairro",
        "highly_overvalued": "Muito acima da média do bairro",
    },
}

_TEMPLATE_VISUAL = {
    "en": {
        "pristine": "excellent condition",
        "good": "good condition",
        "average": "average condition",
        "needs_renovation": "needs renovation",
        "poor": "poor condition",
    },
    "pt-BR": {
        "pristine": "excelente estado",
        "good": "bom estado",
        "average": "estado médio",
        "needs_renovation": "precisa de reforma",
        "poor": "mau estado",
    },
}

_TEMPLATE_EMPTY = {
    "en": "Not enough data for a deal verdict",
    "pt-BR": "Dados insuficientes para um veredito",
}

# Listing ad-claim phrases (closed templates — extend by locale key, not if/else)
_TEMPLATE_SENTIMENT = {
    "en": {
        "claims_none": "no listing claim alerts",
        "claims_one": "1 listing claim concern",
        "claims_many": "{n} listing claim concerns",
        "green_many": "{n} positive listing claims",
    },
    "pt-BR": {
        "claims_none": "sem alertas nas reivindicações do anúncio",
        "claims_one": "1 preocupação nas reivindicações do anúncio",
        "claims_many": "{n} preocupações nas reivindicações do anúncio",
        "green_many": "{n} reivindicações positivas do anúncio",
    },
}

_TEMPLATE_NEIGHBOURHOOD = {
    "en": {
        "quality": "neighbourhood quality {pct}",
        "risk_one": "1 neighbourhood risk ({flag})",
        "risk_many": "{n} neighbourhood risks",
    },
    "pt-BR": {
        "quality": "qualidade do bairro {pct}",
        "risk_one": "1 risco de bairro ({flag})",
        "risk_many": "{n} riscos de bairro",
    },
}


def _locale_key(output_language: str | None) -> str:
    if output_language in _TEMPLATE_STAT:
        return output_language  # type: ignore[return-value]
    return "en"


def _phrases(registry: dict[str, dict[str, str]], locale: str) -> dict[str, str]:
    return registry.get(locale) or registry["en"]


def _template_stat_part(stat_analysis: dict | None, locale: str) -> str | None:
    category = normalize_stat_category((stat_analysis or {}).get("category"))
    if not category:
        return None
    labels = _TEMPLATE_STAT.get(locale) or _TEMPLATE_STAT["en"]
    return labels.get(category, category)


def _template_visual_part(visual: dict | None, locale: str) -> str | None:
    raw = (visual or {}).get("category")
    if not raw:
        return None
    category = normalize_visual_category(raw if isinstance(raw, str) else None)
    labels = _TEMPLATE_VISUAL.get(locale) or _TEMPLATE_VISUAL["en"]
    return labels.get(category, category)


def _template_sentiment_parts(sentiment: dict | None, locale: str) -> list[str]:
    """Listing ad-claim signals (not objective neighbourhood truth)."""
    if not sentiment:
        return []
    red_flags = sentiment.get("red_flags")
    green_flags = sentiment.get("green_flags")
    red_flags = red_flags if isinstance(red_flags, list) else []
    green_flags = green_flags if isinstance(green_flags, list) else []
    phrases = _phrases(_TEMPLATE_SENTIMENT, locale)
    if not red_flags:
        claims_part = phrases["claims_none"]
    elif len(red_flags) == 1:
        claims_part = phrases["claims_one"]
    else:
        claims_part = phrases["claims_many"].format(n=len(red_flags))
    green_part = (
        [phrases["green_many"].format(n=len(green_flags))]
        if len(green_flags) >= 2
        else []
    )
    return [claims_part, *green_part]


def _template_neighbourhood_parts(
    neighbourhood_quality: dict | None,
    locale: str,
) -> list[str]:
    """Objective neighbourhood quality summary for the template path."""
    if not neighbourhood_quality:
        return []
    score = neighbourhood_quality.get("neighbourhood_score")
    risk_flags = neighbourhood_quality.get("risk_flags") or []
    if not isinstance(risk_flags, list):
        risk_flags = []
    phrases = _phrases(_TEMPLATE_NEIGHBOURHOOD, locale)
    parts: list[str] = []
    if score is not None:
        try:
            pct = f"{float(score):.0%}"
            parts.append(phrases["quality"].format(pct=pct))
        except (TypeError, ValueError):
            pass
    if risk_flags:
        if len(risk_flags) == 1:
            parts.append(phrases["risk_one"].format(flag=risk_flags[0]))
        else:
            parts.append(phrases["risk_many"].format(n=len(risk_flags)))
    return parts


def template_deal_verdict(
    stat_analysis: dict | None = None,
    visual: dict | None = None,
    sentiment: dict | None = None,
    neighborhood_name: str | None = None,
    neighbourhood_quality: dict | None = None,
    output_language: str = "en",
) -> str:
    """Deterministic deal verdict from scoring signals (no GPU/LLM).

    Accepts legacy EN category titles or snake_case codes. Phrases follow
    ``output_language`` (``en`` / ``pt-BR``).
    """
    del neighborhood_name  # Name is context for the LLM path; template stays place-agnostic.
    locale = _locale_key(output_language)
    parts = [
        part
        for part in (
            _template_stat_part(stat_analysis, locale),
            _template_visual_part(visual, locale),
        )
        if part
    ]
    parts.extend(_template_neighbourhood_parts(neighbourhood_quality, locale))
    parts.extend(_template_sentiment_parts(sentiment, locale))

    if not parts:
        return _TEMPLATE_EMPTY.get(locale, _TEMPLATE_EMPTY["en"])

    if len(parts) == 1:
        return parts[0]
    return parts[0] + " — " + ", ".join(parts[1:])


class AIClientError(RuntimeError):
    """Raised when a local AI backend returns a non-success response."""


def _clamp_unit_score(value: float, *, field_name: str) -> float:
    """Clamp an AI-model score onto the ``[0.0, 1.0]`` contract (BIN-148).

    Local VLM/text models occasionally drift to a 0-100 scale or emit a
    slightly out-of-range float (e.g. ``1.02``) due to rounding. Clamping
    (rather than hard-rejecting the whole result) keeps a single
    borderline/drifted value from corrupting downstream deal ranking
    (``a_score`` in ``adapters/queue/tasks.py``) while preserving the rest
    of the model's output (category, reasoning, detected features/flags).
    Genuinely malformed (non-numeric) output still fails loudly via
    Pydantic's normal type validation before this validator ever runs.
    A warning is logged so drift is visible rather than silent.
    """
    clamped = max(0.0, min(1.0, value))
    if clamped != value:
        logger.warning(
            "ai_score_out_of_range_clamped: field=%s raw=%s clamped=%s",
            field_name,
            value,
            clamped,
        )
    return clamped


class VisualResult(BaseModel):
    condition_score: float
    analysis: str = ""
    category: str = "average"
    reasoning: str = ""
    features_detected: List[str] = []
    issues_detected: List[str] = []

    @field_validator("condition_score")
    @classmethod
    def _clamp_condition_score(cls, value: float) -> float:
        return _clamp_unit_score(value, field_name="condition_score")


class DealVerdictResult(BaseModel):
    """Result of deal verdict synthesis combining all scoring signals."""

    verdict: str = ""
    confidence: float = 0.0


class SentimentResult(BaseModel):
    sentiment_score: float
    analysis: str = ""
    category: str = "average"
    reasoning: str = ""
    green_flags: List[str] = []
    red_flags: List[str] = []

    @field_validator("sentiment_score")
    @classmethod
    def _clamp_sentiment_score(cls, value: float) -> float:
        return _clamp_unit_score(value, field_name="sentiment_score")


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
        neighbourhood_quality: dict | None = None,
        output_language: str | None = None,
    ) -> DealVerdictResult:
        """Generate a natural-language deal verdict.

        Tries the LLM first; falls back to deterministic template on failure.
        Language defaults to the active UI locale (BIN-101).
        """
        try:
            from adapters.ai.prompts import build_deal_verdict_prompt
            from infra.ui_locale import resolve_ai_output_language

            lang = output_language or resolve_ai_output_language()
            prompt = build_deal_verdict_prompt(
                stat_analysis=stat_analysis,
                visual=visual,
                sentiment=sentiment,
                neighborhood_name=neighborhood_name,
                neighbourhood_quality=neighbourhood_quality,
                output_language=lang,
            )
            # Subclasses override to call their specific LLM endpoint
            result = await self._llm_verdict(prompt)
            return result
        except Exception as exc:
            logger.warning("deal_verdict_llm_fallback: %s", str(exc))
            try:
                from infra.ui_locale import resolve_ai_output_language

                lang = output_language or resolve_ai_output_language()
            except Exception:
                lang = output_language or "en"
            return DealVerdictResult(
                verdict=template_deal_verdict(
                    stat_analysis,
                    visual,
                    sentiment,
                    neighborhood_name,
                    neighbourhood_quality=neighbourhood_quality,
                    output_language=lang,
                ),
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

    @staticmethod
    def _image_max_dimension() -> int:
        """Configured longest-side px cap for VLM images (0 = disabled)."""
        try:
            from infra.config import get_config

            return int(get_config().ai.image_max_dimension)
        except Exception:  # noqa: BLE001 - never break the image path on config
            return 0

    @staticmethod
    def _read_or_make_variant(path: str, max_dim: int) -> bytes:
        """Return downscaled bytes for *path*, caching the variant on disk.

        Synchronous (Pillow + disk); call via a worker thread. Fail-open: any
        error falls back to the original file bytes so enrich never breaks.
        """
        from adapters.ai.image_ops import downscale_jpeg, variant_path

        variant = variant_path(path, max_dim)
        try:
            if variant.exists():
                return variant.read_bytes()
            raw = Path(path).read_bytes()
            out = downscale_jpeg(raw, max_dim)
            if out is not raw:  # only cache when a real downscale happened
                variant.write_bytes(out)
            return out
        except Exception:  # noqa: BLE001 - fall back to the original bytes
            return Path(path).read_bytes()

    async def _read_image_b64(self, path: str) -> str:
        """Read an image file and return base64 text, downscaled if configured.

        When ``ai.image_max_dimension`` > 0 the image is capped to that longest
        side (BIN-248) and the variant is cached next to the original.
        """
        max_dim = self._image_max_dimension()
        if max_dim > 0:
            raw = await anyio.to_thread.run_sync(
                self._read_or_make_variant, path, max_dim
            )
        else:
            async with await anyio.open_file(path, "rb") as image_file:
                raw = await image_file.read()
        return base64.b64encode(raw).decode("utf-8")

    async def _run_json_retry_loop(
        self,
        fetch: Callable[[], Awaitable[Tuple[str, Any]]],
        apply_retry_hint: Callable[[], None],
        build_result: Callable[[dict, Any], Any],
        attempts: int = 3,
    ) -> Any:
        """Call ``fetch`` up to ``attempts`` times until it yields valid JSON.

        Shared by ``OllamaClient`` and ``LMStudioClient`` for the
        analyze_visuals / analyze_text / _llm_verdict retry-on-invalid-JSON
        loop, which was previously duplicated per backend.

        ``fetch`` performs one HTTP call and returns ``(raw_text, context)``:
        ``raw_text`` is parsed as JSON, and ``context`` is passed through to
        ``build_result`` unchanged (e.g. the raw response payload, used by
        some callers as an ``analysis`` fallback distinct from the JSON
        parse text). On ``json.JSONDecodeError``, ``apply_retry_hint`` mutates
        the enclosing prompt/messages before the next attempt. The last
        ``JSONDecodeError`` is re-raised once attempts are exhausted —
        callers wrap the call in their own try/except to apply a fallback
        result and keep their own log message.
        """
        for attempt in range(attempts):
            raw_text, context = await fetch()
            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                if attempt == attempts - 1:
                    raise
                apply_retry_hint()
                continue
            return build_result(data, context)

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
        visual_model: str = "qwen2.5vl:7b",
        text_model: str = "qwen2.5vl:7b",
        embedding_model: str = "bge-m3",
        num_ctx: int = 8192,
        max_tokens: int = 1024,
    ):
        super().__init__(base_url, timeout)
        self.visual_model = visual_model
        self.text_model = text_model
        self.embedding_model = embedding_model
        self.num_ctx = num_ctx
        self.max_tokens = max_tokens

    def _ollama_options(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Merge caller options with configured num_ctx / num_predict."""
        options = dict(kwargs.pop("options", None) or {})
        if self.num_ctx and "num_ctx" not in options:
            options["num_ctx"] = int(self.num_ctx)
        if self.max_tokens and "num_predict" not in options:
            options["num_predict"] = int(self.max_tokens)
        return options

    async def _llm_verdict(self, prompt: str) -> DealVerdictResult:
        """Call Ollama for deal verdict synthesis."""
        try:
            async def fetch() -> Tuple[str, Any]:
                res = await self.generate(self.text_model, prompt, stream=False, format="json")
                return res.get("response", "{}"), None

            def apply_hint() -> None:
                nonlocal prompt
                prompt += _INVALID_JSON_RETRY_HINT

            def build(data: dict, _context: Any) -> DealVerdictResult:
                return DealVerdictResult(
                    verdict=data.get("verdict", ""),
                    confidence=float(data.get("confidence", 0.8)),
                )

            return await self._run_json_retry_loop(fetch, apply_hint, build)
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
            options = self._ollama_options(kwargs)
            data = {"model": model, "prompt": prompt, **kwargs}
            if options:
                data["options"] = options

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

            async def fetch() -> Tuple[str, Any]:
                res = await self.generate(self.visual_model, prompt, images=images, stream=False, format="json")
                return res.get("response", "{}"), res

            def apply_hint() -> None:
                nonlocal prompt
                prompt += _INVALID_JSON_RETRY_HINT

            def build(data: dict, res: Any) -> VisualResult:
                return VisualResult(
                    condition_score=data.get("condition_score", 0.5),
                    analysis=res.get("response", ""),
                    category=normalize_visual_category(data.get("category", "average")),
                    reasoning=data.get("reasoning", ""),
                    features_detected=data.get("features_detected", []),
                    issues_detected=data.get("issues_detected", []),
                )

            return await self._run_json_retry_loop(fetch, apply_hint, build)
        except Exception:
            logger.exception("Error in analyze_visuals")
            return VisualResult(condition_score=0.5, analysis="Error")

    async def analyze_text(self, description: str, prompt: str) -> SentimentResult:
        try:
            full_prompt = f"{prompt}\n\nDescription: {description}"

            async def fetch() -> Tuple[str, Any]:
                res = await self.generate(self.text_model, full_prompt, stream=False, format="json")
                return res.get("response", "{}"), res

            def apply_hint() -> None:
                nonlocal full_prompt
                full_prompt += _INVALID_JSON_RETRY_HINT

            def build(data: dict, res: Any) -> SentimentResult:
                return SentimentResult(
                    sentiment_score=data.get("sentiment_score", 0.5),
                    analysis=res.get("response", ""),
                    category=normalize_sentiment_category(data.get("category", "average")),
                    reasoning=data.get("reasoning", ""),
                    green_flags=data.get("green_flags", []),
                    red_flags=data.get("red_flags", []),
                )

            return await self._run_json_retry_loop(fetch, apply_hint, build)
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
        visual_model: str = "qwen2.5vl:7b",
        text_model: str = "qwen2.5vl:7b",
        embedding_model: str = "bge-m3",
        num_ctx: int = 8192,
        max_tokens: int = 1024,
    ):
        super().__init__(base_url, timeout)
        self.visual_model = visual_model
        self.text_model = text_model
        self.embedding_model = embedding_model
        self.num_ctx = num_ctx
        self.max_tokens = max_tokens

    async def _llm_verdict(self, prompt: str) -> DealVerdictResult:
        """Call LM Studio for deal verdict synthesis."""
        try:
            async def fetch() -> Tuple[str, Any]:
                messages = [{"role": "user", "content": prompt}]
                result = await self.chat_completions(
                    model=self.text_model,
                    messages=messages,
                    max_tokens=256,
                )
                text = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                return text, None

            def apply_hint() -> None:
                nonlocal prompt
                prompt += _INVALID_JSON_RETRY_HINT

            def build(data: dict, _context: Any) -> DealVerdictResult:
                return DealVerdictResult(
                    verdict=data.get("verdict", ""),
                    confidence=float(data.get("confidence", 0.8)),
                )

            return await self._run_json_retry_loop(fetch, apply_hint, build)
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

            async def fetch() -> Tuple[str, Any]:
                messages = [{"role": "user", "content": content}]
                result = await self.chat_completions(
                    model=self.visual_model,
                    messages=messages,
                    max_tokens=1024,
                )
                text = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                return text, text

            def apply_hint() -> None:
                if isinstance(content[0], dict) and content[0].get("type") == "text":
                    content[0]["text"] += _INVALID_JSON_RETRY_HINT

            def build(data: dict, text: str) -> VisualResult:
                return VisualResult(
                    condition_score=data.get("condition_score", 0.5),
                    analysis=data.get("analysis", text),
                    category=normalize_visual_category(data.get("category", "average")),
                    reasoning=data.get("reasoning", ""),
                    features_detected=data.get("features_detected", []),
                    issues_detected=data.get("issues_detected", []),
                )

            return await self._run_json_retry_loop(fetch, apply_hint, build)
        except Exception:
            logger.exception("Error in LMStudioClient.analyze_visuals")
            return VisualResult(condition_score=0.5, analysis="Error")

    async def analyze_text(self, description: str, prompt: str) -> SentimentResult:
        """Analyze property description text using LM Studio via chat completions."""
        try:
            full_prompt = f"{prompt}\n\nDescription: {description}"

            async def fetch() -> Tuple[str, Any]:
                messages = [{"role": "user", "content": full_prompt}]
                result = await self.chat_completions(
                    model=self.text_model,
                    messages=messages,
                    max_tokens=1024,
                )
                text = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                return text, text

            def apply_hint() -> None:
                nonlocal full_prompt
                full_prompt += _INVALID_JSON_RETRY_HINT

            def build(data: dict, text: str) -> SentimentResult:
                return SentimentResult(
                    sentiment_score=data.get("sentiment_score", 0.5),
                    analysis=data.get("analysis", text),
                    category=normalize_sentiment_category(data.get("category", "average")),
                    reasoning=data.get("reasoning", ""),
                    green_flags=data.get("green_flags", []),
                    red_flags=data.get("red_flags", []),
                )

            return await self._run_json_retry_loop(fetch, apply_hint, build)
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


class GeminiClient(LMStudioClient):
    """Client for Google Gemini via its OpenAI-compatible endpoint.

    Reuses ``LMStudioClient``'s OpenAI-style ``analyze_visuals`` /
    ``analyze_text`` / ``_llm_verdict`` (base64 ``image_url`` data-URIs + chat
    completions), overriding only transport: the Gemini base URL, bearer-key
    auth, JSON ``response_format``, and exponential-backoff retry on
    429/5xx / connection resets (the reliability gap vs a local backend that
    has no rate limit).

    Embeddings are intentionally out of scope for the A/B — semantic-search
    vectors stay on the local ``bge-m3`` backend (the ``properties.embedding``
    column is ``vector(1024)`` and mixing model vector spaces corrupts cosine
    search), so :meth:`embed` raises.

    The ``request_count`` / ``retry_count`` / ``rate_limit_hits`` counters are
    read by the A/B harness (``scripts/dev/ab_gemini_vs_ollama.py``) to report
    observed quota headroom empirically.
    """

    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
    _RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
    _MAX_BACKOFF_SECONDS = 30.0

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = 120,
        max_retries: int = 5,
    ):
        if not api_key:
            raise AIClientError(
                "GeminiClient requires a non-empty api_key (set GEMINI_API_KEY)"
            )
        # Both visual + text run on the same Gemini model; embedding_model is
        # unused (embed() raises).
        super().__init__(
            base_url=base_url,
            timeout=timeout,
            visual_model=model,
            text_model=model,
            embedding_model="",
        )
        self.api_key = api_key
        self.model = model
        self.max_retries = max(1, max_retries)
        self.request_count = 0
        self.retry_count = 0
        self.rate_limit_hits = 0
        # Last hard failure (status + short body), surfaced by the A/B harness so
        # a run that fully fell back is self-explanatory (e.g. depleted billing
        # credits vs a genuine rate limit vs a bad request).
        self.last_error = ""

    async def _sleep_backoff(self, backoff: float) -> float:
        """Sleep ``backoff`` + jitter and return the next (doubled) backoff."""
        await asyncio.sleep(backoff + random.uniform(0, backoff))
        return min(backoff * 2, self._MAX_BACKOFF_SECONDS)

    async def chat_completions(self, model: str, messages: list, **kwargs) -> Dict[str, Any]:
        """POST to Gemini's OpenAI-compatible chat endpoint with retry.

        Adds bearer-key auth and forces JSON output via ``response_format``
        (all three call sites — visual / sentiment / verdict — want JSON).
        Retries 429/5xx and connection errors with exponential backoff +
        jitter; a persistent failure raises ``AIClientError`` so the caller's
        existing try/except applies its template fallback.
        """
        self._ensure_session()
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            **kwargs,
        }

        backoff = 1.0
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            self.request_count += 1
            final_attempt = attempt == self.max_retries - 1
            try:
                async with self.session.post(url, json=payload, headers=headers) as response:
                    if response.status == 200:
                        return await response.json()
                    error_text = await response.text()
                    if response.status in self._RETRY_STATUS and not final_attempt:
                        if response.status == 429:
                            self.rate_limit_hits += 1
                        self.retry_count += 1
                        logger.warning(
                            "gemini_retry status=%s attempt=%s body=%s",
                            response.status,
                            attempt,
                            error_text[:200],
                        )
                        backoff = await self._sleep_backoff(backoff)
                        continue
                    logger.error("Gemini API error: %s - %s", response.status, error_text)
                    self.last_error = f"{response.status}: {error_text[:200].strip()}"
                    raise AIClientError(f"Gemini API error: {response.status}")
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_exc = exc
                if final_attempt:
                    logger.exception("Error calling Gemini API")
                    self.last_error = f"connection: {str(exc)[:200]}"
                    raise
                self.retry_count += 1
                logger.warning("gemini_conn_retry attempt=%s err=%s", attempt, str(exc))
                backoff = await self._sleep_backoff(backoff)

        if last_exc is not None:
            raise last_exc
        raise AIClientError("Gemini API error: retries exhausted")

    async def embed(self, text: str) -> List[float]:
        raise NotImplementedError(
            "GeminiClient embeddings are out of scope; embeddings stay on the "
            "local bge-m3 backend (see docs/features/BIN-*-gemini-ab-enrich.md)"
        )


class GemmaClient(GeminiClient):
    """Gemma models served through the Gemini OpenAI-compatible endpoint.

    Identical transport to :class:`GeminiClient` (same base URL / bearer auth /
    retry), but Gemma emits a ``<thought>…</thought>`` reasoning preamble before
    the JSON body **even in JSON mode**, which breaks the strict ``json.loads``
    in the shared retry loop. This strips that wrapper (and any prose outside the
    outermost JSON object) from each response so the inherited
    ``analyze_visuals`` / ``analyze_text`` / ``_llm_verdict`` parsing works
    unchanged. Gemma is vision-capable via ``image_url`` data-URIs (verified).
    """

    _THOUGHT_RE = re.compile(r"<thought>.*?</thought>", re.DOTALL)

    def __init__(self, api_key: str, model: str = "gemma-4-31b-it", **kwargs):
        super().__init__(api_key=api_key, model=model, **kwargs)

    @classmethod
    def _sanitize_content(cls, text: str) -> str:
        """Strip a Gemma ``<thought>`` preamble and isolate the JSON object."""
        if not text:
            return text
        cleaned = cls._THOUGHT_RE.sub("", text)
        # Handle a truncated/unclosed block: keep only what follows the marker.
        if "</thought>" in cleaned:
            cleaned = cleaned.rsplit("</thought>", 1)[-1]
        cleaned = cleaned.strip()
        # Trim stray prose around the JSON object so json.loads succeeds.
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            return cleaned[start : end + 1]
        return cleaned

    # Gemma spends completion tokens on its <thought> preamble before the JSON
    # body. The inherited verdict call caps max_tokens at 256, which Gemma can
    # exhaust mid-thought — truncating away the JSON and leaving an empty body
    # after sanitisation. Enforce a floor so thought + answer both fit.
    _MIN_MAX_TOKENS = 2048

    async def chat_completions(self, model: str, messages: list, **kwargs) -> Dict[str, Any]:
        kwargs["max_tokens"] = max(int(kwargs.get("max_tokens") or 0), self._MIN_MAX_TOKENS)
        result = await super().chat_completions(model, messages, **kwargs)
        try:
            message = (result.get("choices") or [{}])[0].get("message") or {}
            content = message.get("content")
            if isinstance(content, str):
                message["content"] = self._sanitize_content(content)
        except (IndexError, AttributeError, TypeError):
            pass  # leave the raw response; the JSON retry loop will fall back
        return result


def _gemini_client_for(model: str, **kwargs) -> "GeminiClient":
    """Pick GemmaClient for gemma-* model ids, else GeminiClient."""
    cls = GemmaClient if model.lower().startswith("gemma") else GeminiClient
    return cls(model=model, **kwargs)


def create_ai_client() -> LocalAIClient:
    """Factory to create an AI client based on configuration.

    Reads ``cfg.ai.backend`` to select the provider and passes the
    corresponding base URL and model names to the client constructor.
    """
    from infra.config import get_config

    cfg = get_config()
    backend = cfg.ai.backend

    if backend in ("gemini", "gemma"):
        # Both route through the same OpenAI-compatible endpoint; the model id
        # selects the concrete client (``gemma-*`` → GemmaClient) via
        # ``_gemini_client_for``. ``backend: gemma`` picks ``ai.gemma_model``.
        model = cfg.ai.gemma_model if backend == "gemma" else cfg.ai.gemini_model
        return _gemini_client_for(
            model,
            api_key=cfg.ai.gemini_api_key,
            base_url=cfg.ai.gemini_url,
            timeout=cfg.ai.timeout,
        )
    elif backend == "lmstudio":
        return LMStudioClient(
            base_url=cfg.ai.lmstudio_url,
            timeout=cfg.ai.timeout,
            visual_model=cfg.ai.visual_model,
            text_model=cfg.ai.text_model,
            embedding_model=cfg.ai.embedding_model,
            num_ctx=cfg.ai.num_ctx,
            max_tokens=cfg.ai.max_tokens,
        )
    else:
        # Default to Ollama
        return OllamaClient(
            base_url=cfg.ai.ollama_url,
            timeout=cfg.ai.timeout,
            visual_model=cfg.ai.visual_model,
            text_model=cfg.ai.text_model,
            embedding_model=cfg.ai.embedding_model,
            num_ctx=cfg.ai.num_ctx,
            max_tokens=cfg.ai.max_tokens,
        )
