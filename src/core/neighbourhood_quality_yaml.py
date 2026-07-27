"""Load curated neighbourhood quality profiles from YAML into PostGIS.

Idempotent update keyed by folded (name, city) + state. Never inserts new
neighbourhoods — unknown names are skipped with a structured log.

Scores are operator judgment (``quality_meta.source = curated``), not ground
truth. Later OSM/transit/risk jobs may overwrite by stamping their own source.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

import yaml
from sqlalchemy.orm import Session

from core.neighbourhood_assignment import _fold
from core.neighbourhood_quality import normalize_quality_score, normalize_risk_flags
from infra.logging import get_logger

logger = get_logger(__name__)

YamlInput = Union[str, Path, Mapping[str, Any]]

CURATED_SOURCE = "curated"
DEFAULT_YAML_PATH = Path(__file__).resolve().parents[2] / "configs" / "neighbourhood_quality.yaml"


@dataclass(frozen=True)
class CuratedProfile:
    name: str
    city: str
    state: str
    amenity_score: Optional[float]
    transit_score: Optional[float]
    access_score: Optional[float]
    safety_score: Optional[float]
    risk_flags: tuple[str, ...]
    notes: Optional[str] = None
    slug: Optional[str] = None


@dataclass(frozen=True)
class LoadResult:
    updated: int = 0
    skipped: int = 0

    @property
    def total(self) -> int:
        return self.updated + self.skipped


class NeighbourhoodQualityYamlError(ValueError):
    """Invalid or incomplete curated neighbourhood quality YAML."""


def _as_mapping(data: YamlInput) -> Mapping[str, Any]:
    if isinstance(data, (str, Path)):
        path = Path(data)
        with path.open(encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh)
        if not isinstance(loaded, Mapping):
            raise NeighbourhoodQualityYamlError("YAML root must be an object")
        return loaded
    return data


def _notes(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_curated_yaml(
    data: YamlInput,
    *,
    default_city: str = "Belo Horizonte",
    default_state: str = "MG",
) -> list[CuratedProfile]:
    """Parse curated quality YAML into profile rows."""
    root = _as_mapping(data)
    defaults = root.get("defaults") or {}
    if defaults is not None and not isinstance(defaults, Mapping):
        raise NeighbourhoodQualityYamlError("defaults must be an object")
    city_default = str(defaults.get("city") or default_city).strip()
    state_default = str(defaults.get("state") or default_state).strip().upper()

    profiles = root.get("profiles")
    if not isinstance(profiles, Sequence) or isinstance(profiles, (str, bytes)):
        raise NeighbourhoodQualityYamlError("profiles must be an array")

    rows: list[CuratedProfile] = []
    for idx, item in enumerate(profiles):
        if not isinstance(item, Mapping):
            raise NeighbourhoodQualityYamlError(f"Profile at index {idx} must be an object")
        name = item.get("name")
        if not name or not str(name).strip():
            raise NeighbourhoodQualityYamlError(f"Profile at index {idx} is missing name")
        city = str(item.get("city") or city_default).strip()
        state = str(item.get("state") or state_default).strip().upper()
        if len(state) != 2:
            raise NeighbourhoodQualityYamlError(
                f"Profile at index {idx} state must be a 2-letter code, got {state!r}"
            )
        slug_raw = item.get("slug")
        slug = str(slug_raw).strip() if slug_raw else None
        rows.append(
            CuratedProfile(
                name=str(name).strip(),
                city=city,
                state=state,
                amenity_score=normalize_quality_score(item.get("amenity_score")),
                transit_score=normalize_quality_score(item.get("transit_score")),
                access_score=normalize_quality_score(item.get("access_score")),
                safety_score=normalize_quality_score(item.get("safety_score")),
                risk_flags=tuple(normalize_risk_flags(item.get("risk_flags"))),
                notes=_notes(item.get("notes")),
                slug=slug or None,
            )
        )
    return rows


def _float_eq(a: Optional[float], b: Optional[float]) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) < 1e-9


def _profile_unchanged(existing: Any, profile: CuratedProfile) -> bool:
    meta = existing.quality_meta if isinstance(existing.quality_meta, dict) else {}
    if meta.get("source") != CURATED_SOURCE:
        return False
    existing_flags = list(existing.risk_flags or [])
    existing_notes = _notes(existing.quality_notes)
    return (
        _float_eq(existing.amenity_score, profile.amenity_score)
        and _float_eq(existing.transit_score, profile.transit_score)
        and _float_eq(existing.access_score, profile.access_score)
        and _float_eq(existing.safety_score, profile.safety_score)
        and existing_flags == list(profile.risk_flags)
        and existing_notes == profile.notes
    )


def _neighbourhood_index(session: Session) -> dict[tuple[str, str, str], Any]:
    from adapters.db.models import Neighborhood

    index: dict[tuple[str, str, str], Any] = {}
    for row in session.query(Neighborhood).all():
        key = (_fold(row.name), _fold(row.city), str(row.state).strip().upper())
        index[key] = row
    return index


def apply_curated_profiles(
    session: Session,
    rows: Sequence[CuratedProfile],
    *,
    refreshed_at: Optional[datetime] = None,
) -> LoadResult:
    """Update existing neighbourhoods from curated profiles. Never inserts."""
    stamp = refreshed_at or datetime.now(timezone.utc)
    refreshed_iso = stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    index = _neighbourhood_index(session)
    updated = skipped = 0

    for profile in rows:
        key = (_fold(profile.name), _fold(profile.city), profile.state)
        existing = index.get(key)
        if existing is None:
            logger.warning(
                "neighbourhood_quality_unknown",
                neighbourhood_name=profile.name,
                city=profile.city,
                state=profile.state,
                slug=profile.slug,
            )
            skipped += 1
            continue

        if _profile_unchanged(existing, profile):
            skipped += 1
            continue

        existing.amenity_score = profile.amenity_score
        existing.transit_score = profile.transit_score
        existing.access_score = profile.access_score
        existing.safety_score = profile.safety_score
        existing.risk_flags = list(profile.risk_flags)
        existing.quality_notes = profile.notes
        existing.quality_meta = {
            "source": CURATED_SOURCE,
            "refreshed_at": refreshed_iso,
        }
        session.flush()
        updated += 1

    return LoadResult(updated=updated, skipped=skipped)


def load_curated_neighbourhood_quality(
    session: Session,
    data: YamlInput,
    *,
    default_city: str = "Belo Horizonte",
    default_state: str = "MG",
) -> LoadResult:
    """Parse + apply in one call."""
    rows = parse_curated_yaml(
        data, default_city=default_city, default_state=default_state
    )
    return apply_curated_profiles(session, rows)
