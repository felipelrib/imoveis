"""Fogo Cruzado geographic coverage lock (BIN-120).

Official API coverage (https://api.fogocruzado.org.br/docs): metropolitan
armed-violence occurrences in Rio de Janeiro, Pernambuco (Recife), Bahia, and
Pará only — not Minas Gerais or São Paulo.

BIN-120 decision: do **not** ingest Fogo Cruzado into neighbourhood
``safety_score`` / ``quality_meta.safety`` for operator cities (BH/SP). Use
SEJUSP/SSP rate loaders instead. Never invent armed-violence numbers from
listing AI prompts. Access requires prior authorization + JWT; this module
does not call the live API.
"""

from __future__ import annotations

from typing import Optional

COVERED_STATE_CODES: frozenset[str] = frozenset({"RJ", "PE", "BA", "PA"})

# Folded full names → UF code (accents stripped, lowercased keys).
_STATE_NAME_TO_CODE: dict[str, str] = {
    "rio de janeiro": "RJ",
    "pernambuco": "PE",
    "bahia": "BA",
    "para": "PA",
    "pará": "PA",
    "minas gerais": "MG",
    "sao paulo": "SP",
    "são paulo": "SP",
}


class FogoCruzadoCoverageError(ValueError):
    """Raised when Fogo Cruzado overlay is requested for an unsupported state."""


def _fold_accents(value: str) -> str:
    """Lowercase and strip common Portuguese accents for name matching."""
    table = str.maketrans(
        {
            "á": "a",
            "à": "a",
            "â": "a",
            "ã": "a",
            "é": "e",
            "ê": "e",
            "í": "i",
            "ó": "o",
            "ô": "o",
            "õ": "o",
            "ú": "u",
            "ü": "u",
            "ç": "c",
        }
    )
    return value.lower().translate(table)


def _normalize_state_code(state: Optional[str]) -> Optional[str]:
    if state is None:
        return None
    raw = state.strip()
    if not raw:
        return None
    upper = raw.upper()
    if len(upper) == 2 and upper.isalpha():
        return upper
    folded = _fold_accents(raw)
    # Prefer accent-stripped lookup; also try original lower for "pará" key.
    code = _STATE_NAME_TO_CODE.get(folded) or _STATE_NAME_TO_CODE.get(raw.lower())
    return code


def supports_state(state: Optional[str]) -> bool:
    """Return True iff ``state`` is in Fogo Cruzado's documented coverage."""
    code = _normalize_state_code(state)
    if code is None:
        return False
    return code in COVERED_STATE_CODES


def assert_supported_for_overlay(state: Optional[str]) -> None:
    """Raise if Fogo Cruzado must not be used as a safety overlay for ``state``.

    Operator cities (MG/SP) are explicitly unsupported — use SEJUSP/SSP loaders.
    """
    code = _normalize_state_code(state)
    if code is not None and code in COVERED_STATE_CODES:
        return
    label = (state or "").strip() or "<empty>"
    raise FogoCruzadoCoverageError(
        f"Fogo Cruzado is not covered for state {label!r} "
        f"(API covers RJ/PE/BA/PA only; BIN-120: no MG/SP ingest)"
    )
