"""Image downscaling for the AI/VLM enrich path (BIN-248).

The BIN-242 A/B showed that capping images at 768px longest side matched
full-resolution quality for Gemma *and* fixed Ollama's visual-error rate, while
shrinking payloads (TPM headroom for the free-tier backfill). These helpers are
pure (bytes in / bytes out) so they unit-test without disk or network, and they
are deliberately fail-open: any decode/encode error returns the original bytes
so a single bad image never breaks an enrich run.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Tuple

from infra.logging import get_logger

logger = get_logger(__name__)

# Re-encode the downscaled variant as JPEG at this quality. 85 is visually
# lossless for VLM analysis and keeps files small.
_JPEG_QUALITY = 85


def longest_side(raw: bytes) -> Tuple[int, int]:
    """Return the ``(width, height)`` of a JPEG/PNG byte payload."""
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as img:
        return img.size


def downscale_jpeg(raw: bytes, max_dim: int) -> bytes:
    """Return ``raw`` resized so its longest side is ``max_dim`` px, as JPEG.

    Returns the **original** ``raw`` object unchanged when downscaling is
    disabled (``max_dim <= 0``), the image is already within bounds, or any
    Pillow error occurs — callers rely on identity (``out is raw``) to skip a
    needless re-encode / disk write.
    """
    if max_dim <= 0:
        return raw
    try:
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as img:
            width, height = img.size
            if max(width, height) <= max_dim:
                return raw
            scale = max_dim / float(max(width, height))
            new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
            resized = img.convert("RGB").resize(new_size, Image.LANCZOS)
            out = io.BytesIO()
            resized.save(out, format="JPEG", quality=_JPEG_QUALITY)
            return out.getvalue()
    except Exception as exc:  # noqa: BLE001 - fail open, never break enrich
        logger.warning("image_downscale_failed", error=str(exc), max_dim=max_dim)
        return raw


def variant_path(original: str, max_dim: int) -> Path:
    """Cache path for the downscaled variant next to the original.

    ``…/deadbeef.png`` → ``…/deadbeef.d768.jpg``. The dimension is encoded so a
    later cap change produces a distinct cache file instead of a stale hit.
    """
    p = Path(original)
    return p.with_name(f"{p.stem}.d{max_dim}.jpg")
