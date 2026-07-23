#!/usr/bin/env bash
# Build and run the project Postgres image (PostGIS + pgvector) for CI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE_NAME="${POSTGRES_IMAGE_NAME:-imoveis-postgres-pgvector}"
CONTAINER_NAME="${POSTGRES_CONTAINER_NAME:-imoveis-ci-postgres}"
PORT="${POSTGRES_PORT:-5432}"

docker build -t "${IMAGE_NAME}" -f "${ROOT}/Dockerfile.postgres" "${ROOT}"

docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true

docker run -d \
  --name "${CONTAINER_NAME}" \
  -p "${PORT}:5432" \
  -e POSTGRES_USER=imoveis \
  -e POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-test_password}" \
  -e POSTGRES_DB=realestate \
  "${IMAGE_NAME}"

echo "Waiting for Postgres on :${PORT}..."
for _ in $(seq 1 60); do
  if docker exec "${CONTAINER_NAME}" pg_isready -U imoveis -d realestate >/dev/null 2>&1; then
    echo "Postgres is ready."
    exit 0
  fi
  sleep 1
done

echo "Postgres failed to become ready" >&2
docker logs "${CONTAINER_NAME}" >&2 || true
exit 1
