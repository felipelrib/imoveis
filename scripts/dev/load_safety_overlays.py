#!/usr/bin/env python3
"""Load crime / safety rate overlays onto neighbourhood profiles.

Vendor-agnostic: pass YAML/CSV rate files (or a YAML path map). Missing files
are skipped with a clear log — not a hard failure. Does not hardcode SSP URLs
or invent rates from listing text.

Usage:
  PYTHONPATH=src python scripts/dev/load_safety_overlays.py \\
    --rates src/tests/fixtures/safety/sp_safety_rates_tiny.yaml --dry-run

  PYTHONPATH=src python scripts/dev/load_safety_overlays.py \\
    --config configs/safety_overlays.example.yaml
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "src"))

from core.safety_overlay import (  # noqa: E402
    SafetyOverlayError,
    load_and_apply_safety_rates,
    load_safety_rates_file,
    safety_score_from_rates,
)

logger = logging.getLogger("load_safety_overlays")


def _load_config(path: Path) -> list[dict[str, Any]]:
    import yaml

    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise SafetyOverlayError("Config root must be a mapping")
    cities = data.get("cities")
    if not isinstance(cities, list):
        raise SafetyOverlayError("Config must include a cities list")
    return cities


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Load neighbourhood crime rates into safety_score / "
            "quality_meta.safety (city-relative scores)."
        )
    )
    parser.add_argument(
        "--config",
        help="YAML path map (see configs/safety_overlays.example.yaml).",
    )
    parser.add_argument(
        "--rates",
        help="Single YAML or CSV rates file (one-shot mode).",
    )
    parser.add_argument(
        "--city",
        default="São Paulo",
        help="City filter for one-shot mode (default: São Paulo).",
    )
    parser.add_argument(
        "--state",
        default="SP",
        help="UF for one-shot mode (default: SP).",
    )
    parser.add_argument(
        "--provider",
        help="Override provider stamped into quality_meta.safety.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report relative scores; do not write to the database.",
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

    if not args.config and not args.rates:
        parser.error("provide --config and/or --rates")

    repo_root = Path(_REPO)
    # Jobs: (label, path, city_filter, state_filter, provider)
    jobs: list[tuple[str, Path, Optional[str], Optional[str], Optional[str]]] = []

    if args.rates:
        jobs.append(
            (
                f"{args.city}/{args.state}",
                Path(args.rates),
                args.city,
                args.state,
                args.provider,
            )
        )

    if args.config:
        try:
            for entry in _load_config(Path(args.config)):
                city = str(entry.get("city") or "").strip()
                state = str(entry.get("state") or "").strip().upper()
                path_raw = entry.get("path")
                if not city or len(state) != 2 or not path_raw:
                    raise SafetyOverlayError(
                        "Each config city entry needs city, 2-letter state, path"
                    )
                path = Path(str(path_raw))
                if not path.is_absolute():
                    path = repo_root / path
                provider = entry.get("provider")
                if provider is not None:
                    provider = str(provider).strip() or None
                jobs.append((f"{city}/{state}", path, city, state, provider))
        except (OSError, SafetyOverlayError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    if args.dry_run:
        for label, path, city, state, provider in jobs:
            try:
                rows, missing = load_safety_rates_file(
                    path,
                    default_city=city or "São Paulo",
                    default_state=state or "SP",
                    default_provider=provider,
                )
            except (OSError, SafetyOverlayError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
            if missing:
                print(f"[dry-run] {label}: skipped_missing path={path}")
                continue
            if city or state:
                filtered = rows
                if city:
                    from core.neighbourhood_assignment import _fold

                    city_fold = _fold(city)
                    filtered = [r for r in filtered if _fold(r.city) == city_fold]
                if state:
                    state_norm = state.strip().upper()
                    filtered = [r for r in filtered if r.state == state_norm]
            else:
                filtered = rows
            print(f"[dry-run] {label}: loaded={len(filtered)} rate row(s)")
            scores = safety_score_from_rates([r.rate_per_100k for r in filtered])
            for rate_row, score in zip(filtered, scores):
                print(
                    f"  - {rate_row.name}: rate={rate_row.rate_per_100k} "
                    f"→ safety_score={score:.4f}"
                )
        print("Dry-run complete; no database writes.")
        return 0

    from infra.db import SessionLocal

    exit_code = 0
    with SessionLocal() as session:
        for label, path, city, state, provider in jobs:
            try:
                result = load_and_apply_safety_rates(
                    session,
                    path,
                    city=city,
                    state=state,
                    default_city=city or "São Paulo",
                    default_state=state or "SP",
                    default_provider=provider,
                )
            except (OSError, SafetyOverlayError) as exc:
                print(f"error ({label}): {exc}", file=sys.stderr)
                exit_code = 1
                continue
            print(
                f"{label}: updated={result.updated} "
                f"unchanged={result.unchanged} "
                f"skipped_unknown={result.skipped_unknown} "
                f"files_skipped_missing={result.files_skipped_missing}"
            )
        if exit_code == 0:
            session.commit()
        else:
            session.rollback()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
