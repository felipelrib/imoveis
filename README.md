Local Real-Estate Ingestor

This repository contains a modular ingestion pipeline, heuristic deduplication, PostGIS-backed geospatial storage, and a pluggable local AI enrichment stack. Use the configs/app_config.yaml to configure platforms, Redis and DB.

Quickstart (developer):
- Create Python venv and install dependencies: sqlalchemy, geoalchemy2, httpx, celery, redis, psycopg2-binary
- Start Redis and Postgres(+PostGIS)
- Run alembic migrations (not provided in this skeleton)
- Start API: uvicorn src.api.main:app --reload
- Start Celery workers: celery -A src.adapters.queue.tasks.celery worker -Q scrapers -c 4
- Start AI workers: celery -A src.adapters.queue.tasks.celery worker -Q ai -c 1

See docs/rocm_directml_setup.md for GPU guidance.
