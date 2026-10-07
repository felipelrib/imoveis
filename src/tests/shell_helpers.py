"""Resolve the actual host shell before Windows CreateProcess searches System32."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

_VALIDATE_PY = Path(__file__).resolve().parents[2] / "scripts" / "agent" / "validate.py"


def _gate():
    spec = importlib.util.spec_from_file_location("imoveis_validate_gate_shell", _VALIDATE_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bash_executable() -> str:
    candidate = shutil.which("bash")
    if os.name == "nt":
        gate = _gate()
        # A bare ``bash`` is the WSL launcher when System32 precedes Git on PATH
        # (PowerShell sessions); find Git Bash from git itself instead of refusing.
        if not candidate or gate.is_wsl_launcher(candidate):
            candidate = gate.find_git_bash()
        if not candidate:
            raise RuntimeError("Git Bash not found; install Git for Windows (the WSL bash launcher cannot run the gate)")
    if not candidate:
        raise RuntimeError("Bash is required; run tests through scripts/agent/validate.py")
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
