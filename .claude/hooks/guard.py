#!/usr/bin/env python3
"""PreToolUse guard — the project's only enforced rules. Stdlib only.

Denies, in every permission mode (including bypassPermissions):

* ``git push`` to ``main`` unless HEAD's tree carries a validation stamp for the
  tier the diff requires (``scripts/agent/validate.py --check-stamp``);
* any force push (``--force``, ``-f``, ``+refspec``, ``--force-with-lease``);
* ``docker compose`` lifecycle commands against the primary project ``imoveis``
  (anything not explicitly scoped to ``docker-compose.test.yml`` / a ``*-test*``
  project), ``docker system prune``, ``docker volume rm|prune``, ``down -v``;
* edits to ``.env.local`` and ``configs/anchors.local.yaml`` (operator-owned
  personal/secret files) through Edit/Write or shell redirection.

Everything else passes through to the normal permission flow (exit 0, no output).
Reads the hook payload from stdin; emits a JSON ``deny`` decision on stdout.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
PRIMARY_PROJECT = "imoveis"
PROTECTED_FILES = (".env.local", "configs/anchors.local.yaml", "anchors.local.yaml")

_GIT_PUSH_RE = re.compile(r"(?:^|[;&|]\s*|\$\(\s*)git(?:\s+-[cC]\s+\S+|\s+--git-dir=\S+|\s+--work-tree=\S+)*\s+push\b(?P<rest>[^;&|]*)")
_FORCE_RE = re.compile(r"(?:^|\s)(?:--force(?:-with-lease)?(?:=\S+)?|-f|-[a-zA-Z]*f[a-zA-Z]*)(?:\s|$)|(?:^|\s)\+\S+")
_DOCKER_COMPOSE_RE = re.compile(r"(?:^|[;&|]\s*)(?:docker\s+compose|docker-compose)\b(?P<rest>[^;&|]*)")
_LIFECYCLE_RE = re.compile(r"\b(up|down|restart|stop|start|rm|kill|build|run|exec|create|recreate|pull)\b")
_DOCKER_DESTRUCTIVE_RE = re.compile(r"\bdocker\s+(?:system\s+prune|volume\s+(?:rm|prune)|container\s+prune\s+.*--volumes)")
_REDIRECT_TO_PROTECTED_RE = re.compile(r"(?:>>?|tee\s+(?:-a\s+)?|sed\s+-i\S*\s+(?:'[^']*'|\"[^\"]*\"|\S+)\s+)\s*\S*(?:\.env\.local|anchors\.local\.yaml)\b")


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def _git(cwd: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


_CD_RE = re.compile(r"^\s*cd\s+(?P<dir>\"[^\"]+\"|'[^']+'|\S+)\s*(?:&&|;)")


def effective_cwd(command: str, cwd: Path) -> Path:
    """The directory a leading ``cd <dir> &&`` puts the rest of the command in."""
    m = _CD_RE.match(command)
    if not m:
        return cwd
    target = m.group("dir").strip("\"'")
    if target.startswith("/c/") or target.startswith("/d/"):
        target = f"{target[1].upper()}:{target[2:]}"
    path = Path(target)
    return path if path.is_absolute() else (cwd / path)


def _toplevel(path: Path) -> Path | None:
    """Git toplevel of ``path`` (None when it is not inside a repository)."""
    try:
        out = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None


def stamp_checker(repo: Path) -> list[str] | None:
    """The repo's own stamp-check command, or None when the repo has no stamp gate."""
    for candidate in (repo / "scripts" / "agent" / "validate.py", repo / "scripts" / "validate.py"):
        if candidate.is_file() and "--check-stamp" in candidate.read_text(encoding="utf-8", errors="replace"):
            return [sys.executable, str(candidate), "--check-stamp"]
    return None


def _pushes_main(rest: str, cwd: Path) -> bool:
    tokens = [t for t in rest.split() if not t.startswith("-")]
    # tokens: [remote, refspec...]
    refspecs = tokens[1:] if tokens else []
    if not refspecs:
        return _git(cwd, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    for spec in refspecs:
        dst = spec.split(":", 1)[1] if ":" in spec else spec
        if dst.lstrip("+") in ("main", "refs/heads/main"):
            return True
        if spec in ("HEAD",) and _git(cwd, "rev-parse", "--abbrev-ref", "HEAD") == "main":
            return True
    return False


def check_bash(command: str, cwd: Path) -> str | None:
    """Return a denial reason for ``command`` or None."""
    repo = _toplevel(effective_cwd(command, cwd))
    for m in _GIT_PUSH_RE.finditer(command):
        rest = m.group("rest") or ""
        if _FORCE_RE.search(rest):
            return "Force pushes are never allowed (git push --force / -f / +refspec)."
        if repo is not None and _pushes_main(rest, repo):
            checker = stamp_checker(repo)
            if checker is None:
                continue  # a repo without a stamp gate is not ours to guard
            check = subprocess.run(checker, cwd=str(repo), capture_output=True, text=True, timeout=120)
            if check.returncode != 0:
                detail = (check.stdout or check.stderr).strip().splitlines()[-1:] or [""]
                return (
                    f"Push to main in {repo} refused: HEAD's tree has no validation stamp for the tier this diff needs. "
                    f"{detail[0]} Run that repo's validate.py (auto tier) on a clean tree, then push."
                )
    if _DOCKER_DESTRUCTIVE_RE.search(command):
        return "Destructive docker command refused (system prune / volume rm|prune). Named volumes are never deleted here."
    for m in _DOCKER_COMPOSE_RE.finditer(command):
        rest = m.group("rest") or ""
        if not _LIFECYCLE_RE.search(rest):
            continue
        scoped_to_test = "docker-compose.test.yml" in rest or re.search(r"(?:-p|--project-name)[\s=]+\S*-test", rest)
        if not scoped_to_test:
            return (
                f"docker compose lifecycle command against the primary project `{PRIMARY_PROJECT}` refused. "
                "Validation uses the ephemeral stack (scripts/agent/validate.py); the primary stack is the operator's."
            )
        if re.search(r"\bdown\b.*(?:\s-v\b|--volumes)", rest) and not scoped_to_test:
            return "`docker compose down -v` against the primary project refused."
    if _REDIRECT_TO_PROTECTED_RE.search(command):
        return "Writing to .env.local / anchors.local.yaml refused: operator-owned personal/secret files."
    return None


def check_file_edit(file_path: str) -> str | None:
    norm = file_path.replace("\\", "/")
    if any(norm.endswith(p) for p in PROTECTED_FILES):
        return f"Editing {Path(norm).name} refused: operator-owned personal/secret file (edit it yourself)."
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    tool = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}
    cwd = Path(payload.get("cwd") or PROJECT_DIR)
    reason = None
    if tool == "Bash":
        reason = check_bash(str(tool_input.get("command") or ""), cwd)
    elif tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        reason = check_file_edit(str(tool_input.get("file_path") or tool_input.get("notebook_path") or ""))
    if reason:
        deny(reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
