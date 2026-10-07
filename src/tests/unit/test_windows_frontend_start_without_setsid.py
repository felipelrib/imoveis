"""Regression: ``start_frontend_dev`` must start Vite on a host without ``setsid``.

Root cause (2026-10-07): ``scripts/lib.sh`` launched the dev server as
``setsid npm run dev`` unconditionally. Git Bash on Windows ships no ``setsid``,
so the background job died with ``setsid: command not found`` and
``scripts/start.sh`` brought up the backend only ("Frontend exited early").

The test makes ``setsid`` unavailable on every platform by overriding the
``_have_setsid`` probe (and making any stray ``setsid`` call fail the way the
missing binary does), stubs ``npm`` / ``curl``, and asserts the server is
reported healthy.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.shell_helpers import BASH, bash_path

pytestmark = [pytest.mark.unit, pytest.mark.harness]

_LIB = Path(__file__).resolve().parents[3] / "scripts" / "lib.sh"

_SCRIPT = r"""
source "$1"
REPO_ROOT="$2"
RUN_DIR="$REPO_ROOT/.run"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"
FRONTEND_LOG_FILE="$RUN_DIR/frontend.log"
_have_setsid() { return 1; }
setsid() { echo "setsid: command not found" >&2; return 127; }
npm() { sleep 20; }
curl() { return 0; }
start_frontend_dev
rc=$?
pid="$(tr -d '[:space:]' < "$FRONTEND_PID_FILE" 2>/dev/null || true)"
[ -n "$pid" ] && kill "$pid" 2>/dev/null
cat "$FRONTEND_LOG_FILE" 2>/dev/null
exit $rc
"""


def test_start_frontend_dev_works_without_setsid(tmp_path):
    (tmp_path / "frontend" / "node_modules").mkdir(parents=True)

    result = subprocess.run(
        [BASH, "-c", _SCRIPT, "start-frontend", bash_path(_LIB), bash_path(tmp_path)],
        capture_output=True,
        text=True,
        timeout=60,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "command not found" not in output, output
    assert "Frontend healthy" in output, output
    assert "exited early" not in output, output
