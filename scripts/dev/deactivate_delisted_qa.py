#!/usr/bin/env python3
"""Classify & deactivate delisted QuintoAndar rows with empty descriptions (BIN-249).

Follow-up to the BIN-245 description backfill: ~898 active QA rows still have an
empty ``description``. Most are not text-less live listings — they are delisted
listings whose ``/imovel/{id}`` now serves an empty-``houseInfo`` placeholder shell
(never 301-redirecting to a slug). This script probes each such row and buckets it:

* **delisted**   — availability probe returns UNAVAILABLE (``qa_placeholder_shell``,
                   ``qa_house_despublicado``, 404/410, …). Soft-deactivated on --apply.
* **duplicate**  — ``/imovel/{id}`` redirects to a *different* live listing id. The
                   stale row is deactivated; if the canonical id already exists in the
                   DB it is reported as a merge target.
* **no_text**    — probe returns AVAILABLE for the same id: a genuinely text-less live
                   listing. Left untouched (BIN-243 neutral sentiment already covers it).
* **unknown**    — transient (Cloudflare 403 / timeout / 5xx). Left active for retry.

Default is dry-run. With ``--apply`` it soft-deactivates delisted/duplicate rows via
the same ``deactivate_listing_and_maybe_property`` path the availability_recheck job
uses (property flips inactive only when no active listing remains).

Usage:
  PYTHONPATH=src python scripts/dev/deactivate_delisted_qa.py
  PYTHONPATH=src python scripts/dev/deactivate_delisted_qa.py --apply --limit 100
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from typing import Any, Optional

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from adapters.scrapers.availability import (  # noqa: E402
    _QA_LISTING_ID_RE,
    AvailabilityStatus,
    classify_response,
    deactivate_listing_and_maybe_property,
)
from adapters.scrapers.http_client import create_scraper_http_client  # noqa: E402
from infra.config import get_config  # noqa: E402
from infra.db import SessionLocal  # noqa: E402
from infra.logging import get_logger  # noqa: E402

logger = get_logger(__name__)


def select_empty_description_qa_listings(
    session: Session, *, limit: int = 0
) -> list[Any]:
    """Active QuintoAndar listing rows whose property has an empty description."""
    sql = """
        SELECT pl.id AS listing_id,
               pl.property_id,
               pl.listing_type,
               pl.url
        FROM property_listings pl
        JOIN properties p ON p.id = pl.property_id
        WHERE pl.active = true
          AND p.platform = 'quintoandar'
          AND COALESCE(TRIM(p.description), '') = ''
          AND COALESCE(TRIM(pl.url), '') <> ''
        ORDER BY pl.last_seen ASC NULLS FIRST
    """
    params: dict[str, Any] = {}
    if limit and limit > 0:
        sql += " LIMIT :limit"
        params["limit"] = int(limit)
    return list(session.execute(text(sql), params).fetchall())


def _qa_id_from_url(url: str | None) -> Optional[str]:
    if not url:
        return None
    match = _QA_LISTING_ID_RE.search(url)
    return match.group(1) if match else None


def _canonical_exists(session: Session, platform_id: str) -> bool:
    row = session.execute(
        text(
            "SELECT 1 FROM properties "
            "WHERE platform = 'quintoandar' AND platform_id = :pid "
            "AND active = true LIMIT 1"
        ),
        {"pid": platform_id},
    ).fetchone()
    return row is not None


def classify_row(client: Any, url: str, listing_type: str | None) -> tuple[str, str, Optional[str]]:
    """Return (bucket, reason, final_id) for one QA listing URL.

    bucket is one of: delisted | duplicate | no_text | unknown.
    """
    try:
        response = client.get(url)
    except Exception as exc:  # noqa: BLE001 — transient network errors stay unknown
        logger.warning("qa_sweep_http_error", url=url, error=str(exc))
        return "unknown", "http_error", None

    final_url = str(response.url)
    result = classify_response(
        "quintoandar",
        status_code=response.status_code,
        html=response.text or "",
        request_url=url,
        final_url=final_url,
        listing_type=listing_type,
    )
    requested_id = _qa_id_from_url(url)
    final_id = _qa_id_from_url(final_url)

    if result.status == AvailabilityStatus.UNAVAILABLE:
        return "delisted", result.reason, final_id
    if final_id and requested_id and final_id != requested_id:
        # Redirected to a different canonical listing (BIN-249 case c).
        return "duplicate", result.reason, final_id
    if result.status == AvailabilityStatus.AVAILABLE:
        return "no_text", result.reason, final_id
    return "unknown", result.reason, final_id


def run_sweep(session: Session, *, apply: bool, limit: int) -> Counter:
    counts: Counter = Counter()
    rows = select_empty_description_qa_listings(session, limit=limit)
    counts["candidates"] = len(rows)

    cfg = get_config()
    timeout = float(cfg.scraping.availability_recheck.request_timeout_sec)
    client = create_scraper_http_client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": cfg.scraping.user_agent},
    )
    try:
        for row in rows:
            bucket, reason, final_id = classify_row(
                client, str(row.url), str(row.listing_type) if row.listing_type else None
            )
            counts[bucket] += 1

            if bucket == "duplicate" and final_id:
                canonical = _canonical_exists(session, final_id)
                counts["duplicate_canonical_present" if canonical else "duplicate_gone"] += 1

            logger.info(
                "qa_sweep_classified",
                listing_id=str(row.listing_id),
                bucket=bucket,
                reason=reason,
                url=str(row.url),
                final_id=final_id,
            )

            if bucket in ("delisted", "duplicate"):
                counts["would_deactivate" if not apply else "deactivated"] += 1
                if apply:
                    summary = deactivate_listing_and_maybe_property(
                        session, str(row.listing_id)
                    )
                    if summary.get("property_deactivated"):
                        counts["properties_deactivated"] += 1
                    session.commit()
    finally:
        client.close()
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Classify & deactivate delisted QuintoAndar rows (BIN-249)."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Soft-deactivate delisted/duplicate rows. Default is dry-run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max listing rows to probe (0 = all).",
    )
    args = parser.parse_args(argv)

    with SessionLocal() as session:
        counts = run_sweep(session, apply=args.apply, limit=args.limit)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] {dict(counts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
