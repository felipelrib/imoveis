"""Unit tests for embedding text helpers."""

from __future__ import annotations

from adapters.ai.embeddings import build_embedding_text, vector_literal


def test_build_embedding_text_joins_title_and_description():
    assert build_embedding_text("Apt", "Nice view", 1000) == "Apt\nNice view"


def test_build_embedding_text_truncates():
    text = build_embedding_text("Title", "x" * 100, 20)
    assert len(text) == 20
    assert text.startswith("Title\n")


def test_build_embedding_text_skips_empty():
    assert build_embedding_text("", "only desc", 100) == "only desc"
    assert build_embedding_text("only title", None, 100) == "only title"
    assert build_embedding_text(None, None, 100) == ""


def test_vector_literal():
    assert vector_literal([1.0, 2.5]) == "[1.0,2.5]"
