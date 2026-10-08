"""The per-search price-drop alert (v0.14-s1.10, FR-32, UX-DR13).

A saved search with alerts on and a stored minimum drop gets one email per
local day listing the Listings of matching, decidable Properties whose own
headline price fell by at least that minimum since drop alerts became active
for the search (``saved_searches.price_drop_enabled_at``, the floor).

* **A drop** is one Listing against that Listing's own earlier price. A
  cheaper Listing appearing on another platform is not a drop.
* **The earlier price** (reference) is, in this order: the price of this
  search's last drop email for the Listing, the price in force at the floor,
  the Listing's first recorded price after the floor.
* **Detected at send time.** A drop is a comparison of two stored prices, so
  nothing is recorded when it happens: a Property that does not match or is
  not decidable yet is simply looked at again the next day, and a drop that
  was undone before the window is never emailed.
* **The rule has one implementation**, ``drop_amount``. The candidate
  statement only bounds what is examined; the threshold is never in SQL.

* **Independent of the watchlist alert.** A watched Property that a search
  also covers can be announced by both, each for its own reason. The
  watchlist's ``last_notified_price`` is not read: it says a price was once
  handed to that path, not that this drop reached anyone, and trusting it
  could leave a drop the search asked for unannounced by either.

Reads Property / Listing / ``price_history``; writes only
``saved_search_price_drop_alerts`` (one row per alerted Listing of a
Property an email carried) and the drop window date on ``saved_searches``.
Timestamps are naive UTC. SQL is static text with bound values (BIN-135);
no adapter import (AD-1).
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.property_list_filters import build_property_where
from core.property_projection import LIST_SELECT_COLUMNS, map_property_list_item
from core.saved_search_alerts import _COPY as _NEW_MATCH_COPY  # separators, "/mês", the search line, the title fallback
from core.saved_search_alerts import DECIDABLE_SQL, DEFAULT_EMAIL_LOCALE, PROPERTIES_FROM_JOIN, _naive_utc, _number

# The smallest difference that is a drop at all: one centavo.
MIN_DROP = 0.01


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------


def _finite(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def drop_amount(reference: Any, current: Any, threshold: Any) -> Optional[float]:
    """How much a price fell, in reais, when that is an alertable drop.

    ``None`` unless the three values are finite numbers, both prices are
    positive, the threshold is not negative, and the fall (rounded to
    centavos) is at least one centavo and at least the threshold. A threshold
    of ``0`` therefore means any drop, but more than nothing.
    """
    if not (_finite(reference) and _finite(current) and _finite(threshold)):
        return None
    if reference <= 0 or current <= 0 or threshold < 0:
        return None
    fall = round(float(reference) - float(current), 2)
    if fall < MIN_DROP or fall < threshold:
        return None
    return fall


def select_drops(candidates: Sequence[Mapping[str, Any]], threshold: Any) -> List[Dict[str, Any]]:
    """The alertable drops among candidate rows, one per Property.

    ``candidates`` are the rows of the candidate statement. A Property with
    several Listings that fell keeps the largest drop (ties: the lower current
    price, then the Listing id). Each kept row gains ``drop``; ids come back
    as strings. Ordered by drop, largest first, then by Property id.
    """
    best: Dict[str, Dict[str, Any]] = {}
    for row in candidates:
        fall = drop_amount(row.get("reference_price"), row.get("current_price"), threshold)
        if fall is None:
            continue
        item = dict(row)
        item["property_id"] = str(row["property_id"])
        item["listing_id"] = str(row["listing_id"])
        item["drop"] = fall
        kept = best.get(item["property_id"])
        if kept is None or _preference(item) < _preference(kept):
            best[item["property_id"]] = item
    return sorted(best.values(), key=lambda item: (-item["drop"], item["property_id"]))


def _preference(item: Mapping[str, Any]) -> Tuple[float, float, str]:
    return (-item["drop"], float(item["current_price"]), item["listing_id"])


def drops_to_record(
    candidates: Sequence[Mapping[str, Any]],
    threshold: Any,
    shown: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Every alertable Listing of the Properties an email carried.

    The email shows one Listing per Property, the largest drop. A second
    Listing of that Property that also fell is recorded with it: otherwise it
    would still qualify the next day and the Property would be emailed again
    for a drop that is older than the email it already got. The shown rows
    come first, in their order; ids are strings and each row carries ``drop``.
    """
    wanted = {str(item["property_id"]) for item in shown}
    seen = {str(item["listing_id"]) for item in shown}
    rows: List[Dict[str, Any]] = [dict(item) for item in shown]
    for row in candidates:
        property_id = str(row["property_id"])
        listing_id = str(row["listing_id"])
        if property_id not in wanted or listing_id in seen:
            continue
        fall = drop_amount(row.get("reference_price"), row.get("current_price"), threshold)
        if fall is None:
            continue
        item = dict(row)
        item["property_id"] = property_id
        item["listing_id"] = listing_id
        item["drop"] = fall
        seen.add(listing_id)
        rows.append(item)
    return rows


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------

# Reference price of one Listing for one search, first that exists.
_LAST_ALERT_PRICE = (
    "(SELECT a.new_price FROM saved_search_price_drop_alerts a "
    "WHERE a.saved_search_id = CAST(:pd_search_id AS uuid) "
    "AND a.property_listing_id = dl.id AND a.sent_at >= :pd_floor "
    "ORDER BY a.sent_at DESC, a.id DESC LIMIT 1)"
)
_PRICE_AT_FLOOR = (
    "(SELECT ph.price FROM price_history ph "
    "WHERE ph.property_id = dl.property_id AND ph.property_listing_id = dl.id "
    "AND ph.start_ts <= :pd_floor AND (ph.end_ts IS NULL OR ph.end_ts > :pd_floor) "
    "ORDER BY ph.start_ts DESC LIMIT 1)"
)
_FIRST_PRICE_AFTER_FLOOR = (
    "(SELECT ph.price FROM price_history ph "
    "WHERE ph.property_id = dl.property_id AND ph.property_listing_id = dl.id "
    "AND ph.start_ts > :pd_floor "
    "ORDER BY ph.start_ts ASC LIMIT 1)"
)

_CANDIDATES_SELECT = (
    "SELECT p.id AS property_id, dl.id AS listing_id, dl.listing_type AS listing_type, "
    "dl.platform AS platform, dl.price AS current_price, "
    "COALESCE("
    + _LAST_ALERT_PRICE
    + ", "
    + _PRICE_AT_FLOOR
    + ", "
    + _FIRST_PRICE_AFTER_FLOOR
    + ") AS reference_price "
    + PROPERTIES_FROM_JOIN
    + "JOIN property_listings dl ON dl.property_id = p.id "
)

# Only Listings whose price changed after the floor are examined, so a search
# without filters does not probe the history of every Property.
_CHANGED_AFTER_FLOOR = (
    "dl.id IN (SELECT ph.property_listing_id FROM price_history ph "
    "WHERE ph.end_ts > :pd_floor AND ph.property_listing_id IS NOT NULL)"
)

_LISTING_TYPE_PREDICATE = "dl.listing_type = :pd_listing_type"
# The search's own Listing-level filters also hold for the Listing whose drop
# is announced, not only for some Listing of the Property. They reuse the
# values the shared WHERE binds (``max_price`` / ``price_type``, ``platform``).
_LISTING_WITHIN_PRICE_CAP = "dl.listing_type = :price_type AND dl.price <= :max_price"
_LISTING_ON_PLATFORM = "dl.platform = :platform"


def build_drop_candidates_sql(
    filters: Any, *, listing_type: Optional[str]
) -> Tuple[str, Dict[str, Any]]:
    """The candidate statement and the filter parameters it binds.

    One row per active, priced Listing of a Property that passes the grid's
    own ``WHERE`` for ``filters`` and is decidable, whose price changed after
    the floor. A search for one listing type (``rent`` / ``sale``) only looks
    at Listings of that type. The caller adds ``pd_search_id`` and
    ``pd_floor``.
    """
    predicates, params = build_property_where(filters)
    clauses = [
        *predicates,
        DECIDABLE_SQL,
        "dl.active = true",
        "dl.price > 0",
        _CHANGED_AFTER_FLOOR,
    ]
    if listing_type in ("rent", "sale"):
        clauses.append(_LISTING_TYPE_PREDICATE)
        params["pd_listing_type"] = listing_type
    if "max_price" in params and not (
        listing_type in ("rent", "sale") and listing_type != params["price_type"]
    ):
        # A search "rent up to R$ 3.000" never announces a Listing above the
        # cap, or of the other type, on a Property another Listing qualifies.
        # A search for one type capped on the other (sale Listings of homes
        # that also rent for at most R$ 3.000) announces Listings of its own
        # type: the cap is about the other Listing and stays in the shared
        # WHERE. Both predicates together would match no Listing at all.
        clauses.append(_LISTING_WITHIN_PRICE_CAP)
    if "platform" in params:
        clauses.append(_LISTING_ON_PLATFORM)
    sql = _CANDIDATES_SELECT + "WHERE " + " AND ".join(clauses)
    return sql, params


def collect_drop_candidates(
    session: Session,
    *,
    search_id: str,
    filters: Any,
    listing_type: Optional[str],
    floor: datetime,
) -> List[Dict[str, Any]]:
    """Run the candidate statement for one search; rows for ``select_drops``."""
    sql, params = build_drop_candidates_sql(filters, listing_type=listing_type)
    params.update(
        {
            "pd_search_id": str(search_id),
            "pd_floor": _naive_utc(floor),
        }
    )
    rows = session.execute(text(sql), params).mappings().fetchall()
    return [dict(row) for row in rows]


_LOAD_PROPERTIES_SQL = (
    "SELECT " + LIST_SELECT_COLUMNS + " "
    + PROPERTIES_FROM_JOIN
    + "WHERE p.id = ANY(CAST(:pd_property_ids AS uuid[]))"
)


def load_drop_properties(
    session: Session, property_ids: Sequence[str]
) -> Dict[str, Dict[str, Any]]:
    """AD-12 list items of the Properties an email is about, by id.

    ``property_type`` (the stored ``props_json.type``) is added for the email
    title fallback, as ``collect_pending`` does; the projection is unchanged.
    """
    ids = [str(pid) for pid in property_ids]
    if not ids:
        return {}
    rows = session.execute(
        text(_LOAD_PROPERTIES_SQL), {"pd_property_ids": ids}
    ).mappings().fetchall()
    items: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        item = map_property_list_item(row)
        item["property_type"] = (row.get("props_json") or {}).get("type")
        items[str(item["id"])] = item
    return items


# ---------------------------------------------------------------------------
# Window and alert rows
# ---------------------------------------------------------------------------

_STAMP_DROP_WINDOW_SQL = (
    "UPDATE saved_searches SET price_drop_last_window_on = :pd_window_date "
    "WHERE id = CAST(:pd_search_id AS uuid)"
)
# Gives a claimed day back; a no-op when the date is no longer the claimed one.
_RELEASE_DROP_WINDOW_SQL = (
    "UPDATE saved_searches SET price_drop_last_window_on = :pd_previous "
    "WHERE id = CAST(:pd_search_id AS uuid) "
    "AND price_drop_last_window_on = :pd_window_date"
)
# Through the search and the Listing: either one deleted while the email was
# being sent inserts nothing instead of failing on a foreign key.
_RECORD_ALERT_SQL = (
    "INSERT INTO saved_search_price_drop_alerts "
    "(saved_search_id, property_id, property_listing_id, owner, listing_type, platform, "
    "reference_price, new_price, threshold, sent_at) "
    "SELECT s.id, dl.property_id, dl.id, :pd_owner, :pd_listing_type, :pd_platform, "
    ":pd_reference_price, :pd_new_price, :pd_threshold, :pd_now "
    "FROM saved_searches s "
    "JOIN property_listings dl ON dl.id = CAST(:pd_listing_id AS uuid) "
    "WHERE s.id = CAST(:pd_search_id AS uuid)"
)


def claim_drop_window(session: Session, search_id: str, window_date: date) -> None:
    """Stamp the search's drop window date before its email is sent.

    Committed under the search's row lock, before the mail server is
    contacted; ``release_drop_window`` undoes it when the send fails.
    """
    session.execute(
        text(_STAMP_DROP_WINDOW_SQL),
        {"pd_search_id": str(search_id), "pd_window_date": window_date},
    )


def release_drop_window(
    session: Session, search_id: str, window_date: date, previous: Optional[date]
) -> None:
    """Give a claimed day back after a failed send, so the next run tries again."""
    session.execute(
        text(_RELEASE_DROP_WINDOW_SQL),
        {
            "pd_search_id": str(search_id),
            "pd_window_date": window_date,
            "pd_previous": previous,
        },
    )


def record_drop_alerts(
    session: Session,
    *,
    search_id: str,
    owner: str,
    drops: Sequence[Mapping[str, Any]],
    threshold: float,
    now: datetime,
) -> int:
    """Store one row per alerted Listing; return how many were stored.

    ``drops`` are the rows of ``drops_to_record``: the Listing each emailed
    block showed, plus the other Listings of those Properties that fell by
    the threshold as well. The row keeps the price the comparison started
    from, the Listing's price when the email left and the threshold the
    email stated. That price is the reference of the next comparison, so the
    next alert for the Listing needs a further drop of at least the
    threshold.
    """
    recorded = 0
    for item in drops:
        result = session.execute(
            text(_RECORD_ALERT_SQL),
            {
                "pd_search_id": str(search_id),
                "pd_listing_id": str(item["listing_id"]),
                "pd_owner": owner,
                "pd_listing_type": item["listing_type"],
                "pd_platform": item.get("platform"),
                "pd_reference_price": float(item["reference_price"]),
                "pd_new_price": float(item["current_price"]),
                "pd_threshold": float(threshold),
                "pd_now": _naive_utc(now),
            },
        )
        recorded += max(int(result.rowcount or 0), 0)
    return recorded


# ---------------------------------------------------------------------------
# Email text
# ---------------------------------------------------------------------------

_COPY = {
    "pt-BR": {
        "subject_one": "1 queda de preço na busca “{name}”",
        "subject_many": "{count} quedas de preço na busca “{name}”",
        "intro_one": "1 imóvel desta busca baixou de preço.",
        "intro_many": "{count} imóveis desta busca baixaram de preço.",
        "drop": "queda de R$ {drop} — seu mínimo: R$ {threshold}",
        "more": "+{count} nesta busca chegam no próximo aviso.",
        "why": (
            "Você recebe este e-mail porque os avisos estão ligados para esta busca, "
            "com queda mínima de R$ {threshold}. Para mudar, abra Buscas salvas."
        ),
    },
    "en": {
        "subject_one": "1 price drop in “{name}”",
        "subject_many": "{count} price drops in “{name}”",
        "intro_one": "1 home in this search dropped in price.",
        "intro_many": "{count} homes in this search dropped in price.",
        "drop": "drop of R$ {drop} — your minimum: R$ {threshold}",
        "more": "+{count} more in this search arrive in the next email.",
        "why": (
            "You receive this email because alerts are on for this search, "
            "with a minimum drop of R$ {threshold}. To change it, open Buscas salvas."
        ),
    },
}

# Display names of the stored platform slugs, one per scraper; a slug that is
# not listed is shown as stored. (``frontend/src/labels.ts`` names the first
# two the same way and has no entry for the third.)
_PLATFORM_NAMES = {
    "olx": "OLX",
    "quintoandar": "QuintoAndar",
    "zapimoveis": "ZapImóveis",
}


def _money(value: Any, shared: Mapping[str, str]) -> str:
    """Whole reais without decimals, anything else with two."""
    amount = round(float(value), 2)
    return _number(amount, shared, 0 if amount == int(amount) else 2)


def _drop_block(
    index: int,
    item: Mapping[str, Any],
    prop: Mapping[str, Any],
    *,
    threshold: Any,
    copy: Mapping[str, str],
    shared: Mapping[str, str],
    app_base_url: str,
) -> List[str]:
    title = (prop.get("title") or "").strip()
    if not title:
        title = str(prop.get("property_type") or "").strip().capitalize() or shared["untitled"]
    lines = [str(index) + ". " + title]

    place = ", ".join(part for part in (prop.get("neighborhood_name"), prop.get("city")) if part)
    if place:
        lines.append("   " + place)

    suffix = shared["per_month"] if item.get("listing_type") == "rent" else ""
    prices = (
        "R$ "
        + _money(item["reference_price"], shared)
        + suffix
        + " → R$ "
        + _money(item["current_price"], shared)
        + suffix
    )
    platform = item.get("platform")
    if platform:
        prices += " · " + _PLATFORM_NAMES.get(str(platform), str(platform))
    lines.append("   " + prices)

    lines.append(
        "   "
        + copy["drop"].format(
            drop=_money(item["drop"], shared), threshold=_money(threshold, shared)
        )
    )

    public_id = prop.get("public_id")
    if app_base_url and public_id is not None:
        # The SPA route of the detail panel (frontend/src/routes/propertyPaths.ts).
        lines.append("   " + app_base_url.rstrip("/") + "/properties/" + str(public_id))
    return lines


def render_price_drop_email(
    *,
    search_name: str,
    drops: Sequence[Mapping[str, Any]],
    properties: Mapping[str, Mapping[str, Any]],
    threshold: Any,
    remaining: int = 0,
    app_base_url: str = "",
    locale: str = DEFAULT_EMAIL_LOCALE,
) -> Tuple[str, str]:
    """Plain-text subject and body of one search's price-drop email.

    ``drops`` are the rows of ``select_drops`` this email carries (already cut
    to the per-email limit by the caller); ``properties`` are their list items
    by id (``load_drop_properties``). A drop whose Property is not in
    ``properties`` is left out. Every block states the drop and ``threshold``,
    the minimum stored for the search when the email is sent (UX-DR13).
    ``remaining`` is how many more drops wait for the next email.
    """
    copy = _COPY.get(locale) or _COPY[DEFAULT_EMAIL_LOCALE]
    shared = _NEW_MATCH_COPY.get(locale) or _NEW_MATCH_COPY[DEFAULT_EMAIL_LOCALE]
    shown = [item for item in drops if str(item["property_id"]) in properties]
    total = len(shown)
    plural = "one" if total == 1 else "many"
    # A header cannot carry a line break; the stored name is only length-checked.
    subject = copy["subject_" + plural].format(count=total, name=" ".join(str(search_name).split()))

    lines = [
        shared["search"].format(name=search_name),
        copy["intro_" + plural].format(count=total),
        "",
    ]
    for index, item in enumerate(shown, start=1):
        lines.extend(
            _drop_block(
                index,
                item,
                properties[str(item["property_id"])],
                threshold=threshold,
                copy=copy,
                shared=shared,
                app_base_url=app_base_url,
            )
        )
        lines.append("")
    if remaining > 0:
        lines.append(copy["more"].format(count=remaining))
        lines.append("")
    lines.append(copy["why"].format(threshold=_money(threshold, shared)))
    return subject, "\n".join(lines)
