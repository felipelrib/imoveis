"""Intersect neighbourhood polygons with vendor-agnostic risk GeoJSON overlays.

Writes managed ``risk_flags`` (``flood_zone``, ``industrial_adjacent``) and
optional severity under ``quality_meta["risk"]``. Large municipal dumps stay
out of git — pass local paths like neighbourhood GeoJSON (feature 28).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.geometry.base import BaseGeometry
from sqlalchemy.orm import Session

from core.neighbourhood_quality import normalize_risk_flags

logger = logging.getLogger(__name__)

GeoJsonInput = Union[str, Path, Mapping[str, Any]]

MANAGED_RISK_FLAGS = frozenset({"flood_zone", "industrial_adjacent"})
_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}


@dataclass(frozen=True)
class RiskFeature:
    risk_type: str
    polygon: Polygon
    severity: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None


@dataclass(frozen=True)
class RiskOverlayLayer:
    path: Path
    risk_type: Optional[str] = None


@dataclass(frozen=True)
class ApplyResult:
    updated: int = 0
    unchanged: int = 0
    skipped_no_geometry: int = 0
    layers_loaded: int = 0
    layers_skipped_missing: int = 0

    @property
    def total_rows(self) -> int:
        return self.updated + self.unchanged + self.skipped_no_geometry


class RiskOverlayError(ValueError):
    """Invalid or incomplete risk overlay GeoJSON."""


def normalize_severity(value: Any) -> Optional[str]:
    """Map label or numeric ``[0,1]`` severity to ``low``/``medium``/``high``."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        score = float(value)
        if score < 0.0 or score > 1.0:
            return None
        if score >= 2.0 / 3.0:
            return "high"
        if score >= 1.0 / 3.0:
            return "medium"
        return "low"
    text = str(value).strip().lower()
    if text in _SEVERITY_RANK:
        return text
    return None


def max_severity(values: Sequence[Optional[str]]) -> Optional[str]:
    """Return the highest known severity label, or ``None`` if none present."""
    best: Optional[str] = None
    best_rank = 0
    for value in values:
        label = normalize_severity(value)
        if label is None:
            continue
        rank = _SEVERITY_RANK[label]
        if rank > best_rank:
            best = label
            best_rank = rank
    return best


def _as_mapping(data: GeoJsonInput) -> Mapping[str, Any]:
    if isinstance(data, (str, Path)):
        path = Path(data)
        with path.open(encoding="utf-8") as fh:
            loaded = json.load(fh)
        if not isinstance(loaded, Mapping):
            raise RiskOverlayError("GeoJSON root must be an object")
        return loaded
    return data


def _polygon_from_geometry(geom: BaseGeometry) -> Polygon:
    if isinstance(geom, Polygon):
        poly = geom
    elif isinstance(geom, MultiPolygon):
        if geom.is_empty or len(geom.geoms) == 0:
            raise RiskOverlayError("MultiPolygon is empty")
        poly = max(geom.geoms, key=lambda g: g.area)
    else:
        raise RiskOverlayError(
            f"Unsupported geometry type {geom.geom_type!r}; expected Polygon or MultiPolygon"
        )

    if poly.is_empty:
        raise RiskOverlayError("Polygon is empty")
    if not poly.is_valid:
        poly = poly.buffer(0)
        if not isinstance(poly, Polygon) or poly.is_empty or not poly.is_valid:
            raise RiskOverlayError("Polygon is not valid")
    coords = list(poly.exterior.coords)
    if len(coords) < 4:
        raise RiskOverlayError("Polygon exterior ring needs at least 4 positions")
    if coords[0] != coords[-1]:
        coords.append(coords[0])
        poly = Polygon(coords, [list(r.coords) for r in poly.interiors])
    return poly


def parse_risk_feature_collection(
    data: GeoJsonInput,
    *,
    default_risk_type: Optional[str] = None,
    default_city: Optional[str] = None,
    default_state: Optional[str] = None,
) -> list[RiskFeature]:
    """Parse a risk FeatureCollection into intersecting polygons."""
    root = _as_mapping(data)
    if root.get("type") != "FeatureCollection":
        raise RiskOverlayError("Root type must be FeatureCollection")
    features = root.get("features")
    if not isinstance(features, Sequence) or isinstance(features, (str, bytes)):
        raise RiskOverlayError("features must be an array")

    if default_risk_type is not None and default_risk_type not in MANAGED_RISK_FLAGS:
        raise RiskOverlayError(
            f"Unsupported risk_type {default_risk_type!r}; "
            f"expected one of {sorted(MANAGED_RISK_FLAGS)}"
        )

    rows: list[RiskFeature] = []
    for idx, feature in enumerate(features):
        if not isinstance(feature, Mapping):
            raise RiskOverlayError(f"Feature at index {idx} must be an object")
        if feature.get("type") != "Feature":
            raise RiskOverlayError(f"Feature at index {idx} type must be Feature")
        props = feature.get("properties") or {}
        if not isinstance(props, Mapping):
            raise RiskOverlayError(f"Feature at index {idx} properties must be an object")

        raw_type = props.get("risk_type") or default_risk_type
        if not raw_type or not str(raw_type).strip():
            raise RiskOverlayError(
                f"Feature at index {idx} is missing properties.risk_type"
            )
        risk_type = str(raw_type).strip()
        if risk_type not in MANAGED_RISK_FLAGS:
            raise RiskOverlayError(
                f"Unsupported risk_type {risk_type!r}; "
                f"expected one of {sorted(MANAGED_RISK_FLAGS)}"
            )

        city = props.get("city") or default_city
        state = props.get("state") or default_state
        if city is not None:
            city = str(city).strip() or None
        if state is not None:
            state = str(state).strip().upper() or None
            if state is not None and len(state) != 2:
                raise RiskOverlayError(
                    f"Feature at index {idx} state must be a 2-letter code, got {state!r}"
                )

        geom_raw = feature.get("geometry")
        if not geom_raw:
            raise RiskOverlayError(f"Feature at index {idx} is missing geometry")
        try:
            geom = shape(geom_raw)
        except Exception as exc:  # shapely raises assorted errors
            raise RiskOverlayError(
                f"Feature at index {idx} has invalid geometry: {exc}"
            ) from exc

        rows.append(
            RiskFeature(
                risk_type=risk_type,
                polygon=_polygon_from_geometry(geom),
                severity=normalize_severity(props.get("severity")),
                city=city,
                state=state,
            )
        )
    return rows


def flags_for_neighbourhood(
    nhood_poly: BaseGeometry,
    risk_features: Sequence[RiskFeature],
) -> tuple[list[str], dict[str, str]]:
    """Return managed risk flags and max severity map for one neighbourhood."""
    if nhood_poly is None or nhood_poly.is_empty:
        return [], {}

    by_type: dict[str, list[Optional[str]]] = {}
    for feature in risk_features:
        if feature.risk_type not in MANAGED_RISK_FLAGS:
            continue
        try:
            if not nhood_poly.intersects(feature.polygon):
                continue
        except Exception:  # pragma: no cover — degenerate geometries
            continue
        by_type.setdefault(feature.risk_type, []).append(feature.severity)

    flags = sorted(by_type.keys())
    severity = {
        risk_type: sev
        for risk_type, values in by_type.items()
        if (sev := max_severity(values)) is not None
    }
    return flags, severity


def merge_risk_flags(
    existing: Any,
    new_managed: Sequence[str],
    *,
    layers_applied: Sequence[str],
) -> list[str]:
    """Replace managed flags only for applied layers; preserve the rest."""
    existing_flags = normalize_risk_flags(existing)
    applied = set(layers_applied) & MANAGED_RISK_FLAGS
    preserved = [
        flag
        for flag in existing_flags
        if flag not in MANAGED_RISK_FLAGS or flag not in applied
    ]
    managed = [flag for flag in new_managed if flag in applied]
    out: list[str] = []
    seen: set[str] = set()
    for flag in preserved + sorted(set(managed)):
        if flag not in seen:
            seen.add(flag)
            out.append(flag)
    return out


def merge_quality_meta_risk(
    existing: Any,
    *,
    severity: Mapping[str, str],
    layers_applied: Sequence[str],
    refreshed_at: Optional[str] = None,
) -> dict[str, Any]:
    """Merge ``quality_meta`` keeping non-risk keys; overwrite ``risk``."""
    meta: dict[str, Any]
    if isinstance(existing, dict):
        meta = dict(existing)
    else:
        meta = {}
    when = refreshed_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    meta["risk"] = {
        "provider": "geojson-overlay",
        "refreshed_at": when,
        "severity": dict(severity),
        "layers_applied": sorted(set(layers_applied)),
    }
    return meta


def load_risk_layers(
    layers: Sequence[RiskOverlayLayer],
    *,
    default_city: Optional[str] = None,
    default_state: Optional[str] = None,
) -> tuple[list[RiskFeature], int]:
    """Load risk features from layer paths; missing files are skipped (logged)."""
    features: list[RiskFeature] = []
    skipped = 0
    for layer in layers:
        path = Path(layer.path)
        if not path.is_file():
            logger.warning(
                "skipping missing risk layer path=%s risk_type=%s",
                path,
                layer.risk_type,
            )
            skipped += 1
            continue
        features.extend(
            parse_risk_feature_collection(
                path,
                default_risk_type=layer.risk_type,
                default_city=default_city,
                default_state=default_state,
            )
        )
    return features, skipped


def apply_risk_overlays(
    session: Session,
    risk_features: Sequence[RiskFeature],
    *,
    city: str,
    state: str,
    layers_applied: Optional[Sequence[str]] = None,
    refreshed_at: Optional[str] = None,
) -> ApplyResult:
    """Update neighbourhood ``risk_flags`` / ``quality_meta`` for one city."""
    from geoalchemy2.shape import to_shape

    from adapters.db.models import Neighborhood

    if layers_applied is None:
        applied = sorted({f.risk_type for f in risk_features} & MANAGED_RISK_FLAGS)
    else:
        applied = sorted(set(layers_applied) & MANAGED_RISK_FLAGS)

    state_norm = state.strip().upper()
    city_norm = city.strip()
    rows = (
        session.query(Neighborhood)
        .filter_by(city=city_norm, state=state_norm)
        .all()
    )

    updated = unchanged = skipped_no_geometry = 0
    for row in rows:
        if row.geometry is None:
            skipped_no_geometry += 1
            continue
        nhood_poly = to_shape(row.geometry)
        new_flags, severity = flags_for_neighbourhood(nhood_poly, risk_features)
        merged_flags = merge_risk_flags(
            row.risk_flags, new_flags, layers_applied=applied
        )
        # Only keep severity for flags that remain after merge
        severity_kept = {
            k: v for k, v in severity.items() if k in merged_flags
        }
        merged_meta = merge_quality_meta_risk(
            row.quality_meta,
            severity=severity_kept,
            layers_applied=applied,
            refreshed_at=refreshed_at,
        )

        same_flags = normalize_risk_flags(row.risk_flags) == merged_flags
        same_meta = (row.quality_meta or {}) == merged_meta
        if same_flags and same_meta:
            unchanged += 1
            continue

        row.risk_flags = merged_flags
        row.quality_meta = merged_meta
        session.flush()
        updated += 1

    return ApplyResult(
        updated=updated,
        unchanged=unchanged,
        skipped_no_geometry=skipped_no_geometry,
        layers_loaded=len(applied),
        layers_skipped_missing=0,
    )


def load_and_apply_risk_overlays(
    session: Session,
    layers: Sequence[RiskOverlayLayer],
    *,
    city: str,
    state: str,
    refreshed_at: Optional[str] = None,
) -> ApplyResult:
    """Load layers (skip missing) then apply intersections for ``city``/``state``."""
    features, skipped = load_risk_layers(
        layers, default_city=city, default_state=state
    )
    # layers_applied = types we *attempted* that existed; if all missing, applied empty
    attempted_types = [
        layer.risk_type
        for layer in layers
        if layer.risk_type and Path(layer.path).is_file()
    ]
    from_features = sorted({f.risk_type for f in features} & MANAGED_RISK_FLAGS)
    applied = sorted(set(attempted_types) | set(from_features))

    if not features and skipped == len(list(layers)):
        logger.warning(
            "no risk layers loaded for city=%s state=%s (all paths missing); "
            "leaving neighbourhood risk_flags unchanged",
            city,
            state,
        )
        return ApplyResult(
            updated=0,
            unchanged=0,
            skipped_no_geometry=0,
            layers_loaded=0,
            layers_skipped_missing=skipped,
        )

    result = apply_risk_overlays(
        session,
        features,
        city=city,
        state=state,
        layers_applied=applied,
        refreshed_at=refreshed_at,
    )
    return ApplyResult(
        updated=result.updated,
        unchanged=result.unchanged,
        skipped_no_geometry=result.skipped_no_geometry,
        layers_loaded=result.layers_loaded,
        layers_skipped_missing=skipped,
    )
