#!/usr/bin/env python3
"""Purge properties outside the configured geo keep-list (BIN-70).

Deletes rows whose city is missing or not in the allowlist (default:
Belo Horizonte, São Paulo, Campinas). Uses the same extract/fold rules as
ingest (``core.geo_allowlist``).

Uses bulk SQL DELETE (FK CASCADE) rather than ORM session.delete to avoid
per-row after_delete hooks on large purges.

Usage:
  PYTHONPATH=src python scripts/dev/purge_out_of_geo_properties.py
  PYTHONPATH=src python scripts/dev/purge_out_of_geo_properties.py --apply
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "src"))

from sqlalchemy import text  # noqa: E402

from adapters.db.models import Property  # noqa: E402
from core.geo_allowlist import passes_geo_allowlist  # noqa: E402
from infra.config import get_config  # noqa: E402
from infra.db import SessionLocal  # noqa: E402


def _reject_reason(prop: Property, cities: list[str], states: list[str]) -> str | None:
    candidate = SimpleNamespace(props_json=prop.props_json, address=prop.address)
    ok, reason = passes_geo_allowlist(
        candidate, cities=cities, states=states, enabled=True
    )
    return None if ok else (reason or "rejected")


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Purge properties outside geo allowlist (missing city or wrong city)."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Hard-delete matching rows. Default is dry-run only.",
    )
    args = parser.parse_args(argv)

    cfg = get_config().scraping.geo_allowlist
    cities = list(cfg.cities)
    states = list(cfg.states)

    reasons: Counter[str] = Counter()
    delete_ids: list = []

    with SessionLocal() as session:
        props = session.query(Property).all()
        for prop in props:
            reason = _reject_reason(prop, cities, states)
            if reason is None:
                continue
            reasons[reason] += 1
            delete_ids.append(prop.id)

        print(f"Scanned {len(props)} properties")
        print(f"Keep cities: {cities}")
        print(f"Keep states: {states}")
        print(f"Would delete: {len(delete_ids)}")
        for reason, count in sorted(reasons.items(), key=lambda x: (-x[1], x[0])):
            print(f"  {reason}: {count}")

        if not args.apply:
            print("Dry-run only. Re-run with --apply to delete.")
            return 0

        if not delete_ids:
            print("Nothing to delete.")
            return 0

        # Bulk delete in chunks (FK CASCADE on children).
        chunk = 500
        deleted = 0
        for i in range(0, len(delete_ids), chunk):
            batch = delete_ids[i : i + chunk]
            result = session.execute(
                text("DELETE FROM properties WHERE id = ANY(:ids)"),
                {"ids": batch},
            )
            deleted += result.rowcount or 0
        session.commit()
        images_removed = _delete_image_dirs(delete_ids)
        print(f"Deleted {deleted} properties (image dirs removed: {images_removed}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
