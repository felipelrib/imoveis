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
2. Build Docker images (postgres, redis, api, workers)
3. Start the full stack with health checks
4. Run Alembic database migrations
5. Install frontend dependencies

## Day-to-Day Commands

| Script | What it does |
|--------|-------------|
| `./scripts/start.sh` | Start the stack (builds if needed, runs migrations) |
| `./scripts/stop.sh` | Stop containers (volumes preserved for fast restart) |
| `./scripts/restart.sh` | Stop + start (`--build` to rebuild images) |
| `./scripts/test.sh` | Run tests (`unit`, `integration`, `e2e`, or `all`) |
| `./scripts/dev.sh` | Start backend + frontend dev server (hot-reload) |
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

## Development

### Code Quality (pre-commit)

This project uses [pre-commit](https://pre-commit.com/) for local linting and validation. Install the hooks once after cloning:

```bash
pip install pre-commit
pre-commit install          # runs on commit (isort, flake8, secrets, etc.)
pre-commit install --hook-type pre-push  # runs on push (unit tests, frontend build)
```

After installation, all checks run automatically on every `git commit` and `git push`.
This is the **same** hook set used by pre-commit.ci and the CI `lint` job — running
them locally avoids the bot creating fixup commits on your PR.

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

```bash
./scripts/dev.sh  # Starts backend stack + frontend dev server
```

Or start them separately:
```bash
./scripts/start.sh                    # Backend containers
cd frontend && npm run dev            # Frontend dev server (port 5173)
```

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
