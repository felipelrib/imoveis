#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# setup-tools.sh — Ensure required dev tools are installed and on PATH
#
# Called by validate.sh and finish-feature.sh to guarantee the toolchain
# is available.  Idempotent — safe to run multiple times.
# ---------------------------------------------------------------------------
set -euo pipefail

echo "[setup-tools] Checking required tools..."

# ---- Python version detection ----
# Prefer python3, fall back to python
PYTHON=""
if command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    echo "[setup-tools] ERROR: python not found"
    exit 1
fi

# ---- Ensure ~/.local/bin is on PATH ----
if [ -d "$HOME/.local/bin" ]; then
    export PATH="$HOME/.local/bin:$PATH"
fi

# ---- Install Python dev tools ----
PYTHON_TOOLS=(isort flake8 pytest pytest-timeout alembic autoflake)
MISSING=()
for tool in "${PYTHON_TOOLS[@]}"; do
    if ! command -v "$tool" &>/dev/null; then
        MISSING+=("$tool")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "[setup-tools] Installing missing Python tools: ${MISSING[*]}"
    $PYTHON -m pip install --break-system-packages "${MISSING[@]}" 2>/dev/null \
        || $PYTHON -m pip install "${MISSING[@]}" 2>/dev/null \
        || echo "[setup-tools] WARNING: Could not install some tools: ${MISSING[*]}"
fi

# ---- Ensure frontend dependencies ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [ -d "$REPO_ROOT/frontend" ] && [ ! -d "$REPO_ROOT/frontend/node_modules" ]; then
    echo "[setup-tools] Installing frontend dependencies..."
    (cd "$REPO_ROOT/frontend" && npm install --ignore-scripts 2>/dev/null) \
        || echo "[setup-tools] WARNING: npm install failed"
fi

echo "[setup-tools] Done."
