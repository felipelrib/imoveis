#!/usr/bin/env python3
"""Backfill empty property descriptions from platform detail pages (BIN-105).

Default is dry-run. With ``--apply``:

1. Select active properties with empty ``description`` and an active listing URL.
2. Fetch the detail page via the platform scraper (throttled).
3. Update ``properties.description`` when text is found.
4. Enqueue ``embed_property`` so semantic search picks up the new text.

Usage:
  PYTHONPATH=src python scripts/dev/backfill_listing_descriptions.py
  PYTHONPATH=src python scripts/dev/backfill_listing_descriptions.py --apply --limit 50
  PYTHONPATH=src python scripts/dev/backfill_listing_descriptions.py --apply --platform quintoandar
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from typing import Any, Optional
from uuid import UUID

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from adapters.scrapers.olx import OLXScraper  # noqa: E402
from adapters.scrapers.quintoandar import QuintoAndarScraper  # noqa: E402
from infra.config import get_config  # noqa: E402
from infra.db import SessionLocal  # noqa: E402
from infra.logging import get_logger  # noqa: E402

logger = get_logger(__name__)

_SUPPORTED = frozenset({"quintoandar", "olx"})


def select_empty_description_rows(
    session: Session,
    *,
    platform: Optional[str] = None,
    limit: int = 0,
) -> list[Any]:
    """Return rows needing description backfill (property id, platform, url)."""
    clauses = [
        "p.active = true",
        "COALESCE(TRIM(p.description), '') = ''",
        "pl.active = true",
        "COALESCE(TRIM(pl.url), '') <> ''",
    ]
    params: dict[str, Any] = {}
    if platform:
        clauses.append("p.platform = :platform")
        params["platform"] = platform
    else:
        clauses.append("p.platform IN ('quintoandar', 'olx')")

    sql = f"""
        SELECT DISTINCT ON (p.id)
            p.id AS property_id,
            p.platform,
            p.platform_id,
            pl.url
        FROM properties p
        JOIN property_listings pl ON pl.property_id = p.id
        WHERE {" AND ".join(clauses)}
        ORDER BY p.id, pl.last_seen DESC NULLS LAST
    """
    if limit and limit > 0:
        sql += " LIMIT :limit"
        params["limit"] = int(limit)

    return list(session.execute(text(sql), params).fetchall())


def _build_scraper(platform: str):
    cfg = get_config()
    plat_cfg = cfg.scraping.platforms.get(platform)
    raw = {}
    if plat_cfg is not None:
        raw = {
            "rate_limit": getattr(plat_cfg, "rate_limit", 20),
            "jitter_min": getattr(plat_cfg, "jitter_min", 1),
            "jitter_max": getattr(plat_cfg, "jitter_max", 3),
            "extra": dict(getattr(plat_cfg, "extra", None) or {}),
        }
    if platform == "quintoandar":
        scraper = QuintoAndarScraper("quintoandar", raw or {"rate_limit": 30})
    elif platform == "olx":
        scraper = OLXScraper("olx", raw or {"rate_limit": 20, "jitter_min": 1, "jitter_max": 3})
    else:
        raise ValueError(f"unsupported platform: {platform}")
    scraper.start()
    return scraper


def apply_description(
    session: Session,
    *,
    property_id: UUID | str,
    description: str,
) -> None:
    session.execute(
        text(
            "UPDATE properties SET description = :description "
            "WHERE id = CAST(:pid AS uuid)"
        ),
        {"description": description, "pid": str(property_id)},
    )


def enqueue_embed(property_id: UUID | str) -> None:
    from adapters.queue import tasks as tasks_mod

    tasks_mod.embed_property.apply_async(args=[str(property_id)], queue="ai")


def run_backfill(
    session: Session,
    *,
    apply: bool,
    platform: Optional[str],
    limit: int,
    scrapers: Optional[dict[str, Any]] = None,
    enqueue: bool = True,
) -> Counter:
    counts: Counter = Counter()
    rows = select_empty_description_rows(session, platform=platform, limit=limit)
    counts["candidates"] = len(rows)
    own_scrapers: dict[str, Any] = {}
    try:
        for row in rows:
            plat = (row.platform or "").strip().lower()
            if plat not in _SUPPORTED:
                counts["unsupported"] += 1
                continue
            scraper = (scrapers or own_scrapers).get(plat)
            if scraper is None:
                scraper = _build_scraper(plat)
                own_scrapers[plat] = scraper
            description = (scraper.fetch_description(row.url) or "").strip()
            if not description:
                counts["empty_detail"] += 1
                logger.info(
                    "backfill_description_empty",
                    platform=plat,
                    property_id=str(row.property_id),
                    url=row.url,
                )
                continue
            counts["would_update" if not apply else "updated"] += 1
            if not apply:
                continue
            apply_description(
                session, property_id=row.property_id, description=description
            )
            session.commit()
            if enqueue:
                try:
                    enqueue_embed(row.property_id)
                    counts["embed_enqueued"] += 1
                except Exception as exc:  # noqa: BLE001
                    counts["embed_error"] += 1
                    logger.warning(
                        "backfill_embed_enqueue_error",
                        property_id=str(row.property_id),
                        error=str(exc),
                    )
    finally:
        for scraper in own_scrapers.values():
            try:
                scraper.close()
            except Exception:  # noqa: BLE001
                pass
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill empty listing descriptions from detail pages (BIN-105)."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist description updates and enqueue embeds. Default is dry-run.",
    )
    parser.add_argument(
        "--platform",
        choices=sorted(_SUPPORTED),
        default=None,
        help="Limit to one platform (default: quintoandar + olx).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max properties to process (0 = all).",
    )
    parser.add_argument(
        "--no-embed",
        action="store_true",
        help="Skip embed_property enqueue after updates.",
    )
    args = parser.parse_args(argv)

    with SessionLocal() as session:
        counts = run_backfill(
            session,
            apply=args.apply,
            platform=args.platform,
            limit=args.limit,
            enqueue=not args.no_embed,
        )

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] {dict(counts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
