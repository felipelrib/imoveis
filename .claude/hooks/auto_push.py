#!/usr/bin/env python3
"""Stop hook: push ``main`` when it is safe and validated, so origin never lags.

Pushes only when ALL hold: not inside a bmad-loop session (BMAD_LOOP_RUN_DIR unset),
cwd is the primary checkout on ``main``, tree clean, ahead of origin/main by >0 and
behind by 0, and HEAD's tree carries a validation stamp (``validate.py --check-stamp``).
Never forces. Stdlib only. Silent when nothing to do.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=str(PROJECT_DIR), capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def main() -> int:
    if os.environ.get("BMAD_LOOP_RUN_DIR"):
        return 0
    if git("rev-parse", "--abbrev-ref", "HEAD") != "main":
        return 0
    if git("status", "--porcelain", "--untracked-files=no"):
        return 0
    subprocess.run(["git", "fetch", "origin", "main", "--quiet"], cwd=str(PROJECT_DIR), capture_output=True, timeout=60)
    counts = git("rev-list", "--left-right", "--count", "origin/main...HEAD")
    try:
        behind, ahead = (int(x) for x in counts.split())
    except ValueError:
        return 0
    if ahead == 0 or behind != 0:
        return 0
    venv = PROJECT_DIR / ".venv" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    py = str(venv) if venv.exists() else sys.executable
    check = subprocess.run([py, str(PROJECT_DIR / "scripts" / "agent" / "validate.py"), "--check-stamp"], cwd=str(PROJECT_DIR), capture_output=True, text=True, timeout=120)
    if check.returncode != 0:
        print(f"auto-push skipped: {check.stdout.strip().splitlines()[-1] if check.stdout.strip() else 'no validation stamp'}")
        return 0
    push = subprocess.run(["git", "push", "origin", "main"], cwd=str(PROJECT_DIR), capture_output=True, text=True, timeout=120)
    print("auto-push: origin/main updated" if push.returncode == 0 else f"auto-push failed: {push.stderr.strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
