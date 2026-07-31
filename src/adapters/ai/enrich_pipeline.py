"""AI enrichment helpers that must stay free of Celery / DB imports."""

from __future__ import annotations

from typing import List, Tuple

from adapters.ai.client import LocalAIClient, SentimentResult, VisualResult

# Sentiment recorded when a property carries no listing description text
# (BIN-243). Every row in the DB predated the description-enrich step, and some
# platforms (notably QuintoAndar) expose no seller free-text at all, so the text
# model was being handed an empty string. Ollama fabricated a confident
# "good/0.75"; Gemma honestly returned "no data" — either way the sentiment half
# of the deal verdict was meaningless. Skip the model entirely and record an
# explicit neutral, no-signal result instead.
SENTIMENT_NO_DESCRIPTION_REASON = (
    "No listing description available; sentiment skipped."
)


def neutral_sentiment_no_description() -> SentimentResult:
    """Honest neutral sentiment for a property with no description text."""
    return SentimentResult(
        sentiment_score=0.5,
        category="average",
        analysis="",
        reasoning=SENTIMENT_NO_DESCRIPTION_REASON,
        green_flags=[],
        red_flags=[],
    )


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

    When the listing has no description text, skip the text model altogether and
    return an explicit neutral result (BIN-243): asking the model to judge an
    empty string produced fabricated sentiment that silently corrupted the deal
    verdict, and wastes a GPU/API round-trip on nothing.
    """
    visual = await client.analyze_visuals(paths, visual_prompt)
    if not (description or "").strip():
        return visual, neutral_sentiment_no_description()
    sentiment = await client.analyze_text(description, sentiment_prompt)
    return visual, sentiment
