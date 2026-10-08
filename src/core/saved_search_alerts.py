"""Saved-search new-match detection (v0.14-s1.9, FR-32).

A saved search with ``notify_new_matches`` on gets one email per local day
listing the Properties that are new, match it and are decidable.

* **New** is a stored fact: ``properties.first_seen`` at or after the moment
  the search's notifications were enabled. A Listing appearing or reactivating
  on an existing Property does not move ``first_seen``, so a platform outage
  and its recovery produce nothing.
* **Matches** is the list endpoint's own ``WHERE``
  (``core.property_list_filters.build_property_where``), fed with the same
  parameters the SPA derives from the stored search.
* **Decidable** means the verdict is stored and the percentile was evaluated
  (``DECIDABLE_SQL``). A Property that is not decidable yet is simply not
  selectable; the next run looks again. Nothing is queued and nothing is
  written for it, so nothing can be lost. A hold has no time limit ("held,
  never dropped"): a Property that becomes decidable late is alerted late.
  One held longer than ``hold_warning_hours`` is reported as overdue.

Everything here reads Property / Listing / ``metrics_scoring`` and writes only
``saved_search_new_matches`` (plus the window date on ``saved_searches``).
Timestamps are naive UTC, like ``properties.first_seen``. SQL is static text
with bound values (BIN-135); no adapter import (AD-1).
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.property_list_filters import PropertyMatchFilters, build_property_where
from core.property_projection import LIST_SELECT_COLUMNS, map_property_list_item

STATUS_PENDING = "pending"
STATUS_SENT = "sent"
STATUS_WITHDRAWN = "withdrawn"

# Same FROM / JOIN aliases as the list query (``api.properties``).
PROPERTIES_FROM_JOIN = (
    "FROM properties p "
    "LEFT JOIN metrics_scoring ms ON ms.property_id = p.id "
    "LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id "
)

# The verdict is stored and the percentile stage looked at the row. The stamp
# says "evaluated", not "has a value": a suppressed cohort is decidable. A
# degraded (template) verdict counts, because the panel shows it. ``meta`` is
# ``json``. Without a ``metrics_scoring`` row both operands are false, never
# NULL, so ``NOT (...)`` is safe.
DECIDABLE_SQL = (
    "ms.percentile_evaluated_at IS NOT NULL "
    "AND NULLIF(btrim(ms.meta->'deal_verdict'->>'verdict'), '') IS NOT NULL"
)

_RECORD_INSERT = (
    "INSERT INTO saved_search_new_matches "
    "(saved_search_id, property_id, owner, status, matched_at) "
    "SELECT CAST(:nm_search_id AS uuid), p.id, :nm_owner, 'pending', :nm_now "
)
_RECORD_ON_CONFLICT = "ON CONFLICT (saved_search_id, property_id) DO NOTHING"

_HOLD_REPORT_SQL = (
    "SELECT COUNT(*) AS held, "
    "MIN(p.first_seen) AS oldest, "
    "COUNT(*) FILTER (WHERE p.first_seen < :nm_overdue_before) AS overdue "
    "FROM properties p "
    "LEFT JOIN metrics_scoring ms ON ms.property_id = p.id "
    "WHERE p.active = true AND p.first_seen >= :nm_floor "
    "AND NOT (" + DECIDABLE_SQL + ")"
)

_COLLECT_PENDING_SQL = (
    "SELECT " + LIST_SELECT_COLUMNS + " "
    + PROPERTIES_FROM_JOIN
    + "JOIN saved_search_new_matches a ON a.property_id = p.id "
    "WHERE a.saved_search_id = CAST(:nm_search_id AS uuid) "
    "AND a.status = 'pending' AND p.active = true "
    # Oldest first. One matcher run gives all its rows the same ``matched_at``
    # (a backlog released at once), so the Property's age breaks the tie.
    "ORDER BY a.matched_at, p.first_seen, p.id"
)

# A pending row is withdrawn, never emailed, when its Property is gone, when
# the search no longer notifies, or when it was matched under an earlier
# enabling of the search (off and on again starts over).
_WITHDRAW_STALE_SQL = (
    "UPDATE saved_search_new_matches a SET status = 'withdrawn' "
    "WHERE a.saved_search_id = CAST(:nm_search_id AS uuid) AND a.status = 'pending' "
    "AND (NOT EXISTS (SELECT 1 FROM properties p WHERE p.id = a.property_id AND p.active = true) "
    "OR NOT EXISTS (SELECT 1 FROM saved_searches s WHERE s.id = a.saved_search_id "
    "AND s.notify_new_matches AND s.notify_enabled_at IS NOT NULL "
    "AND a.matched_at >= s.notify_enabled_at))"
)

_MARK_SENT_SQL = (
    "UPDATE saved_search_new_matches SET status = 'sent', sent_at = :nm_now "
    "WHERE saved_search_id = CAST(:nm_search_id AS uuid) AND status = 'pending' "
    "AND property_id = ANY(CAST(:nm_property_ids AS uuid[]))"
)
_STAMP_WINDOW_SQL = (
    "UPDATE saved_searches SET new_match_last_window_on = :nm_window_date "
    "WHERE id = CAST(:nm_search_id AS uuid)"
)
# Gives a claimed day back; a no-op when the date is no longer the claimed one.
_RELEASE_WINDOW_SQL = (
    "UPDATE saved_searches SET new_match_last_window_on = :nm_previous "
    "WHERE id = CAST(:nm_search_id AS uuid) "
    "AND new_match_last_window_on = :nm_window_date"
)


# ---------------------------------------------------------------------------
# Saved search -> list filters
# ---------------------------------------------------------------------------


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


# The keys ``api.saved_searches.SavedSearchFilters.to_wire`` writes (a unit
# test pins the two together, and the SPA's wire keys against this set).
SAVED_SEARCH_WIRE_KEYS = frozenset(
    {
        "sort_by",
        "sort_dir",
        "listing_type",
        "property_type",
        "platform",
        "min_price",
        "max_price",
        "price_type",
        "min_bedrooms",
        "max_bedrooms",
        "min_parking",
        "neighborhood",
        "city",
        "is_furnished",
        "accepts_pets",
        "min_score",
        "max_price_per_m2_percentile",
        "q",
    }
)


def saved_search_is_matchable(wire: Any) -> bool:
    """Whether a stored filter blob can be evaluated as a membership test.

    False for a semantic search (its result is a ranking), and for a blob that
    is not an object or carries a key this module does not know (a legacy
    camelCase blob, say): reading either as "no filter" would alert on every
    new Property, so such a search never fires instead.
    """
    if not isinstance(wire, Mapping):
        return False
    if any(key not in SAVED_SEARCH_WIRE_KEYS for key in wire):
        return False
    return _blank(wire.get("q"))


def _percentile_cap(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if 0 < value <= 1 else None


def match_filters_from_saved_search(wire: Any) -> Optional[PropertyMatchFilters]:
    """Translate a stored filter blob into the list endpoint's parameters.

    Mirrors what the SPA sends to ``GET /properties`` when the search is
    applied (``usePropertiesFiltersState.buildListQueryFilters`` and
    ``api.buildPropertyFilterParams``). ``None`` means the search cannot be
    matched (``saved_search_is_matchable``). ``sort_*``, ``min_price`` and
    ``max_bedrooms`` are ignored because the list endpoint ignores them too.
    """
    if not saved_search_is_matchable(wire):
        return None

    max_price = None if _blank(wire.get("max_price")) else wire.get("max_price")
    # The SPA always stores ``price_type``. A blob written through the API
    # without one gets the list endpoint's own default (the listing type, else
    # rent), exactly as ``GET /properties`` would for the same parameters.
    price_type = None
    if max_price is not None and not _blank(wire.get("price_type")):
        price_type = wire.get("price_type")

    listing_type = wire.get("listing_type")
    if listing_type not in ("rent", "sale"):
        listing_type = None

    def stored(key: str) -> Any:
        value = wire.get(key)
        return None if _blank(value) else value

    return PropertyMatchFilters(
        platform=stored("platform"),
        min_score=stored("min_score"),
        max_price=max_price,
        price_type=price_type,
        min_bedrooms=stored("min_bedrooms"),
        min_parking=stored("min_parking"),
        neighborhood_name=stored("neighborhood"),
        city_name=stored("city"),
        listing_type=listing_type,
        property_type=stored("property_type"),
        is_furnished=True if wire.get("is_furnished") is True else None,
        accepts_pets=True if wire.get("accepts_pets") is True else None,
        max_price_per_m2_percentile=_percentile_cap(wire.get("max_price_per_m2_percentile")),
    )


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------


def _naive_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def newness_floor(enabled_at: datetime) -> datetime:
    """Earliest ``first_seen`` that counts as new for a search: its enabling.

    There is no upper age: a match is held until it is decidable, however long
    that takes, and alerted then (Story 1.9: "held ..., never dropped").
    """
    return _naive_utc(enabled_at)


def local_window_date(now_utc: datetime, tz_name: str) -> date:
    """The calendar date of ``now_utc`` in the window's timezone."""
    return _local(now_utc, tz_name).date()


def _local(now_utc: datetime, tz_name: str) -> datetime:
    aware = now_utc if now_utc.tzinfo is not None else now_utc.replace(tzinfo=timezone.utc)
    return aware.astimezone(ZoneInfo(tz_name))


def window_is_due(
    now_utc: datetime,
    *,
    tz_name: str,
    window_hour: int,
    last_window_on: Optional[date],
) -> bool:
    """True once per local day, from ``window_hour`` on.

    A worker that was down at the window hour sends at its next run; a second
    run on a day already stamped does nothing.
    """
    local = _local(now_utc, tz_name)
    if local.hour < window_hour:
        return False
    return last_window_on is None or last_window_on < local.date()


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def build_record_new_matches_sql(filters: Any) -> Tuple[str, Dict[str, Any]]:
    """The matcher's one statement and the filter parameters it binds.

    The caller adds ``nm_search_id``, ``nm_owner``, ``nm_now`` and ``nm_floor``.
    """
    predicates, params = build_property_where(filters)
    sql = (
        _RECORD_INSERT
        + PROPERTIES_FROM_JOIN
        + "WHERE "
        + " AND ".join(predicates)
        + " AND p.first_seen >= :nm_floor"
        + " AND "
        + DECIDABLE_SQL
        + " "
        + _RECORD_ON_CONFLICT
    )
    return sql, params


def record_new_matches(
    session: Session,
    *,
    search_id: str,
    owner: str,
    filters: Any,
    enabled_at: datetime,
    now: datetime,
) -> int:
    """Insert one pending row per new, matching, decidable Property; return how many.

    Idempotent: the unique constraint on search x Property makes a second run,
    or a second worker, insert nothing.
    """
    sql, params = build_record_new_matches_sql(filters)
    params.update(
        {
            "nm_search_id": str(search_id),
            "nm_owner": owner,
            "nm_now": _naive_utc(now),
            "nm_floor": newness_floor(enabled_at),
        }
    )
    result = session.execute(text(sql), params)
    return max(int(result.rowcount or 0), 0)


def hold_report(
    session: Session, *, floor: datetime, now: datetime, overdue_after_hours: int
) -> Dict[str, Any]:
    """Count the new active Properties that are not decidable yet.

    ``held_overdue`` are those first seen more than ``overdue_after_hours``
    ago. They stay held and are alerted when they become decidable; the count
    is the signal that enrichment is not reaching new Properties.
    """
    clock = _naive_utc(now)
    row = session.execute(
        text(_HOLD_REPORT_SQL),
        {
            "nm_floor": _naive_utc(floor),
            "nm_overdue_before": clock - timedelta(hours=overdue_after_hours),
        },
    ).mappings().fetchone()
    held = int(row["held"] or 0) if row else 0
    oldest = row["oldest"] if row else None
    oldest_hours = None
    if held and oldest is not None:
        oldest_hours = round((clock - _naive_utc(oldest)).total_seconds() / 3600, 1)
    return {
        "held": held,
        "oldest_held_hours": oldest_hours,
        "held_overdue": int(row["overdue"] or 0) if row else 0,
    }


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------


def withdraw_stale(session: Session, *, search_id: str) -> int:
    """Withdraw the search's pending rows that must no longer be emailed."""
    result = session.execute(text(_WITHDRAW_STALE_SQL), {"nm_search_id": str(search_id)})
    return max(int(result.rowcount or 0), 0)


def collect_pending(session: Session, search_id: str) -> List[Dict[str, Any]]:
    """Pending matches of a search whose Property is active, AD-12 projected.

    ``property_type`` (the stored ``props_json.type``) is added for the email
    title fallback; the projection itself is unchanged.
    """
    rows = session.execute(
        text(_COLLECT_PENDING_SQL), {"nm_search_id": str(search_id)}
    ).mappings().fetchall()
    items = []
    for row in rows:
        item = map_property_list_item(row)
        item["property_type"] = (row.get("props_json") or {}).get("type")
        items.append(item)
    return items


def claim_window(session: Session, search_id: str, window_date: date) -> None:
    """Stamp the search's window date before its email is sent.

    The sender commits this under the search's row lock and only then talks to
    the mail server, so no lock is held during the send and a second run finds
    the day taken. ``release_window`` undoes it when the send fails.
    """
    session.execute(
        text(_STAMP_WINDOW_SQL),
        {"nm_search_id": str(search_id), "nm_window_date": window_date},
    )


def release_window(
    session: Session, search_id: str, window_date: date, previous: Optional[date]
) -> None:
    """Give a claimed day back after a failed send, so the next run tries again."""
    session.execute(
        text(_RELEASE_WINDOW_SQL),
        {
            "nm_search_id": str(search_id),
            "nm_window_date": window_date,
            "nm_previous": previous,
        },
    )


def mark_sent(
    session: Session,
    search_id: str,
    property_ids: Sequence[str],
    now: datetime,
    window_date: date,
) -> int:
    """Mark the emailed rows ``sent`` and stamp the search's window date.

    Rows that are not in ``property_ids`` stay ``pending`` for a later window.
    """
    result = session.execute(
        text(_MARK_SENT_SQL),
        {
            "nm_search_id": str(search_id),
            "nm_property_ids": [str(pid) for pid in property_ids],
            "nm_now": _naive_utc(now),
        },
    )
    session.execute(
        text(_STAMP_WINDOW_SQL),
        {"nm_search_id": str(search_id), "nm_window_date": window_date},
    )
    return max(int(result.rowcount or 0), 0)


# ---------------------------------------------------------------------------
# Email text
# ---------------------------------------------------------------------------

_COPY = {
    "pt-BR": {
        "subject_one": "1 imóvel novo na busca “{name}”",
        "subject_many": "{count} imóveis novos na busca “{name}”",
        "search": "Busca salva: {name}",
        "intro_one": "1 imóvel novo corresponde a esta busca.",
        "intro_many": "{count} imóveis novos correspondem a esta busca.",
        "per_month": "/mês",
        "bedroom_one": "1 quarto",
        "bedroom_many": "{count} quartos",
        "percentile": "entre os {n}% mais baratos do bairro",
        "more": "+{count} nesta busca chegam no próximo aviso.",
        "held_one": (
            "1 imóvel novo ainda está em análise; se corresponder a esta busca, "
            "chega num próximo aviso."
        ),
        "held_many": (
            "{count} imóveis novos ainda estão em análise; os que corresponderem "
            "a esta busca chegam num próximo aviso."
        ),
        "why": (
            "Você recebe este e-mail porque os avisos de novos imóveis estão ligados "
            "para esta busca. Para desligar, abra Buscas salvas."
        ),
        "untitled": "Imóvel",
        "thousands": ".",
        "decimal": ",",
    },
    "en": {
        "subject_one": "1 new home for “{name}”",
        "subject_many": "{count} new homes for “{name}”",
        "search": "Saved search: {name}",
        "intro_one": "1 new home matches this search.",
        "intro_many": "{count} new homes match this search.",
        "per_month": "/month",
        "bedroom_one": "1 bedroom",
        "bedroom_many": "{count} bedrooms",
        "percentile": "among the {n}% cheapest in the neighbourhood",
        "more": "+{count} more in this search arrive in the next email.",
        "held_one": (
            "1 new home is still being analysed; if it matches this search it "
            "arrives in a later email."
        ),
        "held_many": (
            "{count} new homes are still being analysed; the ones that match this "
            "search arrive in a later email."
        ),
        "why": (
            "You receive this email because new-match alerts are on for this "
            "search. To switch them off, open Buscas salvas."
        ),
        "untitled": "Home",
        "thousands": ",",
        "decimal": ".",
    },
}
DEFAULT_EMAIL_LOCALE = "pt-BR"


def cheapest_percent(value: Any) -> Optional[int]:
    """N of ``entre os N% mais baratos``: the smallest whole percent that is true.

    Same rule as the card badge (``frontend/src/utils/percentile.ts``): round
    up, at least 1, guarded against floating-point noise (0.07 reads 7).
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not 0 < value <= 1:
        return None
    return max(1, math.ceil(round(value * 100, 9)))


def _plural(copy: Mapping[str, str], key: str, count: int, **extra: Any) -> str:
    template = copy[key + "_one"] if count == 1 else copy[key + "_many"]
    return template.format(count=count, **extra)


def _number(value: float, copy: Mapping[str, str], decimals: int = 0) -> str:
    formatted = format(value, ",." + str(decimals) + "f")
    whole, _, fraction = formatted.partition(".")
    whole = whole.replace(",", copy["thousands"])
    return whole + (copy["decimal"] + fraction if fraction else "")


def _relevant_listing_type(prop: Mapping[str, Any], searched: Optional[str]) -> Optional[str]:
    if searched in ("rent", "sale"):
        return searched
    primary = prop.get("primary_listing") or {}
    if primary.get("listing_type") in ("rent", "sale"):
        return primary["listing_type"]
    if prop.get("available_for_rent"):
        return "rent"
    if prop.get("available_for_sale"):
        return "sale"
    return None


def _headline_price(prop: Mapping[str, Any], listing_type: Optional[str]) -> Optional[float]:
    prices = [
        float(listing["price"])
        for listing in (prop.get("listings") or [])
        if listing.get("listing_type") == listing_type and listing.get("price") is not None
    ]
    if prices:
        return min(prices)
    price = prop.get("price")
    return float(price) if price is not None else None


def _property_block(
    index: int,
    prop: Mapping[str, Any],
    *,
    searched_type: Optional[str],
    copy: Mapping[str, str],
    app_base_url: str,
) -> List[str]:
    listing_type = _relevant_listing_type(prop, searched_type)
    title = (prop.get("title") or "").strip()
    if not title:
        title = str(prop.get("property_type") or "").strip().capitalize() or copy["untitled"]
    lines = [str(index) + ". " + title]

    place = ", ".join(
        part for part in (prop.get("neighborhood_name"), prop.get("city")) if part
    )
    if place:
        lines.append("   " + place)

    facts = []
    price = _headline_price(prop, listing_type)
    if price is not None:
        suffix = copy["per_month"] if listing_type == "rent" else ""
        facts.append("R$ " + _number(price, copy) + suffix)
    area = prop.get("area_m2")
    if area:
        decimals = 0 if float(area).is_integer() else 1
        facts.append(_number(float(area), copy, decimals) + " m²")
    bedrooms = prop.get("bedrooms")
    if bedrooms:
        facts.append(_plural(copy, "bedroom", int(bedrooms)))
    if facts:
        lines.append("   " + " · ".join(facts))

    verdict = (prop.get("deal_summary") or "").strip()
    if verdict:
        lines.append("   " + verdict)

    percent = None
    if listing_type is not None:
        percent = cheapest_percent(prop.get("price_per_m2_percentile_" + listing_type))
    if percent is not None:
        lines.append("   " + copy["percentile"].format(n=percent))

    public_id = prop.get("public_id")
    if app_base_url and public_id is not None:
        # The SPA route of the detail panel (frontend/src/routes/propertyPaths.ts).
        lines.append("   " + app_base_url.rstrip("/") + "/properties/" + str(public_id))
    return lines


def render_new_match_email(
    *,
    search_name: str,
    properties: Sequence[Mapping[str, Any]],
    listing_type: Optional[str] = None,
    held: int = 0,
    remaining: int = 0,
    app_base_url: str = "",
    locale: str = DEFAULT_EMAIL_LOCALE,
) -> Tuple[str, str]:
    """Plain-text subject and body of one search's new-match email.

    ``properties`` are the AD-12 list items this email carries
    (``collect_pending``, already cut to the per-email limit by the caller);
    ``remaining`` is how many more matches stay pending for the next email. A
    fact that is not stored is left out: no percentile line for a NULL
    percentile, no link without ``app_base_url``. Nothing is said about a drop
    threshold; that is the drop email of Story 1.10.
    """
    copy = _COPY.get(locale) or _COPY[DEFAULT_EMAIL_LOCALE]
    total = len(properties)
    # A header cannot carry a line break; the stored name is only length-checked.
    subject = _plural(copy, "subject", total, name=" ".join(str(search_name).split()))

    lines = [copy["search"].format(name=search_name), _plural(copy, "intro", total), ""]
    for index, prop in enumerate(properties, start=1):
        lines.extend(
            _property_block(
                index, prop, searched_type=listing_type, copy=copy, app_base_url=app_base_url
            )
        )
        lines.append("")
    if remaining > 0:
        lines.append(copy["more"].format(count=remaining))
        lines.append("")
    if held > 0:
        lines.append(_plural(copy, "held", held))
        lines.append("")
    lines.append(copy["why"])
    return subject, "\n".join(lines)
