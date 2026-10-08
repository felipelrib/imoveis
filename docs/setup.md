# Setup Guide

## Prerequisites

- Python 3.11 (matching the shipped images and Windows lock)
- PostgreSQL 13+ with PostGIS extension
- Redis 6+
- Git
- Docker & Docker Compose (for containerized workflow)
- Ollama (for local AI enrichment)

## Native Windows checkout

For development in `C:\Workfolder\imoveis`, install Git for Windows, Python
**3.11**, Node.js, Docker Desktop using Linux containers, and Ollama. Use the
existing private configuration and Docker volumes when migrating an installation;
[the migration record](windows-migration.md) identifies the state Git cannot carry.
The setup/start scripts never migrate the primary database: on the primary
compose project `scripts/start.sh` only reports whether the schema is at head
and names the operator step, `bash scripts/agent/migrate-primary.sh`. Agent
validation uses its own throwaway database.

From PowerShell in the checkout:

```powershell
py -3.11 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-windows.txt pre-commit
.venv/Scripts/python.exe -m pre_commit install
npm ci --prefix frontend
& ./frontend/node_modules/.bin/playwright.cmd install chromium
.venv/Scripts/python.exe scripts/agent/validate.py --tier full
```

The gate and the ship script are plain Python and run from any shell — no Git
Bash needed. Only the remaining shell scripts (`scripts/agent/migrate-primary.sh`,
`scripts/ops/*.sh`) need Git Bash; invoke it by its full path
(`& 'C:/Program Files/Git/bin/bash.exe' scripts/agent/migrate-primary.sh`)
because bare `bash` may launch WSL.
Stop this checkout's Vite dev server before a `frontend`/`full` tier run: Windows
locks its loaded native build module and can block the gate's `npm ci`. Restart
Vite after finishing.
Keep `.env.local` private and LF-terminated. The gate loads only allowed workspace
settings and isolates tests from primary database, cloud routing and credentials.

The Linux/Docker lock remains `requirements.txt`. Regenerate the Windows lock on
native Python 3.11 after changing the source or Linux pins:

```powershell
.venv/Scripts/python.exe -m pip install pip-tools
.venv/Scripts/python.exe -m piptools compile requirements.in --constraint requirements.txt --output-file requirements-windows.txt --strip-extras
```

This retains compatible shared pins while excluding Linux-only `uvloop` and
including Windows dependencies. Commit both intended lock updates and validate.
Do not reuse a WSL virtualenv or `node_modules` on Windows.

With the existing API available, start Vite with
`npm run dev --prefix frontend -- --host 127.0.0.1`, then open its reported URL.
Protected dashboard routes require the same private `API_KEY` saved through the
sidebar credential field for that browser session.

Windows backfill supervision uses the installer described in
[ADR 0006](adr/0006-backfill-runner-hosting.md). The operator selected automatic
startup **at sign-in**; the task does not provide pre-login availability.
Stop and disable the previous WSL systemd supervisor before installing the
Windows task, so only one host consumes start requests. Installation itself
must not request a cloud enrichment run.

Use the following from PowerShell (execution-policy flags apply only to that
invocation; no machine-wide policy change):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/install-backfill-runner.ps1 -Mode Check
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/install-backfill-runner.ps1 -Mode Install
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/install-backfill-runner.ps1 -Mode Status
```

`-Mode Print` shows the task plan without installing. `-Mode Stop` disables its
triggers and requests a graceful drain; use `Install` to enable/start again.
`-Mode Uninstall` drains then removes the task. Never use Task Scheduler's End
button as the normal stop path. Check `.run/backfill-host/host.log` and the
admin API's `runner_present` field independently of task status. The task runs
only while the user is signed in. Re-run Install after moving the checkout or
rebuilding its virtualenv; it drains the old registered checkout first.

## Initial Linux / WSL setup

One command to get everything running:

```bash
./scripts/setup.sh
```

This will:
1. Create `.env.local` from the template (if missing)
2. Install frontend dependencies
3. Build Docker images (postgres, redis, api, workers)
4. Start the full stack with health checks (API + background Vite on :5173)
5. Report the database schema state. On the primary compose project (`imoveis`, the
   default) nothing is migrated: apply migrations with the operator step
   `bash scripts/agent/migrate-primary.sh`, which takes the migration lock and refuses
   under a live backfill runner. A fresh install always needs it once. A checkout whose
   `.env.local` names another (isolated) compose project is migrated by `start.sh` itself.

### Local API key (required for the SPA)

Favourites, watchlist, saved searches, and admin routes require `API_KEY` on the API
and the **same** value pasted into the sidebar **API credential** field (sessionStorage →
`X-API-Key`). Missing/mismatched keys show up as **401/403** in the browser network tab.

Compose **requires** `API_KEY` at interpolate time (`:?`). Always start via `./scripts/start.sh`,
`./scripts/restart.sh`, or `docker compose --env-file .env.local …`. A bare
`docker compose up` without the env file fails instead of serving admin routes with an
empty key (which caused SPA `403 Admin API key not configured`).

1. Ensure `.env.local` includes a local-only key (the template ships with one):

   ```env
   API_KEY=local-dev-api-key
   ```

2. Restart so Compose injects it into the API container **and** backgrounds Vite:

   ```bash
   ./scripts/restart.sh
   ```

3. Open http://localhost:5173 → paste `local-dev-api-key` into **API credential** → **Save**.

```bash
curl -s -H "X-API-Key: local-dev-api-key" http://localhost:8000/admin/health
```

## Day-to-Day Commands

| Script | What it does |
|--------|-------------|
| `./scripts/start.sh` | Start stack + background Vite on :5173. Primary project: reports the schema state, never migrates (pending → `bash scripts/agent/migrate-primary.sh`). Isolated project: migrates its own database |
| `./scripts/stop.sh` | Stop containers and the background Vite process |
| `./scripts/restart.sh` | Stop + start (`--build` rebuilds images; Vite comes back up) |
| `./scripts/test.sh` | Run tests (`unit`, `integration`, `e2e`, or `all`) |
| `./scripts/dev.sh` | Same stack, but Vite in the foreground (Ctrl+C stops UI only) |
| `./scripts/clean.sh` | Stop stack; **never** deletes volumes (`--all` also drops rebuildable images/cache) |
| `python scripts/agent/validate.py` | The merge gate — tier chosen from the diff (`--tier X` forces; `--only scrapers\|ai\|harness` runs one domain gate; `--down` removes the ephemeral test stack) |
| `python scripts/agent/ship.py` | Validate → squash-merge into `main` → push (refuses a dirty tree) |
| `bash scripts/ops/docker-cleanup.sh` | Occasional operator task: prune stopped containers, dangling + unused feature images, build cache (keeps primary `imoveis-*` + bases; never volumes) |

Start specific services only:

```bash
./scripts/start.sh postgres redis   # just database services
./scripts/start.sh api               # just the API
```

## Manual Setup

If you prefer to set up without Docker Compose:

### Python Environment

```bash
git clone https://github.com/felipelrib/imoveis.git
cd imoveis
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Dependency lockfile

`requirements.txt` is a **fully pinned lockfile** generated by [`pip-compile`](https://pip-tools.readthedocs.io/) (from [`pip-tools`](https://pypi.org/project/pip-tools/)) — every direct *and* transitive dependency is pinned to an exact version, so `pip install -r requirements.txt` resolves with the pinned Linux versions in Linux local dev, the local gates, and the Docker images (`Dockerfile.api`, `Dockerfile.worker`) regardless of when it runs.

The hand-edited source of truth is `requirements.in` (loose/top-level dependencies, same file CI/Docker used before this lockfile existed). Never hand-edit `requirements.txt` — regenerate it from `requirements.in` instead. Use the same Python version as the Docker images (**3.11** — see `Dockerfile.api`/`Dockerfile.worker`) so resolved wheels match what actually ships:

```bash
# One-time: install pip-tools matching the project's Python (3.11)
pip install pip-tools

# Regenerate the lockfile after editing requirements.in (e.g. adding a package)
pip-compile requirements.in --output-file=requirements.txt --strip-extras

# Bump every pinned version to the latest allowed by requirements.in
pip-compile requirements.in --output-file=requirements.txt --strip-extras --upgrade

# Bump a single package
pip-compile requirements.in --output-file=requirements.txt --strip-extras --upgrade-package fastapi
```

After regenerating, run `python scripts/agent/validate.py --tier full` and rebuild the API/worker images (`docker compose build api worker`) before trusting the change — the lockfile only takes effect once the image is rebuilt from it.

### Database

```bash
createdb realestate_dev
psql realestate_dev -c "CREATE EXTENSION postgis;"
cd alembic && alembic upgrade head && cd ..
```

### Configuration

All settings live in `configs/app_config.yaml`. Environment variable overrides use `${ENV}` syntax:

```bash
export DATABASE_URL=postgresql://user:pass@localhost:5432/realestate_dev
export REDIS_URL=redis://localhost:6379/0
export OLLAMA_HOST=http://localhost:11434
```

### Start Services

```bash
# API
uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --reload

# Scraper workers (scrapes only; a scrape can hold a slot for hours)
celery -A src.adapters.queue.celery worker -Q scrapers -c 4 -n scraper@%h

# AI workers (GPU-bound — match gpu.semaphore_limit / OLLAMA_NUM_PARALLEL)
celery -A src.adapters.queue.celery worker -Q ai -c 2 -n ai@%h

# Periodic workers (every other task: monitor, snapshot, alerts, digests, recheck, refresh)
celery -A src.adapters.queue.celery worker -Q periodic -c 2 -n periodic@%h
```

Each worker gets its own node name (`-n`): without it all three are `celery@<host>`,
and `GET /system/status`, which keys the workers' replies by node name, sees one.

Three queues, one worker each: `scrapers`, `ai`, `periodic`. Without a worker on
`periodic` no alert, digest, snapshot or queue monitor runs, and `GET /system/status`
reports `No worker consumes queue(s): periodic`. In Docker the three services are
`worker_scraper`, `worker_ai` and `worker_periodic`. A new task is routed to `periodic`
unless it is a scrape or GPU work; an idempotent beat entry also gets `expires`
(see `docs/architecture.md`, Task Queue).

## AI Model Setup

### Ollama (Recommended)

```bash
ollama serve  # Prefer OLLAMA_HOST=http://0.0.0.0:11434 so Docker/WSL can reach Windows Ollama
ollama pull qwen2.5vl:7b
ollama pull bge-m3
```

#### Windows host memory / concurrency (RX 7900 XT ~20 GB VRAM)

Ollama env vars control KV-cache preallocation. Oversized `OLLAMA_NUM_PARALLEL` with
`num_ctx=16384` spills VRAM into system RAM and thrash the host.

| Variable | Recommended | Notes |
|---|---|---|
| `OLLAMA_NUM_PARALLEL` | `2` | Must equal `gpu.semaphore_limit` / `worker_ai` concurrency |
| `OLLAMA_CONTEXT_LENGTH` | `16384` | Align with `ai.num_ctx` in `app_config.yaml` |
| `OLLAMA_KEEP_ALIVE` | `30m` | Avoid leaving models resident for hours (`600m`) |
| `OLLAMA_MAX_LOADED_MODELS` | `2` | VLM + embedding |
| `OLLAMA_HOST` | `http://0.0.0.0:11434` | Required for Docker `host.docker.internal` / WSL |

App defaults after tuning: `gpu.semaphore_limit: 2`, Celery AI `--concurrency=2`,
serial visual→text inside each enrich task. Re-measure with:

```bash
PYTHONPATH=src python scripts/dev/bench_ollama_vram.py --cases A,D
```

### LM Studio (Alternative)

1. Download from https://lmstudio.ai
2. Load a quantized VLM model (e.g., `llava-1.6-mistral-7b.Q4_K_M.gguf`)
3. Start local server (typically on `http://localhost:1234`)
4. Update `configs/app_config.yaml` accordingly

## Proxy rotation (scrapers)

Scrapers use the global `proxy:` block in `configs/app_config.yaml` (FR-20). Credentials
belong in env / local overrides — never commit real `user:pass` URLs.

### Enable a pool

```yaml
proxy:
  enabled: true
  rotation_strategy: round_robin   # or random
  url: null
  pool:
    - http://user:pass@proxy1.example:8080
    - http://user:pass@proxy2.example:8080
```

Or a single proxy via `url` (leave `pool: []`). Restart Celery scraper workers so they
reload AppConfig. On the next scrape you should see:

- Structured log `scraper_proxy_mode` with `proxy_mode` (`pool` / `single`), `pool_size`,
  and `proxy_host` (host:port only — no credentials).
- Redis key `pipeline:scraper:<platform>:status` (also exposed via `GET /system/pipeline`)
  with the same safe fields.

Env override example: `IMOVEIS_PROXY__ENABLED=true`.

### Disable (direct mode)

Set `proxy.enabled: false` (or empty pool/url while disabled). Restart workers. The next
scrape uses a direct connection — no code changes. Logs/status show `proxy_mode: direct`.

Platform `extra.proxy` in scraping config, when set to a non-null URL, overrides the global
pool for that platform only.

## Cloudflare bypass (OLX) — headless-browser fetch (BIN-246)

OLX serves a Cloudflare JS challenge (HTTP 403) to plain HTTP clients, so proxy rotation
alone does not help (free/datacenter proxy IPs are challenged the same way). The bypass
routes a platform's GETs through a [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr)
sidecar — a real headless browser that solves the challenge and returns rendered HTML. A
residential exit IP plus a real browser clears the challenge; no paid proxy is required.

It is **off by default** and opt-in in two steps:

1. Start the sidecar (a compose profile, so the default stack never runs it):

   ```bash
   docker compose --profile bypass up -d flaresolverr
   ```

2. Enable it in `configs/app_config.yaml` (or via env) and restart scraper workers:

   ```yaml
   scraping:
     cloudflare_bypass:
       enabled: true
       endpoint: http://flaresolverr:8191/v1   # compose-network address
       max_timeout_ms: 60000
       platforms:
         - olx
   ```

   Env override: `IMOVEIS_SCRAPING__CLOUDFLARE_BYPASS__ENABLED=true`.

On the next scrape, listed platforms log `scraper_cloudflare_bypass` (platform + endpoint)
and per-request `flaresolverr_fetch` (url, status, bytes); `proxy_summary` carries
`cloudflare_bypass: true`. Throttling and circuit breakers are unchanged — only the
transport swaps. Disable by setting `enabled: false` and restarting workers (and optionally
`docker compose --profile bypass stop flaresolverr`).

## Development

### Code Quality (pre-commit)

This project uses [pre-commit](https://pre-commit.com/) for local linting and validation. Install the hooks once after cloning:

```bash
pip install pre-commit      # no-op once the regenerated lock carries it (it is declared in requirements.in)
pre-commit install          # runs on commit (isort, flake8, secrets, hygiene fixers)
```

After `pre-commit install`, the hooks run automatically on every
`git commit`; there is no pre-push stage — the push itself is guarded by the
validation stamp (below). The gate's lint stage runs the **same** hook set over
all tracked files:

```bash
pre-commit run --all-files
```

The fixer hooks (whitespace, end-of-file, isort) modify files when they fail —
commit their edits and re-run.

### Testing

Never run raw `pytest` / `npm test` as the gate. The gate is one command that
picks its tier from the diff:

```bash
python scripts/agent/validate.py                  # docs | fast | frontend | backend | full, chosen from the diff
python scripts/agent/validate.py --tier backend   # force a tier
python scripts/agent/validate.py --only scrapers  # one domain gate: scrapers | ai | harness
python scripts/agent/validate.py --check-stamp    # does HEAD's tree carry a stamp for the required tier?
```

Tiers: `docs` = `mkdocs build --strict`; `fast` = pre-commit + unit (xdist);
`frontend` = fast + eslint + Vite build + Playwright; `backend` = fast +
ephemeral PostGIS/Redis stack + integration + contract + `alembic check`;
`full` = everything. Path-triggered extras: scraper changes add the cassette
suite + live dry-run, AI prompt/client changes add the Ollama golden tests,
`scripts/`/harness changes add the `harness`-marked tests. On the Windows host
`fast` takes ≈ 75 s (lint 17 s + unit 55 s), `docs` ≈ 11 s; the harness-marked
tests take ≈ 14 min serial and run only when scripts change or in `full`.
`bash scripts/agent/validate.sh [all|fast|backend|…]` still works as a thin
wrapper (`all` = `full`).

A green run on a clean tree writes `.run/validated/<tree-sha>.<tier>`; that
stamp — not prose — is what lets a push to `main` through (see below).

The `backend`/`full` tiers build a throwaway compose project
`<COMPOSE_PROJECT_NAME>-test` from `docker-compose.test.yml` (docker-assigned
ports, anonymous volumes; `--down` removes it). Host pytest therefore uses an
isolated Postgres DB and Redis logical DB **15** (`REDIS_TEST_DB`); the primary
`imoveis` project keeps Postgres `realestate` and Redis DB **0** and is never
touched, so fixtures that truncate tables / `flushdb` cannot wipe scraped data or
Celery queues. See `docs/features/BIN-71-isolate-integration-test-db.md` and
`docs/features/BIN-117-isolate-redis-test-db.md`. `./scripts/test.sh` remains
for ad-hoc runs against your own running stack
(`./scripts/test.sh unit --args "-v -k test_dedupe"`).

### Shipping

```bash
git switch -c feat/<slug>        # story branches embed the key: feat/v0.14-s1.2-…
# … commit …
python scripts/agent/ship.py     # merge origin/main in → feature-doc check → validate → squash-merge → push
```

`ship.py` refuses a dirty tree and `bmad-loop/*` branches (the orchestrator
merges those), re-checks the validation stamp of the merged tree before pushing,
and deletes the branch afterwards. There is no Docker teardown or image pruning
in the merge path. Enforcement lives in Claude Code hooks, not prose:
`.claude/hooks/guard.py` denies `git push` to `main` without a stamp for HEAD's
tree, any force push, `docker compose` lifecycle commands against the primary
project, `docker system prune` / `docker volume rm`, and edits to `.env.local` /
`configs/anchors.local.yaml`; `.claude/hooks/auto_push.py` pushes `main` at the
end of a session when it is clean, ahead, not behind and stamped. See
[ADR 0007](adr/0007-tiered-gate-and-hook-enforced-push.md).

### Frontend Development

`./scripts/start.sh` and `./scripts/restart.sh` bring up backend containers **and** a
background Vite on http://localhost:5173 (logs: `.run/frontend.log`).
`./scripts/dev.sh` is the same stack with Vite attached to your terminal (hot-reload
logs visible; Ctrl+C stops only the UI — use `./scripts/stop.sh` for containers).

```bash
./scripts/start.sh   # Detached: API + workers + Vite on :5173
./scripts/dev.sh     # Foreground Vite (stops any background Vite first)
```

Or start Vite yourself after the backend:
```bash
./scripts/start.sh --no-frontend      # Backend containers only
cd frontend && npm run dev            # Frontend on FRONTEND_PORT (default 5173)
```

Remember to set `API_KEY` in `.env.local` and paste it in the UI (see above).

## Production Deployment

For a solo/small-team deployment, Docker Compose on a single server is sufficient:

```bash
# Clone and configure
git clone https://github.com/felipelrib/imoveis.git
cd imoveis
cp .env.local.example .env.local
# Edit .env.local with production values

# Start all services
./scripts/start.sh

# Or with explicit env
docker compose --env-file .env.local up -d
```

### Required Environment Variables

```env
DATABASE_URL=postgresql://user:password@db-host:5432/realestate_prod
REDIS_URL=redis://redis-host:6379/0
OLLAMA_HOST=http://gpu-host:11434
```

### Cloud Backfill Runner (host-side, systemd)

The cloud backfill supervisor is **not** a compose service. It runs on the host,
as your own user, out of the repo `.venv` — see
[ADR 0006](adr/0006-backfill-runner-hosting.md). Without it, the Operações
dashboard's Start button only records a request that nothing consumes.

```bash
# Inspect what would be installed (no privilege needed)
bash scripts/install-backfill-runner.sh --print

# Preflight the host + env contract only
bash scripts/install-backfill-runner.sh --check

# Install, enable and start (asks for sudo; writes /etc/systemd/system)
bash scripts/install-backfill-runner.sh

bash scripts/install-backfill-runner.sh --status      # unit state
bash scripts/install-backfill-runner.sh --uninstall   # disable + remove
```

Preconditions:

- `.env.local` must set `GEMINI_API_KEY` and `DATABASE_URL` (the config default
  DB name is *not* the primary `realestate`), plus `REDIS_URL` whenever
  `REDIS_PORT` is not 6379. See `.env.local.example`.
- **Cloud routing is enabled per host, in that same `.env.local`** — the unit
  reads it via `EnvironmentFile=`:

  ```env
  IMOVEIS_AI__ENRICHMENT_ROUTING__VISUAL=gemma
  IMOVEIS_AI__ENRICHMENT_ROUTING__SENTIMENT=gemma
  IMOVEIS_AI__ENRICHMENT_ROUTING__DEAL_VERDICT=gemma
  ```

  **All three, on the same backend.** `--serve` drives one cloud client and has
  no local mode, so it validates that *every* class in the backfill scope
  (`visual`, `sentiment`, `deal_verdict`) resolves to the **same** cloud backend
  before its poll loop. Route only some of them — or split them between `gemma`
  and `gemini` — and it exits at startup and the unit restarts every 10 s. Do
  **not** enable it by editing
  `ai.enrichment_routing` in the committed `configs/app_config.yaml`: that file
  must stay all-local (NFR-1) and a unit test pins it, so the edit turns the
  merge gate red. These overrides go through the same config loader, keep the
  routing map total, leave `ai.backend` (the live Celery path) local, and never
  enter git. No `export ` prefix — `EnvironmentFile=` is not a shell and would
  keep it literally, leaving the variable unset in the service.
- `bash scripts/install-backfill-runner.sh --check` resolves the *effective*
  routing (YAML overlaid with these overrides), so a correctly enabled host
  passes without a routing warning.
- Run the installer from the **primary checkout**; it refuses from a linked git
  worktree (that path is disposable).

`.env.local` is also read by the local gate, but only through an allowlist of
workspace-identity keys (ports, `COMPOSE_PROJECT_NAME`, the DB credentials and
test-DB selectors, `API_KEY`/`JWT_SECRET`) —
`WORKSPACE_ENV_ALLOWLIST` in `scripts/agent/validate.py` (mirrored by
`scripts/agent/lib.sh::load_workspace_env` for the remaining shell scripts).
Nothing else **in that file** — the cloud key, the primary `DATABASE_URL`, the
`IMOVEIS_*` overrides — reaches `validate.py` / `ship.py`, so an enabled host
still runs a green gate.
The loader filters what it *reads*; it cannot unset a variable you exported in
your own shell before running the gate, so for the `IMOVEIS_*` config-override
channel specifically the suite has a second, origin-independent guard
(`src/tests/conftest.py`, DW-33).

Re-run the installer after moving the repo, rebuilding `.venv`, or upgrading —
it rewrites the same unit name in place. `--uninstall` removes it.

### Scaling Considerations

- **Scraper workers**: Scale horizontally (more replicas)
- **AI workers**: Keep at 2 on a 20 GB card with `OLLAMA_NUM_PARALLEL=2` (monitor VRAM; see setup § Ollama)
- **Database**: Read replicas for analytics, keep writes on primary
- **Redis**: Managed Redis for HA in production

### CI/CD

There is **no merge-gate CI**: code validation is local only
(`python scripts/agent/validate.py`, enforced on push by the stamp guard). GitHub
Actions carries two non-gating workflows:

- `docs.yml` — MkDocs Material site build + Pages deploy on push to `main`.
- `nightly.yml` — external-surface safety nets: the live scraper drift canary
  (`python scripts/agent/validate.py --only scrapers`) and the advisory
  dependency audit (`bash scripts/ops/audit-deps.sh`: `pip-audit` + `npm audit`).

### Docs Deployment

Documentation auto-deploys to GitHub Pages on push to `main`:

```bash
# Local preview
pip install mkdocs-material
mkdocs serve
