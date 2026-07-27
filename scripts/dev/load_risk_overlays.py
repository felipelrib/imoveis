#!/usr/bin/env python3
"""Load flood / environmental risk overlays onto neighbourhood profiles.

Vendor-agnostic: pass GeoJSON paths (or a YAML path map). Missing files are
skipped with a clear log — not a hard failure. Does not hardcode municipal URLs.

Usage:
  PYTHONPATH=src python scripts/dev/load_risk_overlays.py \\
    --geojson src/tests/fixtures/geo/bh_risk_flood_tiny.geojson \\
    --risk-type flood_zone --city "Belo Horizonte" --dry-run

  PYTHONPATH=src python scripts/dev/load_risk_overlays.py \\
    --config configs/risk_overlays.example.yaml
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "src"))

from core.risk_overlay import (  # noqa: E402
    MANAGED_RISK_FLAGS,
    RiskOverlayError,
    RiskOverlayLayer,
    load_and_apply_risk_overlays,
    load_risk_layers,
)

logger = logging.getLogger("load_risk_overlays")


def _load_config(path: Path) -> list[dict[str, Any]]:
    import yaml

    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise RiskOverlayError("Config root must be a mapping")
    cities = data.get("cities")
    if not isinstance(cities, list):
        raise RiskOverlayError("Config must include a cities list")
    return cities


def _layers_from_city(entry: dict[str, Any], *, repo_root: Path) -> list[RiskOverlayLayer]:
    layers_raw = entry.get("layers") or []
    if not isinstance(layers_raw, list):
        raise RiskOverlayError("city.layers must be a list")
    out: list[RiskOverlayLayer] = []
    for layer in layers_raw:
        if not isinstance(layer, dict) or not layer.get("path"):
            raise RiskOverlayError("Each layer needs a path")
        risk_type = layer.get("risk_type")
        if risk_type is not None:
            risk_type = str(risk_type).strip()
            if risk_type not in MANAGED_RISK_FLAGS:
                raise RiskOverlayError(
                    f"Unsupported risk_type {risk_type!r}; "
                    f"expected one of {sorted(MANAGED_RISK_FLAGS)}"
                )
        path = Path(str(layer["path"]))
        if not path.is_absolute():
            path = repo_root / path
        out.append(RiskOverlayLayer(path=path, risk_type=risk_type))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Intersect neighbourhood polygons with risk GeoJSON overlays "
            "and write risk_flags / quality_meta.risk."
        )
    )
    parser.add_argument(
        "--config",
        help="YAML path map (see configs/risk_overlays.example.yaml).",
    )
    parser.add_argument(
        "--geojson",
        help="Single GeoJSON FeatureCollection path (one-shot mode).",
    )
    parser.add_argument(
        "--risk-type",
        choices=sorted(MANAGED_RISK_FLAGS),
        help="Default risk_type when features omit properties.risk_type.",
    )
    parser.add_argument(
        "--city",
        default="Belo Horizonte",
        help="City for one-shot mode / neighbourhood filter (default: Belo Horizonte).",
    )
    parser.add_argument(
        "--state",
        default="MG",
        help="UF for one-shot mode (default: MG).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report intersections; do not write to the database.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="DEBUG logging.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if not args.config and not args.geojson:
        parser.error("provide --config and/or --geojson")

    jobs: list[tuple[str, str, list[RiskOverlayLayer]]] = []
    repo_root = Path(_REPO)

    if args.geojson:
        if not args.risk_type:
            # Allow features to carry risk_type themselves
            pass
        jobs.append(
            (
                args.city,
                args.state,
                [RiskOverlayLayer(path=Path(args.geojson), risk_type=args.risk_type)],
            )
        )

    if args.config:
        try:
            for entry in _load_config(Path(args.config)):
                city = str(entry.get("city") or "").strip()
                state = str(entry.get("state") or "").strip().upper()
                if not city or len(state) != 2:
                    raise RiskOverlayError(
                        "Each config city entry needs city and 2-letter state"
                    )
                jobs.append((city, state, _layers_from_city(entry, repo_root=repo_root)))
        except (OSError, RiskOverlayError, json.JSONDecodeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    if args.dry_run:
        for city, state, layers in jobs:
            try:
                features, skipped = load_risk_layers(
                    layers, default_city=city, default_state=state
                )
            except (OSError, RiskOverlayError, json.JSONDecodeError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
            print(
                f"[dry-run] {city}/{state}: loaded={len(features)} "
                f"features, skipped_missing={skipped}"
            )
            by_type: dict[str, int] = {}
            for feat in features:
                by_type[feat.risk_type] = by_type.get(feat.risk_type, 0) + 1
            for risk_type, count in sorted(by_type.items()):
                print(f"  - {risk_type}: {count} polygon(s)")
        print("Dry-run complete; no database writes.")
        return 0

    from infra.db import SessionLocal

    exit_code = 0
    with SessionLocal() as session:
        for city, state, layers in jobs:
            try:
                result = load_and_apply_risk_overlays(
                    session, layers, city=city, state=state
                )
            except (OSError, RiskOverlayError, json.JSONDecodeError) as exc:
                print(f"error ({city}/{state}): {exc}", file=sys.stderr)
                exit_code = 1
                continue
            print(
                f"{city}/{state}: updated={result.updated} "
                f"unchanged={result.unchanged} "
                f"no_geometry={result.skipped_no_geometry} "
                f"layers_loaded={result.layers_loaded} "
                f"layers_skipped_missing={result.layers_skipped_missing}"
            )
        if exit_code == 0:
            session.commit()
        else:
            session.rollback()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
