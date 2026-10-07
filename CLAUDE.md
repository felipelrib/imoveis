@AGENTS.md

## Claude Code specifics

- Hooks in `.claude/settings.json` (committed) are the enforcement layer: `session_start.py` prints branch / dirty state / validation stamp at session start — no manual `git rev-parse` ritual; `guard.py` (PreToolUse) blocks unvalidated or forced pushes to `main`, primary-stack docker commands and operator-file edits; `auto_push.py` (Stop) pushes a clean, stamped `main`. The bmad-loop relay hooks stay alongside.
- On Windows run the gate as `.venv/Scripts/python.exe scripts/agent/validate.py`; Git Bash by full path (`'C:/Program Files/Git/bin/bash.exe'`) only for `migrate-primary.sh` and `scripts/ops/*.sh` — bare `bash` may resolve to the WSL launcher.
- Writes to `.claude/skills/` are not committed (`.agents/skills/` is the committed BMad copy); `.claude/settings.local.json` is personal.
- Durable lessons go into `AGENTS.md` (shared by every agent tool), not here; keep this file to Claude-only mechanics.
