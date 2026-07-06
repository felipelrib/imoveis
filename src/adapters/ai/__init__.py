"""AI adapter package — local VLM/LLM clients, prompts, and image management."""

from .client import LMStudioClient, LocalAIClient, OllamaClient, create_ai_client
from .image_store import ImageStore
from .prompts import build_sentiment_prompt, build_visual_condition_prompt

__all__ = [
    "LocalAIClient",
    "OllamaClient",
    "LMStudioClient",
    "create_ai_client",
    "build_visual_condition_prompt",
    "build_sentiment_prompt",
    "ImageStore",
]
