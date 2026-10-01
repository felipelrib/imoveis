#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# setup-tools.sh — Ensure required dev tools are installed and on PATH
#
# Called by validate.sh and finish-feature.sh to guarantee the toolchain
# is available.  Idempotent — safe to run multiple times.
# ---------------------------------------------------------------------------
set -euo pipefail

echo "[setup-tools] Checking required tools..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Also support a direct setup-tools invocation.
if ! declare -F activate_project_python >/dev/null; then
    source "$SCRIPT_DIR/lib.sh"
fi
activate_project_python || die "runnable project Python required (create .venv first)"

# ---- Ensure ~/.local/bin is on PATH ----
if [ -d "$HOME/.local/bin" ]; then
    export PATH="$HOME/.local/bin:$PATH"
fi

# ---- Install Python dev tools ----
# Gate-only tools — deliberately NOT in requirements.in/.txt, which is the
# pip-compile'd RUNTIME lockfile that builds the API image (pip-audit powers
# the advisory audit-deps.sh stage; it must not ship to production).
PYTHON_TOOLS=(isort flake8 pytest pytest-timeout alembic autoflake pre-commit pip-audit)
MISSING=()
for tool in "${PYTHON_TOOLS[@]}"; do
    # Plugins such as pytest-timeout have no console executable.
    if ! "$PYTHON_BIN" -c 'import importlib.metadata, sys; importlib.metadata.version(sys.argv[1])' "$tool" 2>/dev/null; then
        MISSING+=("$tool")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "[setup-tools] Installing missing Python tools: ${MISSING[*]}"
    "$PYTHON_BIN" -m pip install --break-system-packages "${MISSING[@]}" 2>/dev/null \
        || "$PYTHON_BIN" -m pip install "${MISSING[@]}" 2>/dev/null \
        || echo "[setup-tools] WARNING: Could not install some tools: ${MISSING[*]}"
fi

# ---- Ensure frontend dependencies ----
if [ -d "$REPO_ROOT/frontend" ] && [ ! -d "$REPO_ROOT/frontend/node_modules" ]; then
    echo "[setup-tools] Installing frontend dependencies..."
    (cd "$REPO_ROOT/frontend" && npm install --ignore-scripts 2>/dev/null) \
        || echo "[setup-tools] WARNING: npm install failed"
fi

echo "[setup-tools] Done."
