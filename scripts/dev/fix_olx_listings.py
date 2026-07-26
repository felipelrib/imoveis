#!/usr/bin/env python3
"""Fix OLX listing_type mislabels and seller-vs-property locations (BIN-72).

Default is dry-run. With ``--apply``:

1. Reclassify OLX ``property_listings.listing_type`` (and property flags) using
   title cues / price band / ``raw_json`` when present.
2. Reconcile address/city/neighborhood via heuristic + optional local AI.
3. Purge rows whose corrected city is outside the geo allowlist.
4. Merge fuzzy duplicates onto a keeper and delete the orphan.

Usage:
  PYTHONPATH=src python scripts/dev/fix_olx_listings.py
  PYTHONPATH=src python scripts/dev/fix_olx_listings.py --apply
  PYTHONPATH=src python scripts/dev/fix_olx_listings.py --apply --skip-ai
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Optional
from uuid import UUID

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from adapters.db.models import Property, PropertyListing  # noqa: E402
from adapters.scrapers.olx import OLXScraper  # noqa: E402
from core.dedupe import text_similarity  # noqa: E402
from core.geo_allowlist import _fold, passes_geo_allowlist  # noqa: E402
from core.neighbourhood_assignment import (  # noqa: E402
    assign_property_neighbourhood_by_name,
    load_neighborhood_names,
)
from core.olx_listing_type import infer_olx_listing_type  # noqa: E402
from core.olx_location import (  # noqa: E402
    humanize_neighborhood_slugs,
    reconcile_olx_location,
    sync_ai_extract,
)
from infra.config import get_config  # noqa: E402
from infra.db import SessionLocal  # noqa: E402


def _delete_image_dirs(property_ids: list) -> int:
    base = get_config().image_storage_path
    if not base:
        return 0
    removed = 0
    root = Path(base)
    for pid in property_ids:
        image_dir = root / str(pid)
        if image_dir.exists():
            shutil.rmtree(image_dir, ignore_errors=True)
            removed += 1
    return removed


def _infer_listing_type(
    *,
    title: str | None,
    price: float | None,
    raw_json: dict | None,
    current: str,
) -> str:
    if isinstance(raw_json, dict) and raw_json:
        detected = OLXScraper._detect_listing_type(raw_json)
        if detected in ("rent", "sale"):
            return detected
    return infer_olx_listing_type(title=title, price=price, current=current)


def _neighborhood_catalog(session: Session) -> list[str]:
    cfg = get_config()
    geo = cfg.scraping.geo_allowlist
    names = list(load_neighborhood_names(session, list(geo.cities)))
    olx = cfg.scraping.platforms.get("olx")
    extra = (olx.extra if olx else {}) or {}
    if hasattr(extra, "get"):
        raw_nb = extra.get("neighborhoods") or []
    else:
        raw_nb = getattr(extra, "neighborhoods", None) or []
    slugs = [
        item.get("slug") if isinstance(item, dict) else getattr(item, "slug", None)
        for item in raw_nb
    ]
    names.extend(humanize_neighborhood_slugs([s for s in slugs if s]))
    names.extend(["Itapoã", "Itapoa", "São Tomáz", "Sao Tomaz"])
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        key = n.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
    return out


def _fix_listing_types(session: Session, prop: Property, apply: bool) -> bool:
    listings = (
        session.query(PropertyListing)
        .filter(
            PropertyListing.property_id == prop.id,
            PropertyListing.platform == "olx",
        )
        .all()
    )
    changed = False
    for listing in listings:
        new_type = _infer_listing_type(
            title=prop.title,
            price=float(listing.price or prop.price or 0),
            raw_json=listing.raw_json if isinstance(listing.raw_json, dict) else None,
            current=listing.listing_type or "sale",
        )
        if new_type == listing.listing_type:
            continue
        changed = True
        if apply:
            # Unique constraint is (platform, platform_listing_id, listing_type).
            conflict = (
                session.query(PropertyListing)
                .filter(
                    PropertyListing.platform == listing.platform,
                    PropertyListing.platform_listing_id == listing.platform_listing_id,
                    PropertyListing.listing_type == new_type,
                    PropertyListing.id != listing.id,
                )
                .one_or_none()
            )
            if conflict is not None:
                session.delete(listing)
            else:
                listing.listing_type = new_type
                if new_type == "sale" and listing.base_price is not None:
                    # Undo erroneous condo/IPTU rollup when possible.
                    listing.price = listing.base_price
                    listing.base_price = None
    if changed and apply:
        props = dict(prop.props_json or {})
        # Prefer sale if any OLX listing is sale after fix.
        types = {
            pl.listing_type
            for pl in session.query(PropertyListing)
            .filter(
                PropertyListing.property_id == prop.id,
                PropertyListing.platform == "olx",
            )
            .all()
        }
        props["available_for_sale"] = "sale" in types
        props["available_for_rent"] = "rent" in types
        prop.props_json = props
    return changed


def _apply_location(
    session: Session,
    prop: Property,
    *,
    catalog: list[str],
    cities: list[str],
    states: list[str],
    ai_extract,
    apply: bool,
) -> str:
    """Return action: unchanged|corrected|out_of_geo|ai_failed."""
    props = dict(prop.props_json or {})
    result = reconcile_olx_location(
        title=prop.title,
        description=prop.description,
        scraped_city=props.get("city"),
        scraped_neighborhood=props.get("neighborhood"),
        scraped_state=props.get("state"),
        scraped_address=prop.address,
        allowed_cities=cities,
        allowed_states=states,
        known_neighborhoods=catalog,
        ai_extract=ai_extract,
    )
    if result.action in ("unchanged", "ai_failed"):
        return result.action
    # out_of_geo: caller deletes the row — do not dirty the ORM instance.
    if result.action == "out_of_geo":
        return result.action
    if not apply:
        return result.action

    if result.city:
        props["city"] = result.city
    if result.state:
        props["state"] = result.state
    if result.neighborhood:
        props["neighborhood"] = result.neighborhood
    props["olx_location_corrected"] = True
    if result.reason:
        props["olx_location_reason"] = result.reason
    prop.props_json = props
    if result.address:
        prop.address = result.address
    if result.clear_coords:
        prop.location = None
        prop.neighborhood_id = None
        if result.neighborhood:
            assign_property_neighbourhood_by_name(
                session,
                prop.id,
                name=result.neighborhood,
                city=result.city,
            )
    return result.action


def _find_duplicate(
    session: Session,
    prop: Property,
    *,
    text_threshold: float,
    area_tol: float,
) -> Optional[UUID]:
    """Find another active property that likely is the same listing after correction."""
    if not prop.title:
        return None
    city = (prop.props_json or {}).get("city")
    rows = session.execute(
        text(
            """
            SELECT id, title, area_m2, props_json
            FROM properties
            WHERE active = true AND id <> :pid
            """
        ),
        {"pid": prop.id},
    ).fetchall()
    for row in rows:
        other_city = (row.props_json or {}).get("city") if isinstance(row.props_json, dict) else None
        if city and other_city and _fold(city) != _fold(other_city):
            continue
        area_a = float(prop.area_m2) if prop.area_m2 else None
        area_b = float(row.area_m2) if row.area_m2 else None
        if not area_a or not area_b:
            continue  # missing/zero area → too many false positives
        if abs(area_a - area_b) > area_tol:
            continue
        if text_similarity(prop.title or "", row.title or "") >= text_threshold:
            return row.id
    return None


def _merge_into(session: Session, keeper_id: UUID, orphan: Property) -> None:
    """Move OLX listings onto keeper and delete orphan property."""
    session.execute(
        text(
            """
            UPDATE property_listings
            SET property_id = :keeper
            WHERE property_id = :orphan AND platform = 'olx'
            """
        ),
        {"keeper": keeper_id, "orphan": orphan.id},
    )
    session.execute(
        text("DELETE FROM properties WHERE id = :pid"),
        {"pid": orphan.id},
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fix OLX listing types and seller-vs-property locations (BIN-72)."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist changes. Default is dry-run only.",
    )
    parser.add_argument(
        "--skip-ai",
        action="store_true",
        help="Heuristic-only location reconcile (no Ollama).",
    )
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="Skip fuzzy duplicate merges (recommended: template OLX titles false-positive heavily).",
    )
    parser.add_argument(
        "--types-only",
        action="store_true",
        help="Only reclassify listing_type / availability flags (skip location, purge, merge).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max OLX properties to scan (0 = all).",
    )
    args = parser.parse_args(argv)

    cfg = get_config()
    cities = list(cfg.scraping.geo_allowlist.cities)
    states = list(cfg.scraping.geo_allowlist.states)
    text_threshold = cfg.dedup.text_similarity_threshold
    area_tol = cfg.dedup.area_tolerance_m2
    ai_extract = None if args.skip_ai or args.types_only else sync_ai_extract

    counts: Counter[str] = Counter()
    purge_ids: list = []
    merge_orphans: list = []

    with SessionLocal() as session:
        catalog = [] if args.types_only else _neighborhood_catalog(session)
        q = (
            session.query(Property)
            .filter(Property.platform == "olx")
            .order_by(Property.first_seen.desc())
        )
        if args.limit and args.limit > 0:
            q = q.limit(args.limit)
        props = q.all()

        print(
            f"Scanning {len(props)} OLX properties "
            f"(apply={args.apply}, skip_ai={args.skip_ai}, types_only={args.types_only})"
        )
        if not args.types_only:
            print(f"Allowlist cities: {cities}")

        for prop in props:
            if _fix_listing_types(session, prop, apply=args.apply):
                counts["type_fixed"] += 1

            if args.types_only:
                continue

            loc_action = _apply_location(
                session,
                prop,
                catalog=catalog,
                cities=cities,
                states=states,
                ai_extract=ai_extract,
                apply=args.apply,
            )
            counts[f"location_{loc_action}"] += 1

            if loc_action == "out_of_geo":
                purge_ids.append(prop.id)
                counts["purged_out_of_geo"] += 1
                continue

            # Geo gate on final props (including corrected).
            ok, _reason = passes_geo_allowlist(
                prop, cities=cities, states=states, enabled=True
            )
            if not ok:
                purge_ids.append(prop.id)
                counts["purged_out_of_geo"] += 1
                continue

            if not args.no_merge:
                dup = _find_duplicate(
                    session,
                    prop,
                    text_threshold=text_threshold,
                    area_tol=area_tol,
                )
                if dup is not None:
                    counts["merged_dupes"] += 1
                    merge_orphans.append((dup, prop))
                    continue

            if loc_action == "unchanged":
                counts["unchanged"] += 1

        for reason, count in sorted(counts.items()):
            print(f"  {reason}: {count}")
        print(f"  would_purge: {len(purge_ids)}")
        print(f"  would_merge: {len(merge_orphans)}")

        if not args.apply:
            print("Dry-run only. Re-run with --apply to persist.")
            return 0

        for keeper_id, orphan in merge_orphans:
            if orphan.id in purge_ids:
                continue
            _merge_into(session, keeper_id, orphan)
            _delete_image_dirs([orphan.id])

        purge_set = set(purge_ids)
        # Expunge anything tied to purge targets so CASCADE delete cannot
        # race pending UPDATEs (StaleDataError on properties / listings).
        for obj in list(session.identity_map.values()):
            if isinstance(obj, Property) and obj.id in purge_set:
                session.expunge(obj)
            elif isinstance(obj, PropertyListing) and obj.property_id in purge_set:
                session.expunge(obj)

        session.commit()
        print("Applied type/location updates.")

        if purge_ids:
            with SessionLocal() as purge_session:
                chunk = 500
                deleted = 0
                for i in range(0, len(purge_ids), chunk):
                    batch = purge_ids[i : i + chunk]
                    result = purge_session.execute(
                        text("DELETE FROM properties WHERE id = ANY(:ids)"),
                        {"ids": batch},
                    )
                    deleted += result.rowcount or 0
                purge_session.commit()
            images_removed = _delete_image_dirs(purge_ids)
            print(
                f"Purged {deleted} out-of-geo properties "
                f"(image dirs removed: {images_removed})."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
