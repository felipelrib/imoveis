#!/usr/bin/env python3
"""Re-embed all active properties with the configured embedding model (BIN-73).

Clears existing vectors then enqueues ``embed_property`` for each active row
with title/description (same as ``POST /admin/embeddings/backfill?force=true``).

Usage:
  PYTHONPATH=src python scripts/dev/reembed_properties.py
  PYTHONPATH=src python scripts/dev/reembed_properties.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "src"))

from sqlalchemy import text  # noqa: E402

from adapters.queue.tasks import embed_property  # noqa: E402
from infra.config import get_config  # noqa: E402
from infra.db import SessionLocal  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-embed properties (BIN-73).")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Clear embeddings and enqueue Celery jobs. Default is dry-run.",
    )
    args = parser.parse_args(argv)

    cfg = get_config()
    print(f"embedding_model={cfg.ai.embedding_model}")
    print(f"ollama_url={cfg.ai.ollama_url}")

    with SessionLocal() as session:
        total = session.execute(
            text(
                "SELECT count(*) FROM properties WHERE active = true "
                "AND (COALESCE(title, '') <> '' OR COALESCE(description, '') <> '')"
            )
        ).scalar()
        missing = session.execute(
            text(
                "SELECT count(*) FROM properties WHERE active = true AND embedding IS NULL "
                "AND (COALESCE(title, '') <> '' OR COALESCE(description, '') <> '')"
            )
        ).scalar()
        print(f"active_with_text={total} missing_embedding={missing}")

        if not args.apply:
            print("Dry-run only. Re-run with --apply to clear + enqueue.")
            return 0

        session.execute(text("UPDATE properties SET embedding = NULL"))
        session.commit()
        rows = session.execute(
            text(
                "SELECT id FROM properties WHERE active = true "
                "AND (COALESCE(title, '') <> '' OR COALESCE(description, '') <> '')"
            )
        ).fetchall()
        queued = 0
        for (prop_id,) in rows:
            embed_property.apply_async(args=[str(prop_id)], queue="ai")
            queued += 1
        print(f"Queued {queued} embed_property jobs on queue=ai")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
