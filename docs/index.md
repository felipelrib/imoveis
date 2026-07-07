# Imoveis — Deal Tracker

A local-first real-estate deal-finding tool that scrapes multiple rental/sale platforms (QuintoAndar, OLX), deduplicates listings via geospatial + heuristic matching, tracks price history over time, enriches listings with AI (visual condition, sentiment, statistical valuation), and alerts users to price drops.

## Quick Start

### Using Docker Compose (recommended)

```bash
bash scripts/agent/setup-worktree.sh <feature-slug>
cd .worktrees/<feature-slug>
bash scripts/agent/run-services.sh
# API: http://localhost:$API_PORT/health
# Frontend: http://localhost:$FRONTEND_PORT
```

### Manual setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
createdb realestate_dev && psql realestate_dev -c "CREATE EXTENSION postgis;"
cd alembic && alembic upgrade head && cd ..
uvicorn src.api.main:app --reload
celery -A src.adapters.queue.tasks.celery worker -Q scrapers -c 4
celery -A src.adapters.queue.tasks.celery worker -Q ai -c 1
```

## Tech Stack

- **Backend:** Python FastAPI + Celery workers + Redis broker
- **Database:** PostgreSQL 15 + PostGIS for geospatial queries
- **AI:** Local Ollama models (llava for vision, llama3 for text) with LM Studio fallback
- **Frontend:** React 18 + Vite (dark theme, score-coloured property cards)
- **Infra:** Docker Compose, Alembic migrations, git worktree isolation

## Core Problems Solved

1. Manual house-hunting across multiple platforms is tedious and misses deals
2. Price changes go unnoticed — the best deals appear and disappear fast
3. Raw listing data needs AI enrichment (visual condition, neighbourhood stats) to be actionable
4. No single unified view of properties across platforms with deduplication

## Key Metrics

- Cross-platform dedup accuracy (same property from different sources → one record)
- Time from price drop to alert notification
- AI enrichment throughput (listings/min on single GPU)
- User filter-to-shortlist conversion