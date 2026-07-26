"""Deactivate properties below the photo gate (BIN-78).

Keeps rows for offline price/geo analysis but hides them from the deal feed
(``active=false``) and stops wasting VLM budget on thin galleries.

Usage:
  PYTHONPATH=src python scripts/dev/deactivate_low_photo_properties.py
  PYTHONPATH=src python scripts/dev/deactivate_low_photo_properties.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "src"))

from adapters.db.models import Property  # noqa: E402
from core.photo_gate import (  # noqa: E402
    passes_photo_gate,
    photo_gate_kwargs_from_config,
)
from infra.config import get_config  # noqa: E402
from infra.db import SessionLocal  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deactivate properties below the configured photo gate."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Set active=false on matching rows. Default is dry-run only.",
    )
    parser.add_argument(
        "--reactivate",
        action="store_true",
        help="Also set active=true on inactive rows that now pass the gate.",
    )
    args = parser.parse_args(argv)

    cfg = get_config()
    gate_kwargs = photo_gate_kwargs_from_config(cfg.scraping.photo_gate, cfg.ai)

    reasons: Counter[str] = Counter()
    deactivate_ids: list = []
    reactivate_ids: list = []

    with SessionLocal() as session:
        props = session.query(Property).all()
        for prop in props:
            ok, reason, count, required = passes_photo_gate(prop, **gate_kwargs)
            if not ok:
                reasons[reason or "too_few_photos"] += 1
                if prop.active:
                    deactivate_ids.append(prop.id)
            elif args.reactivate and not prop.active:
                reactivate_ids.append(prop.id)
                reasons[f"reactivate_ok:{count}>={required}"] += 1

        print(f"Scanned {len(props)} properties")
        print(
            "Gate: enabled={enabled} floor_min={floor_min} "
            "coverage_ratio={coverage_ratio} max_images={max_images_per_property} "
            "min_photos_override={min_photos}".format(**gate_kwargs)
        )
        print(f"Would deactivate (currently active): {len(deactivate_ids)}")
        if args.reactivate:
            print(f"Would reactivate (currently inactive): {len(reactivate_ids)}")
        for reason, count in sorted(reasons.items(), key=lambda x: (-x[1], x[0])):
            print(f"  {reason}: {count}")

        if not args.apply:
            print("Dry-run only. Re-run with --apply to update.")
            return 0

        changed = 0
        for pid in deactivate_ids:
            prop = session.get(Property, pid)
            if prop is not None:
                prop.active = False
                changed += 1
        for pid in reactivate_ids:
            prop = session.get(Property, pid)
            if prop is not None:
                prop.active = True
                changed += 1
        session.commit()
        print(f"Updated {changed} properties.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
