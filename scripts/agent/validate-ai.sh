#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# validate-ai.sh
#
# Validates AI output quality hasn't regressed after prompt/client changes.
# Runs golden-file tests that compare AI scores against known baselines.
# Skips gracefully if OLLAMA_HOST is unreachable (CI-safe).
# ---------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

log "AI validation: checking Ollama availability"

OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
if ! curl -fsS "$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
  warn "Ollama not reachable at $OLLAMA_HOST — skipping AI validation"
  exit 0
fi
ok "Ollama is reachable"

cd "$REPO_ROOT"

log "AI validation: running golden-file tests"
if python -m pytest src/tests/unit/test_ai_quality.py -v --timeout=120; then
  ok "AI validation PASSED"
else
  warn "AI validation FAILED — score deviations may exceed ±0.15 threshold"
  exit 1
fi