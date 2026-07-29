"""Import-direction lock: src/core must never import from src/api (BIN-134).

``src/core`` is the pure business-logic layer; ``src/api`` is the FastAPI
presentation layer sitting above core/adapters (see CLAUDE.md's repository
map). A core -> api import inverts that architecture and, since api already
imports from core, is one hop from a real circular import. This test walks
every module under src/core and fails if any of them import anything from
the api package, so a future refactor can't silently reintroduce the
violation fixed in BIN-134 (src/core/top_deals_digest.py used to import
LIST_SELECT_COLUMNS / map_property_list_item from api.property_projection;
that shared row-mapping now lives in src/core/property_projection.py).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator

import pytest

CORE_DIR = Path(__file__).resolve().parents[2] / "core"


def _core_modules() -> Iterator[Path]:
    yield from sorted(CORE_DIR.rglob("*.py"))


def _api_imports(path: Path) -> list[str]:
    """Return dotted names imported from the api package, if any."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "api" or alias.name.startswith("api."):
                    offenders.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            # node.level > 0 means a relative import (e.g. "from . import x")
            # which can never resolve to the top-level api package.
            if node.level == 0 and node.module and (
                node.module == "api" or node.module.startswith("api.")
            ):
                offenders.append(node.module)
    return offenders


@pytest.mark.unit
@pytest.mark.parametrize("module_path", list(_core_modules()), ids=lambda p: str(p.relative_to(CORE_DIR)))
def test_core_module_does_not_import_api(module_path: Path):
    offenders = _api_imports(module_path)
    assert not offenders, (
        f"{module_path.relative_to(CORE_DIR)} imports from src.api ({offenders}); "
        "src/core is the business-logic layer and must not depend on the "
        "src/api presentation layer — move shared logic into src/core instead."
    )


def test_core_modules_were_discovered():
    """Guard against the glob silently matching nothing (e.g. path drift)."""
    assert list(_core_modules()), f"expected .py files under {CORE_DIR}"
