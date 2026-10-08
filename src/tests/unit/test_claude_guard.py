"""Mutation probe for the Claude Code PreToolUse guard (``.claude/hooks/guard.py``).

The guard is the project's only *enforced* rule set (CLAUDE.md prose is advisory).
Each case here plants the exact command the rule exists to stop and asserts the
guard denies it, plus the benign neighbour it must let through. If a future edit
weakens a pattern, the planted mutation passes and this file goes red.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
GUARD = REPO_ROOT / ".claude" / "hooks" / "guard.py"
SETTINGS = REPO_ROOT / ".claude" / "settings.json"


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location("claude_guard", GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Done:
    def __init__(self, rc: int, out: str = "") -> None:
        self.returncode = rc
        self.stdout = out
        self.stderr = ""


def _fake_toplevel(path: Path):
    """Test double for git toplevel: this repo for anything under it, a dir with scripts/ for fixtures, else None."""
    path = Path(path)
    if str(path).startswith(str(REPO_ROOT)):
        return REPO_ROOT
    return path if (path / "scripts").is_dir() else None


@pytest.fixture
def no_stamp(guard, monkeypatch):
    monkeypatch.setattr(guard.subprocess, "run", lambda *a, **k: _Done(1, "NO VALID STAMP: required tier backend, have none"))
    monkeypatch.setattr(guard, "_git", lambda cwd, *args: "main")
    monkeypatch.setattr(guard, "_toplevel", _fake_toplevel)


@pytest.fixture
def stamped(guard, monkeypatch):
    monkeypatch.setattr(guard.subprocess, "run", lambda *a, **k: _Done(0, "stamp ok"))
    monkeypatch.setattr(guard, "_git", lambda cwd, *args: "main")
    monkeypatch.setattr(guard, "_toplevel", _fake_toplevel)


@pytest.mark.unit
class TestPushGuard:
    @pytest.mark.parametrize(
        "command",
        [
            "git push origin main",
            "git push",
            "git push origin HEAD:main",
            "git -C . push origin main",
            "git -c push.default=current push origin main",
            "cd src && git push origin main",
            "git push origin main && echo done",
        ],
    )
    def test_push_to_main_without_stamp_is_denied(self, guard, no_stamp, command):
        reason = guard.check_bash(command, REPO_ROOT)
        assert reason and "validation stamp" in reason

    @pytest.mark.parametrize("command", ["git push origin main", "git push"])
    def test_push_to_main_with_stamp_is_allowed(self, guard, stamped, command):
        assert guard.check_bash(command, REPO_ROOT) is None

    @pytest.mark.parametrize(
        "command",
        [
            "git push --force origin main",
            "git push -f origin main",
            "git push origin +main",
            "git push --force-with-lease origin feat/x",
        ],
    )
    def test_force_push_is_always_denied(self, guard, stamped, command):
        reason = guard.check_bash(command, REPO_ROOT)
        assert reason and "Force" in reason

    def test_push_to_feature_branch_needs_no_stamp(self, guard, no_stamp):
        assert guard.check_bash("git push origin feat/v0.14-s1.1-thing", REPO_ROOT) is None
        assert guard.check_bash("git push -u origin chore/harness", REPO_ROOT) is None

    def test_push_from_another_repo_checks_that_repo_not_this_one(self, guard, monkeypatch, tmp_path):
        """`cd <other repo> && git push origin main` must run the OTHER repo's stamp check."""
        other = tmp_path / "other"
        (other / "scripts").mkdir(parents=True)
        (other / "scripts" / "validate.py").write_text("# --check-stamp\n", encoding="utf-8")
        seen = {}

        def fake_run(cmd, *a, **k):
            seen["cmd"], seen["cwd"] = cmd, k.get("cwd")
            return _Done(1, "NO VALID STAMP: required tier fast, have none")

        monkeypatch.setattr(guard.subprocess, "run", fake_run)
        monkeypatch.setattr(guard, "_git", lambda cwd, *args: "main")
        monkeypatch.setattr(guard, "_toplevel", _fake_toplevel)
        reason = guard.check_bash(f"cd {other} && git push origin main", REPO_ROOT)
        assert reason and str(other) in reason
        assert Path(seen["cwd"]) == other and str(other / "scripts" / "validate.py") in seen["cmd"][1]

    def test_push_from_a_repo_without_a_stamp_gate_is_not_guarded(self, guard, no_stamp, tmp_path):
        (tmp_path / "scripts").mkdir()
        assert guard.check_bash(f"cd {tmp_path} && git push origin main", REPO_ROOT) is None

    def test_push_outside_any_repo_is_not_guarded(self, guard, no_stamp, tmp_path):
        assert guard.check_bash(f"cd {tmp_path} && git push origin main", REPO_ROOT) is None

    def test_git_commands_other_than_push_pass(self, guard, no_stamp):
        for cmd in ("git status", "git log --oneline -3", "git pull --ff-only origin main", "git fetch origin main"):
            assert guard.check_bash(cmd, REPO_ROOT) is None


@pytest.mark.unit
class TestPrimaryStackGuard:
    @pytest.mark.parametrize(
        "command",
        [
            "docker compose up -d",
            "docker compose --env-file .env.local up -d --build api",
            "docker compose -p imoveis down",
            "docker compose restart worker_ai",
            "docker-compose down -v",
            "docker compose run --rm api alembic upgrade head",
            "docker compose stop && echo ok",
        ],
    )
    def test_primary_lifecycle_commands_are_denied(self, guard, command):
        reason = guard.check_bash(command, REPO_ROOT)
        assert reason and "primary" in reason

    @pytest.mark.parametrize(
        "command",
        [
            "docker compose -f docker-compose.test.yml -p imoveis-test up -d --wait postgres redis",
            "docker compose -f docker-compose.test.yml -p imoveis-test down -v --remove-orphans",
            "docker compose -p imoveis-test-ab12cd port postgres 5432",
            "docker compose ps",
            "docker compose logs api",
            "docker ps",
        ],
    )
    def test_ephemeral_stack_and_read_only_commands_pass(self, guard, command):
        assert guard.check_bash(command, REPO_ROOT) is None

    @pytest.mark.parametrize("command", ["docker system prune -af", "docker volume rm imoveis_postgres_data", "docker volume prune -f"])
    def test_volume_destroying_commands_are_denied(self, guard, command):
        reason = guard.check_bash(command, REPO_ROOT)
        assert reason and "Destructive docker" in reason


@pytest.mark.unit
class TestProtectedFiles:
    @pytest.mark.parametrize("path", [".env.local", r"C:\Workfolder\imoveis\.env.local", "configs/anchors.local.yaml"])
    def test_editing_operator_files_is_denied(self, guard, path):
        assert guard.check_file_edit(path)

    @pytest.mark.parametrize("path", [".env.local.example", "configs/anchors.yaml", "configs/app_config.yaml"])
    def test_committed_config_files_are_editable(self, guard, path):
        assert guard.check_file_edit(path) is None

    @pytest.mark.parametrize(
        "command",
        ["echo API_KEY=x >> .env.local", "sed -i 's/a/b/' .env.local", "cat anchors.yaml | tee configs/anchors.local.yaml"],
    )
    def test_shell_writes_to_operator_files_are_denied(self, guard, command):
        assert guard.check_bash(command, REPO_ROOT)

    def test_reading_operator_files_passes(self, guard):
        assert guard.check_bash("cat .env.local", REPO_ROOT) is None
        assert guard.check_bash("grep -n COMPOSE .env.local", REPO_ROOT) is None


@pytest.mark.unit
class TestWiring:
    def test_settings_register_the_guard_on_pre_tool_use(self):
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        pre = settings["hooks"]["PreToolUse"]
        commands = [h["command"] for entry in pre for h in entry["hooks"]]
        assert any("guard.py" in c for c in commands)
        assert any("Bash" in entry.get("matcher", "") and "Edit" in entry.get("matcher", "") for entry in pre)

    def test_guard_runs_end_to_end_over_stdin(self):
        """The real process contract: payload in, deny JSON out, exit 0."""
        payload = {"tool_name": "Bash", "tool_input": {"command": "docker compose up -d"}, "cwd": str(REPO_ROOT)}
        res = subprocess.run(
            ["python", str(GUARD)] if False else [__import__("sys").executable, str(GUARD)],
            input=json.dumps(payload), capture_output=True, text=True, timeout=60, cwd=str(REPO_ROOT),
        )
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout)
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_guard_is_silent_for_benign_commands(self):
        payload = {"tool_name": "Bash", "tool_input": {"command": "git status"}, "cwd": str(REPO_ROOT)}
        res = subprocess.run(
            [__import__("sys").executable, str(GUARD)], input=json.dumps(payload), capture_output=True, text=True, timeout=60, cwd=str(REPO_ROOT),
        )
        assert res.returncode == 0 and res.stdout.strip() == ""
