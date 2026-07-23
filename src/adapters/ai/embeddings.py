"""Helpers for property text embeddings (semantic search)."""

from __future__ import annotations


def build_embedding_text(
    title: str | None,
    description: str | None,
    max_chars: int,
) -> str:
    """Build ``title\\ndescription`` truncated to ``max_chars``."""
    parts: list[str] = []
    if title and title.strip():
        parts.append(title.strip())
    if description and description.strip():
        parts.append(description.strip())
    text = "\n".join(parts)
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars]
    return text


def vector_literal(embedding: list[float]) -> str:
    """Format a float list as a pgvector literal ``[1.0,2.0,...]``."""
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"
