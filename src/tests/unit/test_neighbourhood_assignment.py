"""Unit tests for spatial neighbourhood assignment (no PostGIS required)."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from core.neighbourhood_assignment import assign_property_neighbourhood


class TestAssignPropertyNeighbourhoodUnit:
    def test_missing_property_returns_none(self):
        session = MagicMock()
        session.get.return_value = None

        result = assign_property_neighbourhood(session, uuid4())

        assert result is None
        session.execute.assert_not_called()

    def test_null_location_leaves_fk_unchanged(self):
        existing_nid = uuid4()
        prop = MagicMock()
        prop.location = None
        prop.neighborhood_id = existing_nid
        session = MagicMock()
        session.get.return_value = prop

        result = assign_property_neighbourhood(session, uuid4())

        assert result == existing_nid
        session.execute.assert_not_called()
        session.flush.assert_not_called()
        assert prop.neighborhood_id == existing_nid

    def test_api_modules_do_not_import_assigner(self):
        import ast
        from pathlib import Path

        api_root = Path(__file__).resolve().parents[2] / "api"
        offenders = []
        for path in api_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if "neighbourhood_assignment" in node.module:
                        offenders.append(str(path))
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if "neighbourhood_assignment" in alias.name:
                            offenders.append(str(path))
        assert offenders == []
