"""Unit tests for description backfill helpers (BIN-105)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_REPO = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO / "scripts" / "dev" / "backfill_listing_descriptions.py"


def _load_mod():
    spec = importlib.util.spec_from_file_location(
        "backfill_listing_descriptions_cli", _SCRIPT
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_select_empty_description_rows_builds_query():
    mod = _load_mod()
    session = MagicMock()
    session.execute.return_value.fetchall.return_value = [
        SimpleNamespace(
            property_id="p1",
            platform="quintoandar",
            platform_id="1",
            url="https://example.test/1",
        )
    ]
    rows = mod.select_empty_description_rows(session, platform="quintoandar", limit=10)
    assert len(rows) == 1
    session.execute.assert_called_once()
    sql = str(session.execute.call_args[0][0])
    assert "COALESCE(TRIM(p.description), '') = ''" in sql
    assert "p.platform = :platform" in sql
    assert "LIMIT :limit" in sql


def test_run_backfill_dry_run_does_not_write():
    mod = _load_mod()
    session = MagicMock()
    row = SimpleNamespace(
        property_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        platform="olx",
        platform_id="123",
        url="https://www.olx.com.br/detalhes/123",
    )
    scraper = MagicMock()
    scraper.fetch_description.return_value = "Full OLX body text here"

    with patch.object(
        mod, "select_empty_description_rows", return_value=[row]
    ):
        counts = mod.run_backfill(
            session,
            apply=False,
            platform="olx",
            limit=1,
            scrapers={"olx": scraper},
        )

    assert counts["candidates"] == 1
    assert counts["would_update"] == 1
    assert "updated" not in counts
    session.commit.assert_not_called()


def test_run_backfill_apply_updates_and_enqueues():
    mod = _load_mod()
    session = MagicMock()
    row = SimpleNamespace(
        property_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        platform="quintoandar",
        platform_id="895",
        url="https://www.quintoandar.com.br/imovel/895",
    )
    scraper = MagicMock()
    scraper.fetch_description.return_value = "Remarks from detail"

    with patch.object(mod, "select_empty_description_rows", return_value=[row]):
        with patch.object(mod, "enqueue_embed") as enqueue:
            counts = mod.run_backfill(
                session,
                apply=True,
                platform="quintoandar",
                limit=1,
                scrapers={"quintoandar": scraper},
            )

    assert counts["updated"] == 1
    assert counts["embed_enqueued"] == 1
    enqueue.assert_called_once()
    session.commit.assert_called()


def test_apply_description_executes_update():
    mod = _load_mod()
    session = MagicMock()
    mod.apply_description(
        session,
        property_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        description="x",
    )
    session.execute.assert_called_once()
