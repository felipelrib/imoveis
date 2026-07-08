# Imoveis — Deal Tracker

A local-first real-estate deal-finding tool that scrapes multiple rental/sale platforms (QuintoAndar, OLX), deduplicates listings via geospatial + heuristic matching, tracks price history over time, enriches listings with AI (visual condition, sentiment, statistical valuation), and alerts users to price drops.

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| API | FastAPI | REST endpoints, admin controls |
| Task Queue | Celery + Redis | Async scraping, AI enrichment |
| Database | PostgreSQL 15 + PostGIS | Geospatial property storage |
| AI | Ollama / LM Studio | Local VLM + text models |
| Frontend | React 18 + Vite | Score-coloured property grid |
| Config | Pydantic + YAML | Single source of truth |
| Migrations | Alembic | Schema versioning |
| CI/CD | GitHub Actions | Tests, lint, build |
| Issue Tracking | Linear | Feature queue, project management |

## Core Problems Solved

1. Manual house-hunting across multiple platforms is tedious and misses deals
2. Price changes go unnoticed — the best deals appear and disappear fast
3. Raw listing data needs AI enrichment (visual condition, neighbourhood stats) to be actionable
4. No single unified view of properties across platforms with deduplication

## Get Started

See the [Setup Guide](setup.md) for full installation instructions, or run:

```bash
./scripts/setup.sh
```

## Key Metrics

- Cross-platform dedup accuracy (same property from different sources → one record)
- Time from price drop to alert notification
- AI enrichment throughput (listings/min on single GPU)
- User filter-to-shortlist conversion