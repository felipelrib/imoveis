"""Integration: the read-only schema check of ``scripts/start.sh`` on PostgreSQL.

``start.sh`` pipes a small Python program into the ``api`` container of the
primary compose project and reports what it prints (DW-32). The unit tests run
that program against SQLite only, so its PostgreSQL path (``connect_timeout``,
the driver, ``has_table`` on a real catalogue) had never executed. Broken, it
fails toward a wrong report on every start: "schema state is unknown" for a
database that is at head.

This runs the program verbatim against the gate's ephemeral PostGIS database,
which ``validate.py`` migrates to head before the integration suite.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from tests.db_isolation import assert_wipe_safe_database_url

_REPO = Path(__file__).resolve().parents[3]


def _schema_check_program() -> str:
    """The Python program start.sh pipes into the api container, verbatim."""
    script = (_REPO / "scripts" / "start.sh").read_text(encoding="utf-8")
    body = script[script.index("report_primary_schema_state() {") :]
    start = body.index("<<'PY'\n") + len("<<'PY'\n")
    return body[start : body.index("\nPY\n", start) + 1]


def _version_rows(url: str) -> list[str]:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
    finally:
        engine.dispose()
    return sorted(row[0] for row in rows)


def test_the_schema_check_answers_current_on_a_migrated_postgres():
    url = os.environ.get("DATABASE_URL")
    if not url or not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not a PostgreSQL URL — run through scripts/agent/validate.py")
    assert_wipe_safe_database_url(url)  # never the primary, even though the check only reads

    before = _version_rows(url)
    assert before, "the gate migrates the test database before the integration suite"

    completed = subprocess.run(
        [sys.executable, "-"],
        input=_schema_check_program(),
        cwd=_REPO,  # alembic.ini and the migration scripts, as in the api image
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "current"
    assert _version_rows(url) == before
