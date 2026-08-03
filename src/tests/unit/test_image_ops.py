"""Unit tests for image downscaling helpers (BIN-248).

Pure byte-in/byte-out; no network or DB. The downscale step must never raise
into the enrich hot path — a corrupt/undecodable image returns the original
bytes so the VLM call still proceeds (and the model handles the fallout).
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from adapters.ai.image_ops import (  # noqa: E402
    downscale_jpeg,
    longest_side,
    variant_path,
)

pytestmark = pytest.mark.unit


def _jpeg_bytes(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (120, 90, 200)).save(buf, format="JPEG")
    return buf.getvalue()


def test_downscale_landscape_caps_longest_side() -> None:
    raw = _jpeg_bytes(2000, 1000)
    out = downscale_jpeg(raw, max_dim=768)
    w, h = longest_side(out)
    assert max(w, h) == 768
    # Aspect ratio preserved (2:1 → 768x384).
    assert (w, h) == (768, 384)


def test_downscale_portrait_caps_longest_side() -> None:
    raw = _jpeg_bytes(1000, 3000)
    out = downscale_jpeg(raw, max_dim=768)
    w, h = longest_side(out)
    assert max(w, h) == 768
    assert (w, h) == (256, 768)


def test_already_small_returns_unchanged_bytes() -> None:
    raw = _jpeg_bytes(400, 300)
    out = downscale_jpeg(raw, max_dim=768)
    # No re-encode when already within bounds — identical bytes.
    assert out is raw


def test_max_dim_zero_disables_downscaling() -> None:
    raw = _jpeg_bytes(2000, 1000)
    assert downscale_jpeg(raw, max_dim=0) is raw
    assert downscale_jpeg(raw, max_dim=-5) is raw


def test_corrupt_bytes_fall_back_to_original() -> None:
    raw = b"not a real image"
    # Must not raise — returns input unchanged.
    assert downscale_jpeg(raw, max_dim=768) is raw


def test_variant_path_encodes_dimension() -> None:
    p = variant_path("/data/images/abc/deadbeef.png", 768)
    assert p == Path("/data/images/abc/deadbeef.d768.jpg")
    # Different cap → different cache file.
    assert variant_path("/data/images/abc/deadbeef.png", 512) == Path(
        "/data/images/abc/deadbeef.d512.jpg"
    )
