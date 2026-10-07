#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# validate.sh — compatibility wrapper. The gate is scripts/agent/validate.py.
#
#   bash scripts/agent/validate.sh [docs|fast|frontend|backend|full|all|auto] [--soft]
#
# Kept so existing callers (bmad-loop policy.toml, older docs) keep working;
# `all` maps to the `full` tier. Prefer: python scripts/agent/validate.py
# ---------------------------------------------------------------------------
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"
activate_project_python || die "runnable project Python required (create .venv first)"
exec "$PYTHON_BIN" "$HERE/validate.py" "$@"
