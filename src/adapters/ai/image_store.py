"""Image download, caching, and encoding for the AI/VLM pipeline.

Downloaded images are stored under ``{base_path}/{property_id}/{hash}.jpg``
and de-duplicated by MD5 content hash so repeated scrapes don't waste disk
space or VLM tokens.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import List, Optional

import httpx

from infra.config import get_config
from infra.logging import get_logger

logger = get_logger(__name__)

CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

class ImageStore:
    """Manage local image cache for property photos."""

    def __init__(self, base_path: Optional[str] = None) -> None:
        resolved = base_path or get_config().image_storage_path
        self._base = Path(resolved)
        self._base.mkdir(parents=True, exist_ok=True)
        logger.info("image_store_init", base_path=str(self._base))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def download_images(
        self,
        property_id: str,
        urls: List[str],
        max_images: int = 5,
    ) -> List[str]:
        """Download images from *urls* into local storage.

        Returns a list of local file paths (up to *max_images*).
        Already-downloaded images (same content hash) are skipped.
        """
        prop_dir = self._base / property_id
        prop_dir.mkdir(parents=True, exist_ok=True)

        existing_hashes = self._existing_hashes(prop_dir)
        saved_paths: List[str] = list(self._iter_existing_paths(prop_dir))

        remaining = max_images - len(saved_paths)
        if remaining <= 0:
            logger.info(
                "image_download_skip_max",
                property_id=property_id,
                cached=len(saved_paths),
            )
            return saved_paths[:max_images]

        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            for url in urls:
                if remaining <= 0:
                    break
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    content = resp.content

                    content_hash = hashlib.sha256(content).hexdigest()
                    if content_hash in existing_hashes:
                        logger.debug(
                            "image_download_dedup",
                            property_id=property_id,
                            hash=content_hash,
                        )
                        continue

                    content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
                    ext = CONTENT_TYPE_EXT.get(content_type, ".jpg")
                    dest = prop_dir / f"{content_hash}{ext}"

                    dest.write_bytes(content)
                    existing_hashes.add(content_hash)
                    saved_paths.append(str(dest))
                    remaining -= 1

                    logger.info(
                        "image_downloaded",
                        property_id=property_id,
                        url=url,
                        hash=content_hash,
                        dest=str(dest),
                    )
                except Exception as exc:
                    logger.warning(
                        "image_download_failed",
                        property_id=property_id,
                        url=url,
                        error=str(exc),
                    )

        return saved_paths[:max_images]

    def get_local_paths(self, property_id: str) -> List[str]:
        """Return all cached image paths for a property."""
        prop_dir = self._base / property_id
        if not prop_dir.is_dir():
            return []
        return sorted(str(p) for p in prop_dir.iterdir() if p.is_file())

    @staticmethod
    def encode_base64(file_path: str) -> str:
        """Read a local image file and return its base64 encoding."""
        data = Path(file_path).read_bytes()
        return base64.b64encode(data).decode("utf-8")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _existing_hashes(directory: Path) -> set[str]:
        """Collect content hashes already present in *directory*.

        The hash is encoded in the filename (``{hash}.jpg``).
        """
        hashes: set[str] = set()
        if directory.is_dir():
            for p in directory.iterdir():
                if p.is_file():
                    hashes.add(p.stem)
        return hashes

    @staticmethod
    def _iter_existing_paths(directory: Path) -> List[str]:
        """Return sorted list of existing image paths in *directory*."""
        if not directory.is_dir():
            return []
        return sorted(str(p) for p in directory.iterdir() if p.is_file())
