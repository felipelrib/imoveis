"""Load vendor-agnostic neighbourhood crime rates into safety_score.

Writes ``neighborhoods.safety_score`` (city-relative invert of rate) and nested
``quality_meta["safety"]`` with period / rate definition / attribution.
Large SSP dumps stay out of git — pass local YAML/CSV like risk overlays.
Never invents rates from listing text.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

import yaml
from sqlalchemy.orm import Session

from core.neighbourhood_assignment import _fold
from core.neighbourhood_quality import normalize_quality_score

logger = logging.getLogger(__name__)

RatesInput = Union[str, Path, Mapping[str, Any]]

DEFAULT_PROVIDER = "sejusp-mg-regional"
DEFAULT_RATE_DEFINITION = "sejusp_violent_crime_count_by_regional_h1_2026"
DEFAULT_GRAIN = "regional"
DEFAULT_ATTRIBUTION = (
    "SEJUSP-MG crimes violentos by PBH regional — registration counts, "
    "not absolute safety"
)
DEFAULT_CITY = "Belo Horizonte"
DEFAULT_STATE = "MG"


@dataclass(frozen=True)
class SafetyRateRow:
    name: str
    city: str
    state: str
    rate_per_100k: float
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    rate_definition: str = DEFAULT_RATE_DEFINITION
    grain: str = DEFAULT_GRAIN
    provider: str = DEFAULT_PROVIDER
    attribution: str = DEFAULT_ATTRIBUTION


@dataclass(frozen=True)
class ApplyResult:
    updated: int = 0
    unchanged: int = 0
    skipped_unknown: int = 0
    files_skipped_missing: int = 0

    @property
    def total_rows(self) -> int:
        return self.updated + self.unchanged + self.skipped_unknown


class SafetyOverlayError(ValueError):
    """Invalid or incomplete safety rates file."""


def safety_score_from_rates(rates: Sequence[float]) -> list[float]:
    """City-relative invert: lowest rate → 1.0, highest → 0.0; equal → 0.5."""
    if not rates:
        return []
    lo = min(rates)
    hi = max(rates)
    if hi == lo:
        return [0.5] * len(rates)
    span = hi - lo
    return [1.0 - (float(r) - lo) / span for r in rates]


def merge_quality_meta_safety(
    existing: Any,
    safety_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge nested ``safety`` into ``quality_meta`` without wiping siblings."""
    meta: dict[str, Any]
    if isinstance(existing, Mapping):
        meta = dict(existing)
    else:
        meta = {}
    meta["safety"] = dict(safety_payload)
    return meta


def _as_mapping(data: RatesInput) -> Mapping[str, Any]:
    if isinstance(data, (str, Path)):
        path = Path(data)
        suffix = path.suffix.lower()
        if suffix == ".csv":
            return _csv_to_mapping(path)
        with path.open(encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh)
        if not isinstance(loaded, Mapping):
            raise SafetyOverlayError("Rates YAML root must be an object")
        return loaded
    return data


def _csv_to_mapping(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise SafetyOverlayError("CSV has no header row")
        rates: list[dict[str, Any]] = []
        for row in reader:
            rates.append(dict(row))
    return {"rates": rates}


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _require_rate(value: Any, *, name: str) -> float:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise SafetyOverlayError(f"rate_per_100k required for {name!r}")
    try:
        rate = float(value)
    except (TypeError, ValueError) as exc:
        raise SafetyOverlayError(
            f"rate_per_100k must be numeric for {name!r}"
        ) from exc
    if rate < 0.0:
        raise SafetyOverlayError(f"rate_per_100k must be >= 0 for {name!r}")
    return rate


def parse_safety_rates(
    data: RatesInput,
    *,
    default_city: str = DEFAULT_CITY,
    default_state: str = DEFAULT_STATE,
    default_provider: Optional[str] = None,
) -> list[SafetyRateRow]:
    """Parse YAML/CSV/mapping into rate rows. Does not touch the database."""
    root = _as_mapping(data)
    defaults = root.get("defaults") or {}
    if defaults is None:
        defaults = {}
    if not isinstance(defaults, Mapping):
        raise SafetyOverlayError("defaults must be a mapping")

    city_default = str(defaults.get("city") or default_city).strip()
    state_default = str(defaults.get("state") or default_state).strip().upper()
    if not city_default or len(state_default) != 2:
        raise SafetyOverlayError("defaults need city and 2-letter state")

    provider = str(
        default_provider
        or root.get("provider")
        or DEFAULT_PROVIDER
    ).strip() or DEFAULT_PROVIDER
    rate_definition = str(
        root.get("rate_definition") or DEFAULT_RATE_DEFINITION
    ).strip() or DEFAULT_RATE_DEFINITION
    grain = str(root.get("grain") or DEFAULT_GRAIN).strip() or DEFAULT_GRAIN
    attribution = str(
        root.get("attribution") or DEFAULT_ATTRIBUTION
    ).strip() or DEFAULT_ATTRIBUTION
    period_start = _optional_str(root.get("period_start"))
    period_end = _optional_str(root.get("period_end"))

    raw_rates = root.get("rates")
    if not isinstance(raw_rates, list) or not raw_rates:
        raise SafetyOverlayError("rates must be a non-empty list")

    out: list[SafetyRateRow] = []
    for entry in raw_rates:
        if not isinstance(entry, Mapping):
            raise SafetyOverlayError("each rate entry must be a mapping")
        name = str(entry.get("name") or "").strip()
        if not name:
            raise SafetyOverlayError("each rate entry needs a name")
        city = str(entry.get("city") or city_default).strip()
        state = str(entry.get("state") or state_default).strip().upper()
        if not city or len(state) != 2:
            raise SafetyOverlayError(
                f"rate {name!r} needs city and 2-letter state"
            )
        rate = _require_rate(entry.get("rate_per_100k"), name=name)
        out.append(
            SafetyRateRow(
                name=name,
                city=city,
                state=state,
                rate_per_100k=rate,
                period_start=_optional_str(entry.get("period_start"))
                or period_start,
                period_end=_optional_str(entry.get("period_end")) or period_end,
                rate_definition=str(
                    entry.get("rate_definition") or rate_definition
                ).strip()
                or rate_definition,
                grain=str(entry.get("grain") or grain).strip() or grain,
                provider=str(entry.get("provider") or provider).strip()
                or provider,
                attribution=str(entry.get("attribution") or attribution).strip()
                or attribution,
            )
        )
    return out


def _neighbourhood_index(session: Session) -> dict[tuple[str, str, str], Any]:
    from adapters.db.models import Neighborhood

    index: dict[tuple[str, str, str], Any] = {}
    for row in session.query(Neighborhood).all():
        key = (_fold(row.name), _fold(row.city), str(row.state).strip().upper())
        index[key] = row
    return index


def _safety_payload(
    row: SafetyRateRow,
    *,
    refreshed_at: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provider": row.provider,
        "refreshed_at": refreshed_at,
        "rate_definition": row.rate_definition,
        "rate_per_100k": float(row.rate_per_100k),
        "grain": row.grain,
        "attribution": row.attribution,
    }
    if row.period_start:
        payload["period_start"] = row.period_start
    if row.period_end:
        payload["period_end"] = row.period_end
    return payload


def _row_unchanged(
    existing: Any,
    *,
    safety_score: float,
    meta: Mapping[str, Any],
) -> bool:
    current = normalize_quality_score(getattr(existing, "safety_score", None))
    if current is None or abs(current - safety_score) > 1e-9:
        return False
    return (existing.quality_meta or {}) == dict(meta)


def apply_safety_rates(
    session: Session,
    rows: Sequence[SafetyRateRow],
    *,
    city: Optional[str] = None,
    state: Optional[str] = None,
    refreshed_at: Optional[str] = None,
) -> ApplyResult:
    """Update matched neighbourhoods. Never inserts. Scores are city-relative."""
    when = refreshed_at or datetime.now(timezone.utc).replace(
        microsecond=0
    ).isoformat()

    filtered = list(rows)
    if city is not None:
        city_fold = _fold(city)
        filtered = [r for r in filtered if _fold(r.city) == city_fold]
    if state is not None:
        state_norm = state.strip().upper()
        filtered = [r for r in filtered if r.state == state_norm]

    if not filtered:
        return ApplyResult()

    # Relative scores within each (city, state) group in this batch.
    groups: dict[tuple[str, str], list[SafetyRateRow]] = {}
    for row in filtered:
        key = (_fold(row.city), row.state)
        groups.setdefault(key, []).append(row)

    score_by_key: dict[tuple[str, str, str], float] = {}
    for group_rows in groups.values():
        scores = safety_score_from_rates([r.rate_per_100k for r in group_rows])
        for rate_row, score in zip(group_rows, scores):
            score_by_key[
                (_fold(rate_row.name), _fold(rate_row.city), rate_row.state)
            ] = score

    index = _neighbourhood_index(session)
    updated = unchanged = skipped_unknown = 0

    for rate_row in filtered:
        key = (_fold(rate_row.name), _fold(rate_row.city), rate_row.state)
        existing = index.get(key)
        if existing is None:
            logger.warning(
                "safety_overlay_unknown neighbourhood_name=%s city=%s state=%s",
                rate_row.name,
                rate_row.city,
                rate_row.state,
            )
            skipped_unknown += 1
            continue

        score = score_by_key[key]
        meta = merge_quality_meta_safety(
            existing.quality_meta,
            _safety_payload(rate_row, refreshed_at=when),
        )
        if _row_unchanged(existing, safety_score=score, meta=meta):
            unchanged += 1
            continue

        # Only touch safety_score + quality_meta — never amenity/transit/access.
        existing.safety_score = score
        existing.quality_meta = meta
        session.flush()
        updated += 1

    return ApplyResult(
        updated=updated,
        unchanged=unchanged,
        skipped_unknown=skipped_unknown,
    )


def load_safety_rates_file(
    path: Path,
    *,
    default_city: str = DEFAULT_CITY,
    default_state: str = DEFAULT_STATE,
    default_provider: Optional[str] = None,
) -> tuple[list[SafetyRateRow], bool]:
    """Load one rates file. Returns (rows, missing). Missing → empty + True."""
    if not path.is_file():
        logger.warning("skipping missing safety rates path=%s", path)
        return [], True
    rows = parse_safety_rates(
        path,
        default_city=default_city,
        default_state=default_state,
        default_provider=default_provider,
    )
    return rows, False


def load_and_apply_safety_rates(
    session: Session,
    path: Path,
    *,
    city: Optional[str] = None,
    state: Optional[str] = None,
    default_city: str = DEFAULT_CITY,
    default_state: str = DEFAULT_STATE,
    default_provider: Optional[str] = None,
    refreshed_at: Optional[str] = None,
) -> ApplyResult:
    """Load a rates file (skip if missing) then apply."""
    rows, missing = load_safety_rates_file(
        path,
        default_city=default_city,
        default_state=default_state,
        default_provider=default_provider,
    )
    if missing:
        return ApplyResult(files_skipped_missing=1)
    result = apply_safety_rates(
        session,
        rows,
        city=city,
        state=state,
        refreshed_at=refreshed_at,
    )
    return ApplyResult(
        updated=result.updated,
        unchanged=result.unchanged,
        skipped_unknown=result.skipped_unknown,
        files_skipped_missing=0,
    )
