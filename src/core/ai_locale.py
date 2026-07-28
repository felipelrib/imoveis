"""Stable AI category codes + legacy English display-string normalization (BIN-101).

Closed vocabularies (stat bands, visual/sentiment categories) persist as snake_case
codes. Legacy EN title-case strings from older enrichments map to the same codes
on read/ingest so the SPA catalog can localize without re-scraping.
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional

# ---------------------------------------------------------------------------
# Canonical codes
# ---------------------------------------------------------------------------

STAT_BAND_CODES = (
    "highly_undervalued",
    "slightly_undervalued",
    "average",
    "slightly_overvalued",
    "highly_overvalued",
)

VISUAL_CATEGORY_CODES = (
    "pristine",
    "good",
    "average",
    "needs_renovation",
    "poor",
)

SENTIMENT_CATEGORY_CODES = (
    "highly_desirable",
    "good",
    "average",
    "undesirable",
    "poor",
)

# Legacy EN titles → codes (and identity for already-coded values)
_STAT_ALIASES: dict[str, str] = {
    "highly undervalued": "highly_undervalued",
    "slightly undervalued": "slightly_undervalued",
    "average": "average",
    "slightly overvalued": "slightly_overvalued",
    "highly overvalued": "highly_overvalued",
    **{c: c for c in STAT_BAND_CODES},
}

_VISUAL_ALIASES: dict[str, str] = {
    "pristine": "pristine",
    "good": "good",
    "average": "average",
    "needs renovation": "needs_renovation",
    "poor": "poor",
    **{c: c for c in VISUAL_CATEGORY_CODES},
}

_SENTIMENT_ALIASES: dict[str, str] = {
    "highly desirable": "highly_desirable",
    "good": "good",
    "average": "average",
    "undesirable": "undesirable",
    "poor": "poor",
    "standard": "average",
    **{c: c for c in SENTIMENT_CATEGORY_CODES},
}


def _lookup(aliases: Mapping[str, str], raw: Optional[str], default: Optional[str] = None) -> Optional[str]:
    if raw is None:
        return default
    text = str(raw).strip()
    if not text:
        return default
    key = text.lower().replace("-", "_")
    # Prefer exact snake_case / spaced EN title match
    if key in aliases:
        return aliases[key]
    spaced = key.replace("_", " ")
    if spaced in aliases:
        return aliases[spaced]
    return default if default is not None else text


def normalize_stat_category(raw: Optional[str]) -> Optional[str]:
    """Map legacy EN stat band labels (or codes) to snake_case codes."""
    return _lookup(_STAT_ALIASES, raw)


def normalize_visual_category(raw: Optional[str], *, default: str = "average") -> str:
    """Map visual condition labels to codes; unknown → ``default``."""
    return _lookup(_VISUAL_ALIASES, raw, default=default) or default


def normalize_sentiment_category(raw: Optional[str], *, default: str = "average") -> str:
    """Map sentiment labels to codes; unknown → ``default``."""
    return _lookup(_SENTIMENT_ALIASES, raw, default=default) or default


def normalize_stat_analysis_meta(stat: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a copy of ``stat_analysis`` with a normalized category code.

    Reasoning is cleared for known codes so the UI catalog owns display copy.
    Unknown legacy categories keep their raw category/reasoning for debugging.
    """
    if not stat:
        return {}
    out = dict(stat)
    raw_cat = out.get("category")
    code = normalize_stat_category(raw_cat if isinstance(raw_cat, str) else None)
    if code is None:
        return out
    out["category"] = code
    if code in STAT_BAND_CODES:
        out["reasoning"] = ""
    return out


def normalize_visual_meta(visual: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a copy of visual meta with normalized category."""
    if not visual:
        return {}
    out = dict(visual)
    raw = out.get("category")
    out["category"] = normalize_visual_category(raw if isinstance(raw, str) else None)
    return out


def normalize_sentiment_meta(sentiment: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a copy of sentiment meta with normalized category."""
    if not sentiment:
        return {}
    out = dict(sentiment)
    raw = out.get("category")
    out["category"] = normalize_sentiment_category(raw if isinstance(raw, str) else None)
    return out


def normalize_ai_meta_inplace(
    meta: MutableMapping[str, Any] | Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Normalize nested visual / sentiment / stat_analysis categories in scoring meta."""
    if not meta:
        return {}
    out = dict(meta)
    if "stat_analysis" in out:
        out["stat_analysis"] = normalize_stat_analysis_meta(out.get("stat_analysis"))
    if "visual" in out:
        out["visual"] = normalize_visual_meta(out.get("visual"))
    if "sentiment" in out:
        out["sentiment"] = normalize_sentiment_meta(out.get("sentiment"))
    return out
