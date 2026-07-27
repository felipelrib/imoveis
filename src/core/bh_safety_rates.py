"""Build Belo Horizonte safety rates from SEJUSP regional or bairro extracts.

CKAN Crimes Violentos dumps are município/RISP only. BH neighbourhood scores
use PBH regional counts (published via SEJUSP) mapped onto curated bairros, or
operator-supplied bairro extracts (LAI / on-demand Drive sheets).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional, Union

import yaml

from core.neighbourhood_assignment import _fold
from core.safety_overlay import SafetyOverlayError, SafetyRateRow

YamlInput = Union[str, Path, Mapping[str, Any]]

DEFAULT_CITY = "Belo Horizonte"
DEFAULT_STATE = "MG"
DEFAULT_PROVIDER = "sejusp-mg-regional"
DEFAULT_RATE_DEFINITION = "sejusp_violent_crime_count_by_regional_h1_2026"
DEFAULT_GRAIN = "regional"
DEFAULT_ATTRIBUTION = (
    "SEJUSP-MG crimes violentos by PBH regional — registration counts, "
    "not absolute safety. Prefer bairro LAI extracts when available."
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGIONALS_PATH = REPO_ROOT / "configs" / "bh_neighbourhood_regionals.yaml"
DEFAULT_COUNTS_PATH = REPO_ROOT / "configs" / "bh_regional_crime_counts.yaml"


def _load_mapping(data: YamlInput) -> Mapping[str, Any]:
    if isinstance(data, (str, Path)):
        with Path(data).open(encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh)
        if not isinstance(loaded, Mapping):
            raise SafetyOverlayError("YAML root must be an object")
        return loaded
    return data


def parse_neighbourhood_regionals(
    data: YamlInput,
) -> dict[str, str]:
    """Return folded neighbourhood name → regional display name."""
    root = _load_mapping(data)
    raw = root.get("neighbourhoods")
    if not isinstance(raw, Mapping) or not raw:
        raise SafetyOverlayError("neighbourhoods mapping required")
    out: dict[str, str] = {}
    for name, regional in raw.items():
        n = str(name).strip()
        r = str(regional).strip()
        if not n or not r:
            raise SafetyOverlayError("neighbourhood/regional names must be non-empty")
        out[_fold(n)] = r
    return out


def parse_regional_counts(data: YamlInput) -> dict[str, Any]:
    """Parse regional count seed; returns meta + folded regional → count."""
    root = _load_mapping(data)
    raw = root.get("regionals")
    if not isinstance(raw, Mapping) or not raw:
        raise SafetyOverlayError("regionals mapping required")
    counts: dict[str, float] = {}
    for name, value in raw.items():
        regional = str(name).strip()
        if not regional:
            raise SafetyOverlayError("regional name must be non-empty")
        try:
            count = float(value)
        except (TypeError, ValueError) as exc:
            raise SafetyOverlayError(
                f"regional count must be numeric for {regional!r}"
            ) from exc
        if count < 0:
            raise SafetyOverlayError(f"regional count must be >= 0 for {regional!r}")
        counts[_fold(regional)] = count
    # Keep display names for output
    display: dict[str, float] = {
        str(k).strip(): float(v) for k, v in raw.items() if str(k).strip()
    }
    return {
        "counts_folded": counts,
        "counts_display": display,
        "period_start": str(root.get("period_start") or "").strip() or None,
        "period_end": str(root.get("period_end") or "").strip() or None,
        "provider": str(root.get("provider") or DEFAULT_PROVIDER).strip()
        or DEFAULT_PROVIDER,
        "rate_definition": str(
            root.get("rate_definition") or DEFAULT_RATE_DEFINITION
        ).strip()
        or DEFAULT_RATE_DEFINITION,
        "attribution": str(root.get("attribution") or DEFAULT_ATTRIBUTION).strip()
        or DEFAULT_ATTRIBUTION,
    }


def expand_regional_counts_to_rates(
    *,
    neighbourhood_regionals: Mapping[str, str],
    regional_payload: Mapping[str, Any],
    display_names: Optional[Mapping[str, str]] = None,
    city: str = DEFAULT_CITY,
    state: str = DEFAULT_STATE,
) -> list[SafetyRateRow]:
    """Fan regional counts onto each mapped neighbourhood (same count/score)."""
    counts_folded: Mapping[str, float] = regional_payload["counts_folded"]
    rows: list[SafetyRateRow] = []
    for folded_name, regional in neighbourhood_regionals.items():
        count = counts_folded.get(_fold(regional))
        if count is None:
            raise SafetyOverlayError(
                f"no count for regional {regional!r} (neighbourhood {folded_name!r})"
            )
        display = (
            display_names.get(folded_name)
            if display_names is not None
            else folded_name
        )
        # Prefer original casing from display_names map keys when provided.
        rows.append(
            SafetyRateRow(
                name=str(display),
                city=city,
                state=state.strip().upper(),
                rate_per_100k=float(count),
                period_start=regional_payload.get("period_start"),
                period_end=regional_payload.get("period_end"),
                rate_definition=str(regional_payload["rate_definition"]),
                grain=DEFAULT_GRAIN,
                provider=str(regional_payload["provider"]),
                attribution=str(regional_payload["attribution"]),
            )
        )
    if not rows:
        raise SafetyOverlayError("no neighbourhood rates produced")
    return rows


def rates_to_yaml_dict(rows: list[SafetyRateRow]) -> dict[str, Any]:
    """Serialize rate rows to the safety overlay YAML shape."""
    if not rows:
        raise SafetyOverlayError("no rows to serialize")
    first = rows[0]
    return {
        "provider": first.provider,
        "rate_definition": first.rate_definition,
        "grain": first.grain,
        "attribution": first.attribution,
        "period_start": first.period_start,
        "period_end": first.period_end,
        "defaults": {"city": first.city, "state": first.state},
        "rates": [
            {
                "name": r.name,
                "rate_per_100k": r.rate_per_100k,
            }
            for r in rows
        ],
    }


def build_bh_regional_safety_rates(
    *,
    regionals_path: Path = DEFAULT_REGIONALS_PATH,
    counts_path: Path = DEFAULT_COUNTS_PATH,
) -> list[SafetyRateRow]:
    """Load committed configs and expand to neighbourhood rate rows."""
    regionals_root = _load_mapping(regionals_path)
    raw_nhoods = regionals_root.get("neighbourhoods")
    if not isinstance(raw_nhoods, Mapping):
        raise SafetyOverlayError("neighbourhoods mapping required")
    display_names = {_fold(str(k)): str(k).strip() for k in raw_nhoods.keys()}
    neighbourhood_regionals = parse_neighbourhood_regionals(regionals_root)
    payload = parse_regional_counts(counts_path)
    return expand_regional_counts_to_rates(
        neighbourhood_regionals=neighbourhood_regionals,
        regional_payload=payload,
        display_names=display_names,
    )


def aggregate_bairro_extract_csv(
    path: Path,
    *,
    neighbourhood_names: Optional[list[str]] = None,
    bairro_column: str = "bairro",
    count_column: str = "registros",
    city: str = DEFAULT_CITY,
    state: str = DEFAULT_STATE,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    provider: str = "sejusp-mg-bairro-extract",
    rate_definition: str = "sejusp_violent_crime_count_by_bairro",
    attribution: str = (
        "SEJUSP-MG on-demand / LAI bairro extract — registration counts, "
        "not absolute safety."
    ),
) -> list[SafetyRateRow]:
    """Sum counts by folded bairro name from an operator extract CSV."""
    import csv

    if not path.is_file():
        raise SafetyOverlayError(f"bairro extract not found: {path}")

    totals: dict[str, float] = {}
    display: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise SafetyOverlayError("CSV has no header")
        fields = {f.casefold(): f for f in reader.fieldnames}
        bairro_key = fields.get(bairro_column.casefold())
        count_key = fields.get(count_column.casefold())
        if not bairro_key or not count_key:
            raise SafetyOverlayError(
                f"CSV needs columns {bairro_column!r} and {count_column!r}"
            )
        for row in reader:
            name = str(row.get(bairro_key) or "").strip()
            if not name:
                continue
            try:
                count = float(str(row.get(count_key) or "0").replace(",", "."))
            except ValueError as exc:
                raise SafetyOverlayError(
                    f"non-numeric {count_column} for bairro {name!r}"
                ) from exc
            key = _fold(name)
            totals[key] = totals.get(key, 0.0) + count
            display.setdefault(key, name)

    allow = None
    if neighbourhood_names is not None:
        allow = {_fold(n) for n in neighbourhood_names}

    rows: list[SafetyRateRow] = []
    for key, count in sorted(totals.items(), key=lambda kv: display[kv[0]]):
        if allow is not None and key not in allow:
            continue
        rows.append(
            SafetyRateRow(
                name=display[key],
                city=city,
                state=state.strip().upper(),
                rate_per_100k=float(count),
                period_start=period_start,
                period_end=period_end,
                rate_definition=rate_definition,
                grain="bairro",
                provider=provider,
                attribution=attribution,
            )
        )
    if not rows:
        raise SafetyOverlayError("no bairro rates produced from extract")
    return rows
