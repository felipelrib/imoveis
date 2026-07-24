# Setup Guide

## Prerequisites

- Python 3.10+
- PostgreSQL 13+ with PostGIS extension
- Redis 6+
- Git
- Docker & Docker Compose (for containerized workflow)
- Ollama (for local AI enrichment)

## Quick Setup (Recommended)

One command to get everything running:

```bash
./scripts/setup.sh
```

This will:
1. Create `.env.local` from the template (if missing)
2. Install frontend dependencies
3. Build Docker images (postgres, redis, api, workers)
4. Start the full stack with health checks (API + background Vite on :5173)
5. Run Alembic database migrations

### Local API key (required for the SPA)

Favourites, watchlist, saved searches, and admin routes require `API_KEY` on the API
and the **same** value pasted into the sidebar **API credential** field (sessionStorage →
`X-API-Key`). Missing/mismatched keys show up as **401/403** in the browser network tab.

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
| `./scripts/start.sh` | Start stack + background Vite on :5173 (migrations included) |
| `./scripts/stop.sh` | Stop containers and the background Vite process |
| `./scripts/restart.sh` | Stop + start (`--build` rebuilds images; Vite comes back up) |
| `./scripts/test.sh` | Run tests (`unit`, `integration`, `e2e`, or `all`) |
| `./scripts/dev.sh` | Same stack, but Vite in the foreground (Ctrl+C stops UI only) |
| `./scripts/clean.sh` | Tear down + remove volumes (`--all` also removes images) |

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
export OLLAMA_BASE_URL=http://localhost:11434
```

### Start Services

```bash
# API
uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --reload

# Scraper workers (I/O-bound, high concurrency)
celery -A src.adapters.queue.celery worker -Q scrapers -c 4

# AI workers (GPU-bound, low concurrency)
celery -A src.adapters.queue.celery worker -Q ai -c 1
```

## AI Model Setup

### Ollama (Recommended)

```bash
ollama serve  # Runs on http://localhost:11434
ollama pull llama-3-2-vision  # Vision model (~11GB)
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

## Development

### Code Quality (pre-commit)

This project uses [pre-commit](https://pre-commit.com/) for local linting and validation. Install the hooks once after cloning:

```bash
pip install pre-commit
pre-commit install          # runs on commit (isort, flake8, secrets, etc.)
pre-commit install --hook-type pre-push  # runs on push (unit tests, frontend build)
```

After installation, all checks run automatically on every `git commit` and `git push`.
This is the **same** hook set used by the CI `lint` job (`pre-commit/action`) —
run them locally so formatting/lint issues never reach GitHub Actions.

To run all hooks manually:

```bash
pre-commit run --all-files
```

### Testing

```bash
./scripts/test.sh unit        # Unit tests only (fast)
./scripts/test.sh integration # Integration tests (needs running stack)
./scripts/test.sh all         # Everything
./scripts/test.sh unit --args "-v -k test_dedupe"  # Filter tests
```

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
OLLAMA_BASE_URL=http://gpu-host:11434
```

### Scaling Considerations

- **Scraper workers**: Scale horizontally (more replicas)
- **AI workers**: Keep at 1-2 (GPU-bound, monitor VRAM)
- **Database**: Read replicas for analytics, keep writes on primary
- **Redis**: Managed Redis for HA in production

### CI/CD

GitHub Actions runs on every push and PR:
- Linting, tests, Docker build verification, and security checks

### Docs Deployment

Documentation auto-deploys to GitHub Pages on push to `main`:

```bash
# Local preview
pip install mkdocs-material
mkdocs serve
