#!/usr/bin/env python3
"""SessionStart hook: print the facts every session used to be told to go and fetch.

Branch, dirty state, whether HEAD's tree already carries a validation stamp, and
the gate command. Replaces the "first action: git rev-parse" ritual. Stdlib only;
never blocks.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=str(PROJECT_DIR), capture_output=True, text=True, timeout=15).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def main() -> int:
    branch = git("rev-parse", "--abbrev-ref", "HEAD") or "unknown"
    dirty = [line for line in git("status", "--porcelain").splitlines() if line.strip()]
    tree = git("rev-parse", "HEAD^{tree}")
    stamps = sorted(p.name.split(".", 1)[1] for p in (PROJECT_DIR / ".run" / "validated").glob(f"{tree}.*")) if tree else []
    behind = git("rev-list", "--count", "HEAD..origin/main") or "?"
    lines = [
        f"imoveis session: branch={branch} dirty_files={len(dirty)} behind_origin_main={behind}",
        f"validation stamps for HEAD tree: {', '.join(stamps) if stamps else 'none'}",
        "gate: `python scripts/agent/validate.py` (tier from the diff; --tier docs|fast|frontend|backend|full to force)",
        "ship: `python scripts/agent/ship.py` (validate → squash-merge into main → push). Pushes to main are hook-gated on a stamp.",
        "primary docker project `imoveis` is operator-owned: validation uses the ephemeral test stack only.",
    ]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
