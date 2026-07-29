"""Shared parsing/lookup helpers for platform scraper adapters.

Extracted from ``adapters.scrapers.olx`` and ``adapters.scrapers.quintoandar``
to stop config-shape drift across per-platform scrapers (BIN-133): the two
implementations of ``_parse_price_pair`` were byte-for-byte identical, and
``_parse_cities`` / ``_parse_neighborhoods`` / the per-key neighborhood
lookup followed the same structure with only superficial differences —
already drifted once (OLX returned ``list[dict]``, QuintoAndar ``list[str]``
for the same "which neighborhoods to fan out into" concept).

Every helper here is behavior-preserving relative to the implementations it
replaces; the one deliberate change is ``parse_neighborhoods`` always
returning ``list[dict]`` (see its docstring) so both scrapers share one
shape going forward.
"""

from __future__ import annotations

from typing import Any


def parse_price_pair(value: Any, default: tuple[int, int]) -> tuple[int, int]:
    """Parse a ``[min, max]`` price-band override from YAML config.

    Falls back to ``default`` when ``value`` isn't a 2-element numeric
    list/tuple.
    """
    if (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(isinstance(v, (int, float)) for v in value)
    ):
        return int(value[0]), int(value[1])
    return default


def parse_neighborhoods(raw: list, *, require_zone: bool = False) -> list[dict[str, str]]:
    """Normalize neighborhood config entries to a single ``list[dict]`` shape.

    Accepts either ``{"slug": ..., "zone": ...}`` mappings (OLX geo fan-out,
    which indexes windows by zone) or bare slug strings (QuintoAndar, which
    has no zone concept). Always returns dicts with a ``slug`` key; ``zone``
    is included only when the source item provided one.

    ``require_zone=True`` (OLX) drops entries missing ``zone`` — OLX cannot
    build a geo window without one, so a bare slug string is never valid
    input in that mode and is skipped like any other malformed entry.
    """
    out: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, dict):
            slug = item.get("slug")
            zone = item.get("zone")
            if not slug or (require_zone and not zone):
                continue
            entry = {"slug": str(slug)}
            if zone:
                entry["zone"] = str(zone)
            out.append(entry)
        elif not require_zone and isinstance(item, str) and item:
            out.append({"slug": item})
    return out


def neighborhoods_for(
    mapping: dict[str, list],
    key: str,
    fallback: list,
    *,
    strict_key: str | None = None,
) -> list:
    """Shared per-key neighborhood fan-out lookup.

    Returns ``mapping[key]`` when present. Otherwise returns ``fallback`` —
    unless ``strict_key`` is given and doesn't match ``key`` (QuintoAndar's
    stricter guard for an unrecognized/renamed city_slug), in which case an
    empty list is returned instead of the fallback.
    """
    if key in mapping:
        return mapping[key]
    if strict_key is not None and key != strict_key:
        return []
    return fallback


def parse_cities(
    extra: dict,
    field_defaults: dict[str, str],
    *,
    require_zone: bool = False,
) -> list[dict[str, Any]]:
    """Parse ``extra['cities']`` (or single-city fallback fields) into a
    uniform list of per-city dicts.

    Each returned dict carries every key in ``field_defaults`` plus
    ``neighborhoods``. ``field_defaults`` maps each required per-city field
    (e.g. QuintoAndar's ``city_slug``; OLX additionally needs ``region``) to
    its single-city fallback default. A ``cities[i]`` entry missing any of
    these fields is dropped, mirroring each platform's original
    ``_parse_cities`` behavior.
    """
    raw_cities = extra.get("cities")
    if isinstance(raw_cities, list) and raw_cities:
        out: list[dict[str, Any]] = []
        for item in raw_cities:
            if not isinstance(item, dict):
                continue
            fields: dict[str, Any] | None = {}
            for field in field_defaults:
                value = item.get(field)
                if not value:
                    fields = None
                    break
                fields[field] = str(value)
            if fields is None:
                continue
            fields["neighborhoods"] = parse_neighborhoods(
                item.get("neighborhoods") or [], require_zone=require_zone
            )
            out.append(fields)
        if out:
            return out
    fields = {
        field: str(extra.get(field) or default) for field, default in field_defaults.items()
    }
    fields["neighborhoods"] = parse_neighborhoods(
        extra.get("neighborhoods") or [], require_zone=require_zone
    )
    return [fields]
