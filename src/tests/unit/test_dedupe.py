"""Unit tests for the text similarity function (now using rapidfuzz Jaro-Winkler)."""
from __future__ import annotations

import pytest

from core.dedupe import text_similarity


def test_identical_strings_score_one():
    assert text_similarity("Apartamento 2 quartos", "Apartamento 2 quartos") == pytest.approx(1.0, abs=0.01)


def test_empty_strings_score_zero():
    assert text_similarity("", "") == 0.0
    assert text_similarity(None, "anything") == 0.0
    assert text_similarity("anything", None) == 0.0


def test_completely_different_strings_score_low():
    score = text_similarity("Apartamento moderno", "Casa com piscina e churrasqueira")
    assert score < 0.7


def test_similar_strings_score_high():
    # Real estate copy-paste with minor change (price diff, same text)
    a = "Lindo apartamento com 2 quartos, 1 vaga, próximo ao metrô"
    b = "Lindo apartamento com 2 quartos, 1 vaga, próximo ao metrô."
    assert text_similarity(a, b) > 0.85


def test_token_order_variation():
    # Jaro-Winkler handles transpositions better than SequenceMatcher
    a = "quarto sala cozinha"
    b = "sala cozinha quarto"
    score = text_similarity(a, b)
    # Both contain the same words — should score reasonably high
    assert score > 0.5


def test_returns_normalized_float():
    score = text_similarity("foo", "bar")
    assert 0.0 <= score <= 1.0
