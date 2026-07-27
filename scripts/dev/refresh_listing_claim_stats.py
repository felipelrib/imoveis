#!/usr/bin/env python3
"""Aggregate listing LLM sentiment flags into neighbourhood profiles (BIN-93).

Writes nested quality_meta.listing_claim_stats only — does not overwrite
amenity/transit/access/safety scores. Weak secondary signal; seller ads omit
problems.

Usage:
  PYTHONPATH=src python scripts/dev/refresh_listing_claim_stats.py
"""

from __future__ import annotations

import os
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "src"))

from adapters.geo.listing_claim_refresh import refresh_listing_claim_stats  # noqa: E402
from infra.config import get_config  # noqa: E402
from infra.db import SessionLocal  # noqa: E402


def main() -> int:
    cfg = get_config().neighbourhood_quality.listing_claim_stats
    with SessionLocal() as session:
        stats = refresh_listing_claim_stats(session, cfg)
    print(stats)
    return 0 if stats.get("errors", 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
