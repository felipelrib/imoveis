# Setup Guide

## Prerequisites

- Python 3.10+
- PostgreSQL 13+ with PostGIS extension
- Redis 6+
- Git
- Docker & Docker Compose (for containerized workflow)
- Ollama (for local AI enrichment)

## Docker Compose (Recommended)

The recommended workflow uses git worktrees with isolated Docker stacks:

```bash
bash scripts/agent/setup-worktree.sh <feature-slug>
cd .worktrees/<feature-slug>
bash scripts/agent/run-services.sh
```

This sets up:

- PostgreSQL (PostGIS) on a unique port
- Redis on a unique port
- FastAPI backend
- Celery workers (scraper + AI)
- React frontend

Each worktree gets its own ports and Docker containers, so parallel feature work is isolated.

## Manual Setup

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

## Testing

```bash
# Unit tests
pytest src/tests/unit/ -v

# Integration tests
pytest src/tests/integration/ -v --tb=short

# Full validation (backend + frontend)
bash scripts/agent/validate.sh all