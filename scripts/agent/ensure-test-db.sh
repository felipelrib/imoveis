#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# ensure-test-db.sh
#
# Create (if missing) and migrate the isolated integration-test database
# (default: realestate_test). Under validate.sh, TEST_DATABASE_URL points at
# the ephemeral test stack (test-stack.sh) — the primary server is never
# touched. Without TEST_DATABASE_URL (manual/operator use), falls back to the
# POSTGRES_* env server. Never points app/scraper containers at this database.
#
# Usage:
#   bash scripts/agent/ensure-test-db.sh
#   TEST_DATABASE_URL=postgresql://... bash scripts/agent/ensure-test-db.sh
# ---------------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

cd "$REPO_ROOT"
[ -f "$REPO_ROOT/.env.local" ] && { set -a; # shellcheck disable=SC1091
  source "$REPO_ROOT/.env.local"; set +a; }

DB_USER="${POSTGRES_USER:-imoveis}"
DB_PASS="${POSTGRES_PASSWORD:-imoveis_local_dev}"
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"
PRIMARY_DB="${POSTGRES_DB:-realestate}"
TEST_DB="${POSTGRES_TEST_DB:-realestate_test}"

if [ -n "${TEST_DATABASE_URL:-}" ]; then
  TARGET_URL="$TEST_DATABASE_URL"
  # Admin connection (CREATE DATABASE cannot run inside the target) goes to the
  # SAME server as the target URL — with the ephemeral test stack this is the
  # throwaway server's own maintenance DB, never the primary stack's server.
  ADMIN_URL="${TARGET_URL%/*}/${PRIMARY_DB}"
else
  TARGET_URL="postgresql://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${TEST_DB}"
  ADMIN_URL="postgresql://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${PRIMARY_DB}"
fi

PYTHON_BIN=""
if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
elif command -v python3 &>/dev/null; then
  PYTHON_BIN="python3"
else
  die "python3 required to ensure test database"
fi

if [[ ! "$TEST_DB" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  die "refusing unsafe POSTGRES_TEST_DB name: ${TEST_DB}"
fi

log "Ensuring test database exists (${TEST_DB})..."
ADMIN_URL="$ADMIN_URL" TEST_DB="$TEST_DB" "$PYTHON_BIN" - <<'PY'
import os
from sqlalchemy import create_engine, text

admin_url = os.environ["ADMIN_URL"]
test_db = os.environ["TEST_DB"]
engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
with engine.connect() as conn:
    exists = conn.execute(
        text("SELECT 1 FROM pg_database WHERE datname = :n"),
        {"n": test_db},
    ).scalar()
    if not exists:
        conn.execute(text(f'CREATE DATABASE "{test_db}"'))
        print(f"created database {test_db}")
    else:
        print(f"database {test_db} already exists")
engine.dispose()
PY

log "Ensuring PostGIS + pgvector on ${TEST_DB}..."
TARGET_URL="$TARGET_URL" "$PYTHON_BIN" - <<'PY'
import os
from sqlalchemy import create_engine, text

url = os.environ["TARGET_URL"]
engine = create_engine(url, isolation_level="AUTOCOMMIT")
with engine.connect() as conn:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
engine.dispose()
print("extensions ok")
PY

log "Migrating test database (alembic upgrade head)..."
export DATABASE_URL="$TARGET_URL"
export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
"$PYTHON_BIN" -m alembic upgrade head
ok "test database ready (${TEST_DB})"
