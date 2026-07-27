#!/usr/bin/env python3
"""Build BH neighbourhood safety rates from SEJUSP regional or bairro extracts.

Regional path (default): expands configs/bh_regional_crime_counts.yaml via
configs/bh_neighbourhood_regionals.yaml → rates YAML for load_safety_overlays.

Bairro path: aggregate an on-demand / LAI CSV (columns bairro, registros).

Usage:
  PYTHONPATH=src python scripts/dev/build_bh_safety_rates.py \\
    --out configs/bh_safety_rates.yaml

  PYTHONPATH=src python scripts/dev/build_bh_safety_rates.py \\
    --bairro-csv data/safety/sejusp_bh_bairro.csv --out data/safety/bh_crime_rates.yaml
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "src"))

import yaml  # noqa: E402

from core.bh_safety_rates import (  # noqa: E402
    DEFAULT_COUNTS_PATH,
    DEFAULT_REGIONALS_PATH,
    aggregate_bairro_extract_csv,
    build_bh_regional_safety_rates,
    rates_to_yaml_dict,
)
from core.safety_overlay import SafetyOverlayError  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build Belo Horizonte safety rate YAML (BIN-96)."
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output rates YAML path.",
    )
    parser.add_argument(
        "--regionals",
        default=str(DEFAULT_REGIONALS_PATH),
        help="Neighbourhood → regional map YAML.",
    )
    parser.add_argument(
        "--counts",
        default=str(DEFAULT_COUNTS_PATH),
        help="Regional crime counts YAML.",
    )
    parser.add_argument(
        "--bairro-csv",
        help="Optional SEJUSP bairro extract CSV (overrides regional expansion).",
    )
    parser.add_argument(
        "--bairro-column",
        default="bairro",
        help="Bairro column name in --bairro-csv.",
    )
    parser.add_argument(
        "--count-column",
        default="registros",
        help="Count column name in --bairro-csv.",
    )
    args = parser.parse_args(argv)

    try:
        if args.bairro_csv:
            rows = aggregate_bairro_extract_csv(
                Path(args.bairro_csv),
                bairro_column=args.bairro_column,
                count_column=args.count_column,
            )
        else:
            rows = build_bh_regional_safety_rates(
                regionals_path=Path(args.regionals),
                counts_path=Path(args.counts),
            )
        payload = rates_to_yaml_dict(rows)
    except (OSError, SafetyOverlayError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, allow_unicode=True, sort_keys=False)
    print(f"wrote {len(rows)} rates → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
