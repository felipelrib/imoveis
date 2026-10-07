"""The gate finds Git Bash on Windows whatever the caller's PATH order (scripts/agent/validate.py).

PowerShell sessions put System32 first, so a bare ``bash`` is the WSL launcher: script
tests refused to collect and pre-commit hooks ran in the wrong shell.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATE_PY = REPO_ROOT / "scripts" / "agent" / "validate.py"


@pytest.fixture()
def gate():
    spec = importlib.util.spec_from_file_location("imoveis_validate_gate_host_shell", VALIDATE_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def host(tmp_path, monkeypatch, gate):
    """A fake Windows host: WSL launcher in System32, Git for Windows under Git/."""
    launcher = tmp_path / "System32" / "bash.exe"
    git = tmp_path / "Git" / "cmd" / "git.exe"
    git_bash = tmp_path / "Git" / "bin" / "bash.exe"
    for path in (launcher, git, git_bash):
        path.parent.mkdir(parents=True)
        path.write_text("")
    for var in ("ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(gate, "IS_WINDOWS", True)
    monkeypatch.setenv("PATH", str(launcher.parent))
    found = {"bash": str(launcher), "git": str(git)}
    monkeypatch.setattr(gate.shutil, "which", lambda name: found.get(name))
    return {"launcher": launcher, "git_bash": git_bash, "found": found}


def test_wsl_launcher_is_recognised(gate):
    assert gate.is_wsl_launcher(r"C:\WINDOWS\system32\bash.exe".replace("\\", os.sep))
    assert gate.is_wsl_launcher(os.sep.join(["C:", "Users", "x", "AppData", "Local", "Microsoft", "WindowsApps", "bash.exe"]))
    assert not gate.is_wsl_launcher(os.sep.join(["C:", "Program Files", "Git", "bin", "bash.exe"]))


def test_git_bash_goes_ahead_of_the_wsl_launcher(gate, host):
    gate.prefer_git_bash_on_path()

    first = os.environ["PATH"].split(os.pathsep)[0]
    assert Path(first) == host["git_bash"].parent.resolve()


def test_path_is_untouched_when_bash_is_already_a_real_shell(gate, host):
    host["found"]["bash"] = str(host["git_bash"])
    before = os.environ["PATH"]

    gate.prefer_git_bash_on_path()

    assert os.environ["PATH"] == before


def test_git_bash_is_found_on_path_when_git_is_not_installed_beside_it(gate, host, tmp_path):
    host["found"]["git"] = None
    other = tmp_path / "msys" / "usr" / "bin"
    other.mkdir(parents=True)
    (other / "bash.exe").write_text("")
    os.environ["PATH"] = os.pathsep.join([str(host["launcher"].parent), str(other)])

    assert gate.find_git_bash() == str(other / "bash.exe")


def test_gate_interpreter_leads_path_for_the_python_hooks(gate, monkeypatch, tmp_path):
    """The local pre-commit hooks call a bare ``python``; it must be the gate's own."""
    monkeypatch.setenv("PATH", str(tmp_path))

    gate.gate_python_first_on_path()
    gate.gate_python_first_on_path()

    assert os.environ["PATH"].split(os.pathsep) == [str(Path(gate.PYTHON).parent), str(tmp_path)]


def test_nothing_changes_off_windows(gate, host, monkeypatch):
    monkeypatch.setattr(gate, "IS_WINDOWS", False)
    before = os.environ["PATH"]

    gate.prefer_git_bash_on_path()

    assert os.environ["PATH"] == before
