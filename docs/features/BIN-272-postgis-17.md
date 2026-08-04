# PostGIS 15 → 17 upgrade — Dockerfile build-deps + local data migration

> Feature branch: `feat/postgis-17` · Linear: `BIN-272` · Status: implemented

## Problem

Dependabot PR #199 bumped `postgis/postgis:15-3.3-alpine → 17-3.5-alpine` by changing
only the `FROM` tag. `Dockerfile.postgres` compiles pgvector from source and hard-coded
PG15-era build-deps (`clang15`, `llvm15`, `postgresql15-dev`). Against the PG17 base
those packages don't resolve, so the image build failed — and because CI's `integration`
and `contract` jobs build this image in `scripts/ci/start-postgres-pgvector.sh`, both
failed at "Start Postgres (PostGIS + pgvector)". A raw tag bump can never work here; the
toolchain has to move with it.

Separately, Postgres 15 → 17 is a **major** engine bump: an existing PG15 data directory
will not start under a PG17 server, so the local dev volume needs a logical
dump → reset → restore (there is real scraped data locally worth keeping).

## Approach

- **Match build-deps to the base image toolchain.** `postgis:17-3.5-alpine` is Alpine
  3.24 and its Postgres is built `--with-llvm` using **LLVM 21** (`pg_config --configure`
  → `LLVM_CONFIG=/usr/lib/llvm21/bin/llvm-config`). So the pgvector build now uses
  `clang21` / `llvm21-dev` / `postgresql17-dev`. A code comment documents the coupling so
  the next major bump moves them in lockstep.
- **Logical dump/restore for the local volume**, verified against a throwaway container
  *before* touching the primary volume, so there is no window where data could be lost.

## Changes

Files touched:

```
 Dockerfile.postgres                  | CHANGED — FROM 17-3.5-alpine; build-deps clang21/llvm21-dev/postgresql17-dev; doc comment
 docs/features/BIN-272-postgis-17.md  | NEW — this doc + migration runbook
```

## New Dependencies

None (Docker base-image major bump only). Runtime versions after upgrade: Postgres
17.10, PostGIS 3.5.7, pgvector 0.8.0.

## How to Test

CI builds the image fresh and runs `integration` + `contract` against it — that is the
authoritative check. Locally:

```bash
docker compose --env-file .env.local -p imoveis build postgres   # image builds, pgvector compiles
bash scripts/agent/validate.sh backend                            # integration + contract on realestate_test
```

## Local data migration runbook (PG15 → PG17)

Performed once on the primary dev stack; repeat on any other PG15 checkout. **Back up and
verify before removing the volume.**

```bash
# 1. Back up the running PG15 database (custom format)
mkdir -p ~/imoveis-backups
docker exec imoveis-postgres-1 pg_dump -Fc -U imoveis -d realestate \
  > ~/imoveis-backups/realestate-pg15-$(date +%Y%m%d-%H%M%S).dump

# 2. Stop the stack (keeps volumes) and reset the postgres volume
docker compose --env-file .env.local -p imoveis down --remove-orphans
docker volume rm imoveis_postgres_data

# 3. Build + start the PG17 image (postgres only), and WAIT until first-time
#    init finishes (container reports healthy) — restoring during init gets killed.
docker compose --env-file .env.local -p imoveis build postgres
docker compose --env-file .env.local -p imoveis up -d postgres
#    (wait for `docker compose ... ps` to show postgres "healthy")

# 4. Restore into a clean database
docker exec imoveis-postgres-1 psql -U imoveis -d postgres -c \
  "DROP DATABASE IF EXISTS realestate WITH (FORCE); CREATE DATABASE realestate OWNER imoveis;"
cat ~/imoveis-backups/realestate-pg15-*.dump | \
  docker exec -i imoveis-postgres-1 pg_restore --no-owner -U imoveis -d realestate

# 5. Bring the rest of the stack up (API alembic upgrade is a no-op at head)
docker compose --env-file .env.local -p imoveis up -d
curl -s http://localhost:8000/health   # {"status":"ok","db":"ok","redis":"ok"}
```

Restore was verified faithful: exact row counts (properties 26188, property_listings
27292, price_history 27384, metrics_scoring 13523), all 24,148 pgvector embeddings, and
`alembic_version` preserved.

## Notes / Follow-ups

- Supersedes Dependabot PR #199 (closed as superseded — a tag-only bump cannot fix the
  build-deps).
- **BUG (Low)**: build-deps are version-coupled to the base image. The next Postgres/Alpine
  major bump will fail the build again until `clang`/`llvm`/`postgresql*-dev` are bumped
  in lockstep — fix hint: build pgvector with `with_llvm=no` to drop the LLVM-version
  coupling entirely (loses only pgvector JIT inlining, negligible at this scale).
- The PG15 backup dump is retained under `~/imoveis-backups/` and can be deleted once the
  PG17 stack is confirmed good in daily use.
