"""Regression: no dev script may destroy the primary stack's named volumes.

Root cause (v0.13-fu5): ``scripts/stop.sh --volumes`` and
``scripts/clean.sh --volumes`` ran ``docker compose down -v`` against the
PRIMARY project with no confirmation and no TTY check. That wipes
``imoveis_postgres_data`` (the entire scraped + AI-enriched corpus),
``imoveis_image_store`` (every downloaded photo), and ``imoveis_redis_data``
(backfill checkpoints/budget) — days of scraping and multi-day AI enrichment
behind a single mistyped flag.

Both flags were removed and now fail closed. These tests lock that: the
volume-destroying invocation must not come back, and the flag must keep
erroring instead of silently succeeding (a silent no-op would be worse — the
operator would believe data was wiped, or a stale script would "pass").

Deliberately NOT covered here (they are correct and must keep working):
  * ``scripts/agent/test-stack.sh`` — ``down -v`` on the ephemeral
    ``<workspace>-test`` project, asserted != primary. Throwaway by design.
  * ``scripts/agent/teardown.sh`` — ``down -v`` only in its non-primary branch;
    it refuses the primary project outright and always refuses ``--volumes``
    there.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
_STOP = _SCRIPTS / "stop.sh"
_CLEAN = _SCRIPTS / "clean.sh"

# `docker compose down -v` / `--volumes`, ignoring comment lines.
_DOWN_V = re.compile(r"^\s*(?!#).*\bdown\b.*(\s-v\b|--volumes\b)", re.MULTILINE)
# `docker volume rm` / `volume prune` / `system prune --volumes`, non-comment.
_VOLUME_NUKE = re.compile(
    r"^\s*(?!#).*\b(?:volume\s+rm|volume\s+prune|system\s+prune[^\n]*--volumes)\b.*$",
    re.MULTILINE,
)


@pytest.mark.parametrize("script", [_STOP, _CLEAN], ids=["stop.sh", "clean.sh"])
def test_script_never_runs_compose_down_with_volumes(script):
    """The volume-destroying compose invocation must not exist in these scripts."""
    body = script.read_text()
    match = _DOWN_V.search(body)
    assert match is None, (
        f"{script.name} contains a volume-destroying `down -v`: {match.group(0).strip()!r}. "
        "Primary named volumes hold the scraped corpus + enrichment work."
    )


@pytest.mark.parametrize("script", [_STOP, _CLEAN], ids=["stop.sh", "clean.sh"])
def test_script_never_removes_volumes_directly(script):
    """No `docker volume rm` / prune --volumes outside the documented manual path."""
    body = script.read_text()
    for match in _VOLUME_NUKE.finditer(body):
        line = match.group(0)
        # The refusal message quotes the manual procedure for a human to run;
        # it is inside a die "..." string, not an executed command.
        assert "die " in line or "docker volume rm imoveis_" in line, (
            f"{script.name} removes volumes directly: {line.strip()!r}"
        )


@pytest.mark.parametrize("script", [_STOP, _CLEAN], ids=["stop.sh", "clean.sh"])
def test_volumes_flag_is_refused_not_silently_ignored(script):
    """`--volumes` must fail loudly (non-zero) so it can never appear to work."""
    proc = subprocess.run(
        ["bash", str(script), "--volumes"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode != 0, (
        f"{script.name} --volumes exited 0 — it must fail closed, never silently no-op."
    )
    combined = (proc.stdout + proc.stderr).lower()
    assert "removed" in combined or "volumes are never deleted" in combined, (
        f"{script.name} --volumes must explain why it refused; got: {combined[:300]!r}"
    )


def test_clean_all_still_preserves_volumes():
    """`--all` may drop images/cache (rebuildable) but must not imply volume loss."""
    body = _CLEAN.read_text()
    assert "--rmi local" in body, "clean.sh --all should still remove local images"
    assert _DOWN_V.search(body) is None, "clean.sh --all must not remove volumes"
