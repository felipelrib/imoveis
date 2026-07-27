"""AI enrichment helpers that must stay free of Celery / DB imports."""

from __future__ import annotations

from typing import List, Tuple

from adapters.ai.client import LocalAIClient, SentimentResult, VisualResult


async def analyze_visual_and_sentiment(
    client: LocalAIClient,
    paths: List[str],
    description: str,
    visual_prompt: str,
    sentiment_prompt: str,
) -> Tuple[VisualResult, SentimentResult]:
    """Run VLM then text analysis sequentially (one GPU request at a time).

    Parallel ``asyncio.gather`` would open two Ollama KV caches under a single
    Celery GPU semaphore slot and can spill VRAM into system RAM on ~20GB cards.
    """
    visual = await client.analyze_visuals(paths, visual_prompt)
    sentiment = await client.analyze_text(description, sentiment_prompt)
    return visual, sentiment
