# core package init
#
# Deferred imports: keep __init__.py lightweight so that importing a single
# submodule (e.g. ``from src.core.exceptions import ConfigError``) does not
# pull in the full dependency graph.


def __getattr__(name: str):  # noqa: ANN001
    if name == "match_or_create_property":
        from .dedupe import match_or_create_property
        return match_or_create_property
    if name in {
        "DedupeResult",
        "LocationData",
        "PropertyCandidate",
        "ScoringWeights",
        "SentimentAnalysisResult",
        "VisualAnalysisResult",
    }:
        from . import entities
        return getattr(entities, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
