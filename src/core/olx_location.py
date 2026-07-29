"""Reconcile OLX seller/region location with property location from title/body.

OLX ``locationDetails`` often reflects the seller or listing metro area, not the
property. Titles like ``Cobertura no Itapoã`` or ``Vendo casa em Cabo Frio`` are
more reliable. This module applies a fast heuristic, optionally calls local AI
with an allowlist + neighborhood catalog, then updates candidate fields.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

from core.geo_allowlist import _canonical_city, _fold, passes_geo_allowlist

_LOC_PHRASE_RE = re.compile(
    r"\b(?:em|no|na|nos|nas|bairro(?:\s+do|\s+da)?)\s+([A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9\s\-']{1,40})",
    re.IGNORECASE,
)


def _slug_to_label(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").strip().title()


def _neighborhood_looks_like_city(
    neighborhood: str | None, allowed_cities: Sequence[str]
) -> bool:
    """True when ``neighborhood`` is actually an allowlisted city name."""
    if not neighborhood or not str(neighborhood).strip():
        return False
    nb_canon = _canonical_city(neighborhood)
    if not nb_canon:
        return False
    return any(_canonical_city(c) == nb_canon for c in allowed_cities if c)


@dataclass(frozen=True)
class OlxLocationResult:
    """Outcome of OLX location reconciliation."""

    action: str  # unchanged | corrected | out_of_geo | ai_failed
    city: Optional[str] = None
    state: Optional[str] = None
    neighborhood: Optional[str] = None
    address: Optional[str] = None
    clear_coords: bool = False
    mismatch_suspected: bool = False
    reason: str = ""
    confidence: float = 0.0


def humanize_neighborhood_slugs(slugs: Sequence[str]) -> list[str]:
    """Turn YAML slugs into display labels for catalog / heuristic matching."""
    return [_slug_to_label(s) for s in slugs if s and str(s).strip()]


def _best_catalog_match(token: str, catalog: Sequence[str]) -> Optional[str]:
    folded_token = _fold(token)
    if not folded_token or len(folded_token) < 3:
        return None
    for name in catalog:
        folded_name = _fold(name)
        if not folded_name:
            continue
        if folded_token == folded_name or folded_name in folded_token or folded_token in folded_name:
            return name
    return None


def _phrases_from_text(text: str) -> list[str]:
    return [m.group(1).strip() for m in _LOC_PHRASE_RE.finditer(text or "")]


def suspect_location_mismatch(
    *,
    title: str | None,
    description: str | None,
    scraped_city: str | None,
    scraped_neighborhood: str | None,
    allowed_cities: Sequence[str],
    known_neighborhoods: Sequence[str],
) -> tuple[bool, Optional[str], Optional[str], str]:
    """Return (suspected, hinted_city, hinted_neighborhood, reason).

    Pure heuristic — no AI. Hinted values are best-effort catalog matches.
    """
    blob = f"{title or ''}\n{description or ''}"
    if not blob.strip():
        return False, None, None, "empty_text"

    scraped_city_f = _canonical_city(scraped_city) if scraped_city else ""
    scraped_nb_f = _fold(scraped_neighborhood) if scraped_neighborhood else ""
    allowed_f = {_canonical_city(c) for c in allowed_cities if c}
    nb_is_city = _neighborhood_looks_like_city(scraped_neighborhood, allowed_cities)

    hinted_city: Optional[str] = None
    hinted_nb: Optional[str] = None

    # Direct catalog neighborhood hits in title/description.
    for name in known_neighborhoods:
        folded = _fold(name)
        if len(folded) < 4:
            continue
        if folded in _fold(blob) and (folded != scraped_nb_f or nb_is_city):
            hinted_nb = name
            break

    for phrase in _phrases_from_text(blob):
        city_hit = _best_catalog_match(phrase, list(allowed_cities))
        if city_hit and _canonical_city(city_hit) != scraped_city_f:
            hinted_city = city_hit
        nb_hit = _best_catalog_match(phrase, known_neighborhoods)
        if nb_hit and (_fold(nb_hit) != scraped_nb_f or nb_is_city):
            hinted_nb = hinted_nb or nb_hit
        # Phrase that looks like a city but is not allowlisted → out-of-geo hint.
        if not city_hit and not nb_hit:
            # Keep raw phrase as city hint when it does not match scraped city.
            if scraped_city_f and _fold(phrase) != scraped_city_f and _fold(phrase) not in allowed_f:
                if len(_fold(phrase)) >= 5 and not hinted_city:
                    hinted_city = phrase.strip()

    if nb_is_city:
        # Seller/region put a city name in the neighborhood field.
        if not hinted_city and scraped_neighborhood:
            if scraped_city_f and scraped_city_f != _canonical_city(scraped_neighborhood):
                hinted_city = scraped_city
            else:
                hinted_city = scraped_neighborhood
        return True, hinted_city, hinted_nb, "neighborhood_is_city"

    if not scraped_neighborhood:
        if hinted_nb or hinted_city:
            return True, hinted_city, hinted_nb, "neighborhood_missing"
        return True, None, None, "neighborhood_missing"

    if hinted_nb and _fold(hinted_nb) != scraped_nb_f:
        return True, hinted_city, hinted_nb, "neighborhood_mismatch"
    if hinted_city and _canonical_city(hinted_city) != scraped_city_f:
        return True, hinted_city, hinted_nb, "city_mismatch"
    return False, None, None, "ok"


def _rebuild_address(
    *,
    neighborhood: str | None,
    city: str | None,
    state: str | None,
    previous: str | None,
) -> str:
    parts: list[str] = []
    if neighborhood:
        parts.append(neighborhood)
    if city:
        parts.append(city)
    if state and (not parts or _fold(state) not in _fold(parts[-1])):
        parts.append(state)
    if parts:
        return ", ".join(parts)
    return previous or ""


def reconcile_olx_location(
    *,
    title: str | None,
    description: str | None,
    scraped_city: str | None,
    scraped_neighborhood: str | None,
    scraped_state: str | None,
    scraped_address: str | None,
    allowed_cities: Sequence[str],
    allowed_states: Sequence[str],
    known_neighborhoods: Sequence[str],
    ai_extract: Callable[[str], Mapping[str, Any] | None] | None = None,
    force_ai: bool = False,
) -> OlxLocationResult:
    """Reconcile scraped OLX location against title/description (+ optional AI)."""
    suspected, hinted_city, hinted_nb, reason = suspect_location_mismatch(
        title=title,
        description=description,
        scraped_city=scraped_city,
        scraped_neighborhood=scraped_neighborhood,
        allowed_cities=allowed_cities,
        known_neighborhoods=known_neighborhoods,
    )

    city = scraped_city
    state = scraped_state
    neighborhood = scraped_neighborhood
    confidence = 0.0
    used_ai = False

    if (suspected or force_ai) and ai_extract is not None:
        from adapters.ai.prompts import build_olx_location_prompt

        prompt = build_olx_location_prompt(
            title=title or "",
            description=description or "",
            scraped_city=scraped_city,
            scraped_neighborhood=scraped_neighborhood,
            scraped_state=scraped_state,
            scraped_address=scraped_address,
            allowed_cities=allowed_cities,
            known_neighborhoods=known_neighborhoods,
        )
        try:
            data = ai_extract(prompt)
        except Exception as exc:  # backfill/ingest must continue
            return OlxLocationResult(
                action="ai_failed",
                city=scraped_city,
                state=scraped_state,
                neighborhood=scraped_neighborhood,
                address=scraped_address,
                mismatch_suspected=suspected,
                reason=f"ai_error:{exc}",
            )
        if not data:
            return OlxLocationResult(
                action="ai_failed",
                city=scraped_city,
                state=scraped_state,
                neighborhood=scraped_neighborhood,
                address=scraped_address,
                mismatch_suspected=suspected,
                reason="ai_empty",
            )
        used_ai = True
        city = (data.get("city") or city or "") or None
        state = (data.get("state") or state or "") or None
        neighborhood = (data.get("neighborhood") or neighborhood or "") or None
        try:
            confidence = float(data.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        reason = str(data.get("reason") or reason)
    elif suspected and (hinted_city or hinted_nb or reason == "neighborhood_is_city"):
        # Heuristic-only correction when AI is unavailable.
        if hinted_city:
            city = hinted_city
        if hinted_nb:
            neighborhood = hinted_nb
        elif reason == "neighborhood_is_city":
            # Drop city-as-neighborhood noise until a real bairro is known.
            neighborhood = None
        # Seller put a metro city in neighborhood; MG scrapes → prefer BH.
        if reason == "neighborhood_is_city" and hinted_nb:
            state_f = _fold(state or scraped_state or "")
            if state_f in ("mg", "minas gerais"):
                for c in allowed_cities:
                    if _canonical_city(c) == _canonical_city("Belo Horizonte"):
                        city = c
                        break
        confidence = 0.55
    elif not suspected:
        return OlxLocationResult(
            action="unchanged",
            city=scraped_city,
            state=scraped_state,
            neighborhood=scraped_neighborhood,
            address=scraped_address,
            mismatch_suspected=False,
            reason="ok",
        )

    # Prefer catalog spelling for neighborhoods.
    if neighborhood:
        catalog_nb = _best_catalog_match(neighborhood, known_neighborhoods)
        if catalog_nb:
            neighborhood = catalog_nb

    probe = type(
        "Probe",
        (),
        {
            "props_json": {"city": city, "state": state, "neighborhood": neighborhood},
            "address": scraped_address,
        },
    )()
    ok, geo_reason = passes_geo_allowlist(
        probe,
        cities=list(allowed_cities),
        states=list(allowed_states),
        enabled=True,
    )
    if not ok:
        return OlxLocationResult(
            action="out_of_geo",
            city=city,
            state=state,
            neighborhood=neighborhood,
            address=_rebuild_address(
                neighborhood=neighborhood, city=city, state=state, previous=scraped_address
            ),
            clear_coords=True,
            mismatch_suspected=True,
            reason=geo_reason or reason,
            confidence=confidence,
        )

    city_changed = _canonical_city(city or "") != _canonical_city(scraped_city or "")
    nb_changed = _fold(neighborhood or "") != _fold(scraped_neighborhood or "")
    if not city_changed and not nb_changed and not used_ai:
        return OlxLocationResult(
            action="unchanged",
            city=scraped_city,
            state=scraped_state,
            neighborhood=scraped_neighborhood,
            address=scraped_address,
            mismatch_suspected=suspected,
            reason=reason,
        )

    clear_coords = nb_changed or city_changed
    new_address = _rebuild_address(
        neighborhood=neighborhood, city=city, state=state, previous=scraped_address
    )
    return OlxLocationResult(
        action="corrected",
        city=city,
        state=state,
        neighborhood=neighborhood,
        address=new_address,
        clear_coords=clear_coords,
        mismatch_suspected=True,
        reason=reason,
        confidence=confidence,
    )


def apply_reconcile_to_candidate(candidate: Any, result: OlxLocationResult) -> Any:
    """Mutate a PropertyCandidate (or similar) from an OlxLocationResult."""
    if result.action in ("unchanged", "ai_failed"):
        return candidate

    props = dict(getattr(candidate, "props_json", None) or {})
    if result.city:
        props["city"] = result.city
    if result.state:
        props["state"] = result.state
    if result.neighborhood:
        props["neighborhood"] = result.neighborhood
    elif result.action == "corrected" and result.reason == "neighborhood_is_city":
        props.pop("neighborhood", None)
    props["olx_location_corrected"] = True
    if result.reason:
        props["olx_location_reason"] = result.reason
    candidate.props_json = props
    if result.address:
        candidate.address = result.address
    if result.clear_coords:
        candidate.location = None
    return candidate


async def _extract_with_retries(prompt: str) -> Mapping[str, Any] | None:
    import json

    from adapters.ai.client import create_ai_client

    client = create_ai_client()
    current = prompt
    try:
        async with client:
            for attempt in range(3):
                res = await client.generate(
                    getattr(client, "text_model", "llama3"),
                    current,
                    stream=False,
                    format="json",
                )
                raw = res.get("response")
                if raw is None and isinstance(res.get("choices"), list) and res["choices"]:
                    raw = res["choices"][0].get("message", {}).get("content")
                try:
                    data = json.loads(raw or "{}")
                    if isinstance(data, dict):
                        return data
                except json.JSONDecodeError:
                    if attempt == 2:
                        return None
                    current = (
                        prompt
                        + "\n\nYour last response was invalid JSON. Return ONLY valid JSON."
                    )
    finally:
        await client.close()
    return None


def sync_ai_extract(prompt: str) -> Mapping[str, Any] | None:
    """Run Ollama/LMStudio location extraction synchronously (Celery / scripts)."""
    import asyncio

    return asyncio.run(_extract_with_retries(prompt))
