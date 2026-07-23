#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# validate-scrapers.sh
#
# Validates scraper health: HTML cassette unit tests + live dry-run.
# Exit 0 = healthy.
#
# Flags:
#   --require-live   Fail if live dry-run fails (CI / merge gate). Default on
#                    for CI via this flag; local default is also fail-on-live
#                    unless --skip-live is passed.
#   --skip-live      Cassette tests only (fast local iteration).
#
# When live fails because site HTML drifted, agents MUST refresh cassettes:
#   python scripts/dev/record_scraper_cassettes.py
#   # update src/tests/unit/test_scraper_cassettes.py expectations if needed
#   bash scripts/agent/validate-scrapers.sh --require-live
# Do NOT delete or weaken the scrapers CI job to pass.
# ---------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

REQUIRE_LIVE=true
for arg in "${@}"; do
  case "$arg" in
    --require-live) REQUIRE_LIVE=true ;;
    --skip-live)    REQUIRE_LIVE=false ;;
  esac
done

rc=0
cd "$REPO_ROOT"

# Prefer python3 (matches validate.sh)
PYTHON_BIN="python3"
command -v python3 &>/dev/null || PYTHON_BIN="python"

log "Scraper validation: HTML cassette + unit tests"
if "$PYTHON_BIN" -m pytest \
  src/tests/unit/test_scraper_cassettes.py \
  src/tests/unit/test_olx.py \
  src/tests/unit/test_scoring_and_fees.py \
  src/tests/unit/test_registry.py \
  -v --timeout=30; then
  ok "scraper cassette/unit tests passed"
else
  warn "scraper cassette/unit tests FAILED"; rc=1
fi

if [ "$REQUIRE_LIVE" = false ]; then
  warn "Skipping live dry-run (--skip-live)"
  [ "$rc" -eq 0 ] && ok "SCRAPER VALIDATION PASSED (cassettes only)" || warn "SCRAPER VALIDATION FAILED (rc=$rc)"
  exit "$rc"
fi

log "Scraper validation: dry-run against live pages (merge-blocking)"
if "$PYTHON_BIN" scripts/dev/test_scraper_dryrun.py; then
  ok "scraper dry-run passed"
else
  warn "scraper dry-run FAILED"
  warn "If HTTP succeeded but parsing/normalize broke, cassettes are likely OUTDATED."
  warn "Refresh: $PYTHON_BIN scripts/dev/record_scraper_cassettes.py"
  warn "Then update test_scraper_cassettes.py expectations if fields changed, re-run this script."
  warn "If the site is down / blocked, fix connectivity or retry — do not skip this gate in CI."
  rc=1
fi

[ "$rc" -eq 0 ] && ok "SCRAPER VALIDATION PASSED" || warn "SCRAPER VALIDATION FAILED (rc=$rc)"
exit "$rc"
