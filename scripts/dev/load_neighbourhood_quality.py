#!/usr/bin/env python3
"""Load curated neighbourhood quality scores from YAML into PostGIS.

Scores are operator judgment (quality_meta.source=curated), not ground truth.
Unknown neighbourhood names are skipped — this never invents rows.

Usage:
  PYTHONPATH=src python scripts/dev/load_neighbourhood_quality.py

  PYTHONPATH=src python scripts/dev/load_neighbourhood_quality.py \\
    --yaml configs/neighbourhood_quality.yaml --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "src"))

from core.neighbourhood_quality_yaml import (  # noqa: E402
    DEFAULT_YAML_PATH,
    NeighbourhoodQualityYamlError,
    load_curated_neighbourhood_quality,
    parse_curated_yaml,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Idempotent load of curated neighbourhood quality profiles "
            "(source=curated). Skips unknown names."
        )
    )
    parser.add_argument(
        "--yaml",
        default=str(DEFAULT_YAML_PATH),
        help=f"Path to curated YAML (default: {DEFAULT_YAML_PATH}).",
    )
    parser.add_argument(
        "--city",
        default="Belo Horizonte",
        help="Default city when a profile omits city (default: Belo Horizonte).",
    )
    parser.add_argument(
        "--state",
        default="MG",
        help="Default UF when a profile omits state (default: MG).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate only; do not write to the database.",
    )
    args = parser.parse_args(argv)

    try:
        rows = parse_curated_yaml(
            args.yaml, default_city=args.city, default_state=args.state
        )
    except (OSError, NeighbourhoodQualityYamlError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Parsed {len(rows)} curated profile(s) from {args.yaml}")
    if args.dry_run:
        for row in rows:
            print(
                f"  - {row.name} ({row.city}/{row.state}) "
                f"amenity={row.amenity_score} transit={row.transit_score} "
                f"access={row.access_score} safety={row.safety_score} "
                f"flags={list(row.risk_flags)}"
            )
        print("Dry-run complete; no database writes.")
        return 0

    from infra.db import SessionLocal

    with SessionLocal() as session:
        result = load_curated_neighbourhood_quality(
            session,
            args.yaml,
            default_city=args.city,
            default_state=args.state,
        )
        session.commit()

    print(f"Done: updated={result.updated} skipped={result.skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
