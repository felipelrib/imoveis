#!/usr/bin/env python3
"""Refresh neighbourhood access_score from YAML hubs (BIN-90).

Uses OSRM when neighbourhood_access.base_url is set; otherwise haversine +
avg_speed_kmh. Safe to re-run — merges nested quality_meta.access only.

Usage:
  PYTHONPATH=src python scripts/dev/refresh_neighbourhood_access.py
"""

from __future__ import annotations

import os
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "src"))

from adapters.geo.access_refresh import refresh_neighbourhood_access  # noqa: E402
from infra.config import get_config  # noqa: E402
from infra.db import SessionLocal  # noqa: E402


def main() -> int:
    cfg = get_config().neighbourhood_access
    if cfg.enabled is not True:
        print("neighbourhood_access is disabled in config")
        return 1
    with SessionLocal() as session:
        stats = refresh_neighbourhood_access(session, cfg)
    print(stats)
    return 0 if stats.get("errors", 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
