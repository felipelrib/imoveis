"""Unit tests for the delisted-QA sweep helpers (BIN-249)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

_REPO = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO / "scripts" / "dev" / "deactivate_delisted_qa.py"
_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "scrapers"


def _load_mod():
    spec = importlib.util.spec_from_file_location("deactivate_delisted_qa_cli", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


def _fake_client(*, status_code: int, html: str, final_url: str) -> MagicMock:
    client = MagicMock()
    client.get.return_value = SimpleNamespace(
        status_code=status_code, text=html, url=final_url
    )
    return client


BARE = "https://www.quintoandar.com.br/imovel/119842623"


def test_classify_row_delisted_placeholder():
    mod = _load_mod()
    client = _fake_client(
        status_code=200,
        html=_fixture("quintoandar_delisted_placeholder.html"),
        final_url=BARE,
    )
    bucket, reason, final_id = mod.classify_row(client, BARE, "rent")
    assert bucket == "delisted"
    assert reason == "qa_placeholder_shell"


def test_classify_row_live_no_text():
    mod = _load_mod()
    url = "https://www.quintoandar.com.br/imovel/894353786"
    client = _fake_client(
        status_code=200,
        html=_fixture("quintoandar_available.html"),
        final_url=url + "/alugar/apto-3-quartos",
    )
    bucket, _reason, _final_id = mod.classify_row(client, url, "rent")
    assert bucket == "no_text"


def test_classify_row_duplicate_redirect_to_other_id():
    mod = _load_mod()
    url = "https://www.quintoandar.com.br/imovel/111111111"
    client = _fake_client(
        status_code=200,
        html=_fixture("quintoandar_available.html"),
        final_url="https://www.quintoandar.com.br/imovel/894353786/alugar/x",
    )
    bucket, _reason, final_id = mod.classify_row(client, url, "rent")
    assert bucket == "duplicate"
    assert final_id == "894353786"


def test_classify_row_transient_is_unknown():
    mod = _load_mod()
    client = _fake_client(status_code=403, html="", final_url=BARE)
    bucket, _reason, _final_id = mod.classify_row(client, BARE, "rent")
    assert bucket == "unknown"


def test_classify_row_network_error_is_unknown():
    mod = _load_mod()
    client = MagicMock()
    client.get.side_effect = RuntimeError("boom")
    bucket, reason, _final_id = mod.classify_row(client, BARE, "rent")
    assert bucket == "unknown"
    assert reason == "http_error"


def test_run_sweep_dry_run_does_not_deactivate(monkeypatch=None):
    mod = _load_mod()
    session = MagicMock()
    session.execute.return_value.fetchall.return_value = [
        SimpleNamespace(
            listing_id="l1",
            property_id="p1",
            listing_type="rent",
            url=BARE,
        )
    ]
    client = _fake_client(
        status_code=200,
        html=_fixture("quintoandar_delisted_placeholder.html"),
        final_url=BARE,
    )
    called = {"deactivate": 0}

    def _fake_deactivate(_session, _listing_id):
        called["deactivate"] += 1
        return {}

    mod.create_scraper_http_client = MagicMock(return_value=client)
    mod.deactivate_listing_and_maybe_property = _fake_deactivate

    counts = mod.run_sweep(session, apply=False, limit=0)
    assert counts["delisted"] == 1
    assert counts["would_deactivate"] == 1
    assert called["deactivate"] == 0


def test_run_sweep_apply_deactivates():
    mod = _load_mod()
    session = MagicMock()
    session.execute.return_value.fetchall.return_value = [
        SimpleNamespace(
            listing_id="l1",
            property_id="p1",
            listing_type="rent",
            url=BARE,
        )
    ]
    client = _fake_client(
        status_code=200,
        html=_fixture("quintoandar_delisted_placeholder.html"),
        final_url=BARE,
    )
    called = {"deactivate": 0}

    def _fake_deactivate(_session, _listing_id):
        called["deactivate"] += 1
        return {"property_deactivated": True}

    mod.create_scraper_http_client = MagicMock(return_value=client)
    mod.deactivate_listing_and_maybe_property = _fake_deactivate

    counts = mod.run_sweep(session, apply=True, limit=0)
    assert counts["deactivated"] == 1
    assert counts["properties_deactivated"] == 1
    assert called["deactivate"] == 1
