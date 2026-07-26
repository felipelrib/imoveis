"""Minimum photo-count gate for AI-quality scoring (BIN-78).

Thin galleries produce incomplete VLM condition scores. The required count is
dynamic so it scales with the VLM image budget:

    effective_min = max(floor_min, ceil(max_images_per_property * coverage_ratio))

Default floor 8 targets whole-home coverage (rooms + wet areas + common spaces).
With stock ``max_images_per_property=8`` and ``coverage_ratio=1.0`` the
threshold stays 8 — ingest requires a full analysis set. Raising the VLM
budget automatically raises the bar.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Optional


def effective_min_photos(
    *,
    floor_min: int = 8,
    max_images_per_property: int = 8,
    coverage_ratio: float = 1.0,
) -> int:
    """Return the minimum gallery size for AI-eligible listings."""
    floor = max(0, int(floor_min))
    budget = max(0, int(max_images_per_property))
    ratio = max(0.0, min(1.0, float(coverage_ratio)))
    if budget <= 0 or ratio <= 0.0:
        return floor
    scaled = math.ceil(budget * ratio)
    return max(floor, scaled)


def count_photos(image_urls: Any) -> int:
    """Count non-empty string URLs in a listing gallery."""
    if not image_urls or not isinstance(image_urls, (list, tuple)):
        return 0
    return sum(1 for url in image_urls if isinstance(url, str) and url.strip())


def extract_image_urls(candidate: Any) -> list[str]:
    """Pull image URLs from a candidate, property row, or mapping."""
    if isinstance(candidate, Mapping):
        raw = candidate.get("image_urls")
    else:
        raw = getattr(candidate, "image_urls", None)
    if not isinstance(raw, (list, tuple)):
        return []
    return [u for u in raw if isinstance(u, str) and u.strip()]


def passes_photo_gate(
    candidate: Any,
    *,
    enabled: bool = True,
    floor_min: int = 8,
    max_images_per_property: int = 8,
    coverage_ratio: float = 1.0,
    min_photos: Optional[int] = None,
) -> tuple[bool, Optional[str], int, int]:
    """Return ``(ok, reject_reason, photo_count, required_min)``.

    When disabled, always allows. ``min_photos`` overrides the dynamic formula
    when provided (tests / explicit operator override).
    """
    required = (
        max(0, int(min_photos))
        if min_photos is not None
        else effective_min_photos(
            floor_min=floor_min,
            max_images_per_property=max_images_per_property,
            coverage_ratio=coverage_ratio,
        )
    )
    urls = extract_image_urls(candidate)
    count = count_photos(urls)

    if not enabled:
        return True, None, count, required

    if count < required:
        return False, f"too_few_photos:{count}<{required}", count, required
    return True, None, count, required


def photo_gate_kwargs_from_config(
    scraping_photo_cfg: Any,
    ai_cfg: Any,
) -> dict[str, Any]:
    """Build kwargs for :func:`passes_photo_gate` from AppConfig sections."""
    override = getattr(scraping_photo_cfg, "min_photos", None)
    return {
        "enabled": bool(getattr(scraping_photo_cfg, "enabled", True)),
        "floor_min": int(getattr(scraping_photo_cfg, "floor_min", 8)),
        "max_images_per_property": int(getattr(ai_cfg, "max_images_per_property", 8)),
        "coverage_ratio": float(getattr(scraping_photo_cfg, "coverage_ratio", 1.0)),
        "min_photos": int(override) if override is not None else None,
    }
