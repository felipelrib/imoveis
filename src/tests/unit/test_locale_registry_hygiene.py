"""Spot-check: locale branching stays in registries (BIN-103).

Fails when application code grows ``if locale == "pt-BR"`` / switcher
ternaries instead of catalog or template dicts. Scrapers' Accept-Language
headers and i18n catalog JSON are out of scope.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]

# Production surfaces that must not grow one-off locale branches.
_SCAN_GLOBS = (
    "src/adapters/ai/*.py",
    "src/adapters/metrics/*.py",
    "src/adapters/queue/*.py",
    "src/api/**/*.py",
    "src/core/**/*.py",
    "src/infra/**/*.py",
    "frontend/src/**/*.{js,jsx}",
)

_EXCLUDE_PARTS = (
    "/i18n/locales/",
    "/tests/",
    "node_modules",
)

# Allowed: membership checks against allowlists / catalog keys (not prose forks).
_FORBIDDEN = (
    re.compile(r"""if\s+locale\s*==\s*['\"]pt-BR['\"]"""),
    re.compile(r"""elif\s+locale\s*==\s*['\"]pt-BR['\"]"""),
    re.compile(r"""locale\s*===\s*['\"]pt-BR['\"]"""),
    re.compile(r"""code\s*===\s*['\"]pt-BR['\"]\s*\?"""),
)


def _iter_scan_files() -> list[Path]:
    files: list[Path] = []
    for pattern in _SCAN_GLOBS:
        files.extend(_REPO.glob(pattern))
    out: list[Path] = []
    for path in files:
        text = str(path).replace("\\", "/")
        if any(part in text for part in _EXCLUDE_PARTS):
            continue
        if path.is_file():
            out.append(path)
    return sorted(set(out))


@pytest.mark.unit
def test_no_hardcoded_pt_br_locale_branches():
    """Application code uses registries; no prose ``if locale == pt-BR`` forks."""
    offenders: list[str] = []
    for path in _iter_scan_files():
        content = path.read_text(encoding="utf-8")
        for i, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("//"):
                continue
            for pattern in _FORBIDDEN:
                if pattern.search(line):
                    rel = path.relative_to(_REPO)
                    offenders.append(f"{rel}:{i}: {stripped}")
    assert not offenders, (
        "Hardcoded locale branches found — extend template/catalog registries "
        "instead (see docs/i18n/add-a-locale.md):\n" + "\n".join(offenders)
    )


@pytest.mark.unit
def test_ai_template_locale_keys_aligned():
    """Template phrase registries share the same locale key set."""
    from adapters.ai import client as ai_client

    locales = set(ai_client._TEMPLATE_STAT)
    assert locales == set(ai_client._TEMPLATE_VISUAL)
    assert locales == set(ai_client._TEMPLATE_EMPTY)
    assert locales == set(ai_client._TEMPLATE_SENTIMENT)
    assert locales == set(ai_client._TEMPLATE_NEIGHBOURHOOD)
    assert "en" in locales and "pt-BR" in locales
