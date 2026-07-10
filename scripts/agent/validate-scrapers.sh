#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# validate-scrapers.sh
#
# Validates scraper health: unit tests + dry-run against live pages.
# Exit 0 = all scrapers are healthy.
# ---------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

rc=0
cd "$REPO_ROOT"

log "Scraper validation: unit tests"
if python -m pytest src/tests/unit/test_olx.py src/tests/unit/test_registry.py src/tests/unit/test_cb.py -v --timeout=30; then
  ok "scraper unit tests passed"
else
  warn "scraper unit tests FAILED"; rc=1
fi

log "Scraper validation: dry-run against live pages"
if python scripts/dev/test_scraper_dryrun.py; then
  ok "scraper dry-run passed"
else
  warn "scraper dry-run FAILED — check site availability or HTML structure changes"; rc=1
fi

[ "$rc" -eq 0 ] && ok "SCRAPER VALIDATION PASSED" || warn "SCRAPER VALIDATION FAILED (rc=$rc)"
exit "$rc"
