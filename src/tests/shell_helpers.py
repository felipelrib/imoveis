"""Resolve the actual host shell before Windows CreateProcess searches System32."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def _bash_executable() -> str:
    candidate = shutil.which("bash")
    if not candidate:
        raise RuntimeError("Bash is required; run tests through scripts/agent/validate.sh")
    if os.name == "nt" and Path(candidate).parent.name.lower() == "system32":
        raise RuntimeError("Use Git Bash for the Windows validation gate, not the WSL bash launcher")
    return candidate


BASH = _bash_executable()


def bash_path(path: str | Path) -> str:
    """Use the shell's canonical path view, including its /tmp mount on Windows."""
    if os.name != "nt":
        return str(path)
    result = subprocess.run(
        [BASH, "-c", 'cygpath -u -- "$1"', "bash-path", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def host_path(path: str) -> Path:
    if os.name != "nt":
        return Path(path)
    result = subprocess.run(
        [BASH, "-c", 'cygpath -m -- "$1"', "host-path", path],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip())
