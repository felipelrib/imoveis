# Real-Estate Ingestion System - Setup & Deployment Guide

## Overview

This guide covers local development setup, GPU/model configuration, and deployment for the Real-Estate ingestion backend with local Vision-Language Model (VLM) enrichment.

## 1. Development Environment Setup

### Prerequisites
- Python 3.10+
- PostgreSQL 13+ with PostGIS extension
- Redis 6+
- Git

### Installation

#### 1.1 Clone and Create Virtual Environment
```bash
git clone <repo>
cd PyCharmMiscProject
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

#### 1.2 Install Dependencies
```bash
pip install -r requirements.txt
```

#### 1.3 Environment Configuration
Create a `.env` file in the project root:
```env
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/realestate_dev
SQLALCHEMY_ECHO=0

# Redis
REDIS_URL=redis://localhost:6379/0

# API
API_HOST=127.0.0.1
API_PORT=8000

# AI Model
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama-3-2-vision

# Scraping
SCRAPER_RATE_LIMIT_PER_MINUTE=30
SCRAPER_JITTER_MIN=2
SCRAPER_JITTER_MAX=7

# GPU
GPU_WORKER_CONCURRENCY=1
GPU_SEMAPHORE_TIMEOUT_SECONDS=30
```

## 2. Database Setup

### 2.1 PostgreSQL + PostGIS

#### Linux (Ubuntu/Debian):
```bash
sudo apt-get install postgresql postgresql-contrib postgis
sudo systemctl start postgresql

# Connect to psql
sudo -u postgres psql
```

#### macOS (Homebrew):
```bash
brew install postgresql postgis
brew services start postgresql
psql postgres
```

#### Windows (PostgreSQL Installer):
- Download from https://www.postgresql.org/download/windows/
- During installation, ensure "PostGIS" extension is selected
- Start PostgreSQL service via Services or pgAdmin

### 2.2 Create Database and Enable Extensions
```sql
CREATE DATABASE realestate_dev;
\c realestate_dev
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
SELECT postgis_version();  -- Verify installation
```

### 2.3 Run Migrations
```bash
cd alembic
alembic upgrade head
```

## 3. Redis Setup

### Linux/macOS:
```bash
# Using Homebrew (macOS)
brew install redis
brew services start redis

# Using package manager (Ubuntu)
sudo apt-get install redis-server
sudo systemctl start redis-server
```

### Windows:
- Download Redis from https://github.com/microsoftarchive/redis/releases or use Windows Subsystem for Linux (WSL2)
- Or use Docker: `docker run -d -p 6379:6379 redis:7`

### Verify Redis
```bash
redis-cli ping
# Expected output: PONG
```

## 4. Local AI Model Setup

### 4.1 Ollama (Recommended for VLM)

#### Installation
- **Linux/macOS**: `curl -fsSL https://ollama.ai/install.sh | sh`
- **Windows**: Download from https://ollama.ai/download/windows

#### Start Ollama Service
```bash
ollama serve
# Runs on http://localhost:11434 by default
```

#### Pull a Vision Model
```bash
# In a new terminal
ollama pull llama-3-2-vision  # ~11GB
# Or use smaller model
ollama pull moondream  # Vision model, smaller footprint
```

#### Test Ollama
```bash
curl -X POST http://localhost:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama-3-2-vision",
    "prompt": "What is in this image?",
    "stream": false
  }'
```

### 4.2 LM Studio Alternative

1. Download from https://lmstudio.ai
2. Load a quantized VLM model (e.g., `llava-1.6-mistral-7b.Q4_K_M.gguf`)
3. Start local server (typically on `http://localhost:1234`)
4. Update `OLLAMA_BASE_URL` and `OLLAMA_MODEL` in `.env` accordingly

### 4.3 Model Quantization & Optimization

#### Why Quantization?
- Reduces model size (50-75% smaller)
- Faster inference with minimal quality loss
- Fits in consumer GPU VRAM (e.g., RX 7900 XT's 20GB)

#### Using ONNX Runtime for Quantization
```bash
pip install onnx onnxruntime onnxruntime-tools
# Download a model and quantize
python -m onnxruntime.transformers.optimizer --model_name_or_path microsoft/phi-2 --output_dir ./quantized_models --use_gpu
```

#### Ollama Quantization
```bash
# Ollama automatically quantizes models; check available quantizations:
ollama pull llama-3-2-vision:13b-instruct-q4_K_M  # Q4 quantization
```

## 5. Running the Application

### 5.1 Start FastAPI Backend
```bash
cd src
uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
# Visit http://127.0.0.1:8000/docs for interactive API docs
```

### 5.2 Start Celery Workers

#### Scraper Workers (I/O-bound, high concurrency)
```bash
# From project root
celery -A src.adapters.queue.celery_app worker -Q scrapers -n scraper-1 --concurrency=4 --loglevel=info
```

#### AI Workers (GPU-bound, limited concurrency)
```bash
# From project root (run only 1-2 for GPU memory management)
celery -A src.adapters.queue.celery_app worker -Q ai -n ai-worker-1 --concurrency=1 --loglevel=info
```

### 5.3 Start Redis Monitoring (Optional)
```bash
redis-cli monitor
# Shows all Redis commands in real-time
```

## 6. API Usage Examples

### 6.1 Health Check
```bash
curl http://127.0.0.1:8000/health
# Response: {"status":"ok"}
```

### 6.2 Admin Endpoints

#### Pause AI Workers
```bash
curl -X POST http://127.0.0.1:8000/admin/workers/pause
# Response: {"paused":true}
```

#### Resume AI Workers
```bash
curl -X POST http://127.0.0.1:8000/admin/workers/resume
# Response: {"paused":false}
```

#### Scale GPU Concurrency
```bash
curl -X POST http://127.0.0.1:8000/admin/gpu/scale \
  -H "Content-Type: application/json" \
  -d '{"limit": 2}'
# Response: {"gpu_limit":2}
```

#### Check Worker Status
```bash
curl http://127.0.0.1:8000/admin/workers/status
# Response: {"ai_workers_paused":false}
```

## 7. GPU Configuration

### AMD (Windows with DirectML)
See `docs/rocm_directml_setup.md` for detailed AMD GPU setup with DirectML backend.

### NVIDIA
```bash
# Install CUDA Toolkit and cuDNN
# Update requirements.txt torch to CUDA-enabled version
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```

### Monitoring GPU Usage
- **Windows**: Use GPU-Z or Task Manager (Performance tab)
- **Linux (AMD ROCm)**: `rocm-smi` or `radeontop`
- **Linux (NVIDIA)**: `nvidia-smi` (watch mode: `watch -n 1 nvidia-smi`)

## 8. Testing

### Run Unit Tests
```bash
pytest src/tests/unit/ -v
```

### Run Integration Tests
```bash
pytest src/tests/integration/ -v --tb=short
```

### Full Test Suite
```bash
pytest src/tests/ -v --cov=src --cov-report=html
```

## 9. Production Deployment

### 9.1 Docker Deployment

#### Build Images
```bash
docker build -f docker/Dockerfile.api -t realestate-api:latest .
docker build -f docker/Dockerfile.worker -t realestate-worker:latest .
```

#### Docker Compose (Local Testing)
```bash
docker-compose up -d
# Creates api, worker, postgres, redis, ollama services
```

### 9.2 Environment Variables
```env
ENVIRONMENT=production
DATABASE_URL=postgresql://prod_user:secure_password@db-host:5432/realestate_prod
REDIS_URL=redis://redis-host:6379/0
OLLAMA_BASE_URL=http://gpu-server:11434
```

### 9.3 Scaling Considerations
- **Scraper Workers**: Scale horizontally (many concurrent workers)
- **AI Workers**: Keep concurrency low (1-2 per GPU), use separate GPU nodes
- **Database**: Use read replicas for analytics; keep writes on primary
- **Redis**: Use managed Redis (AWS ElastiCache, Azure Cache) for HA

## 10. Monitoring & Logging

### Celery Monitoring
```bash
# Install Flower (web UI for Celery)
pip install flower
celery -A src.adapters.queue.celery_app flower
# Visit http://127.0.0.1:5555
```

### Logs
- **FastAPI**: Logged to stdout (configurable via Python logging)
- **Celery**: See worker console output or configure file logging
- **Database**: Enable query logging in PostgreSQL config

### Health Checks
```bash
# Database connectivity
curl http://127.0.0.1:8000/health

# Redis connectivity
redis-cli ping

# Ollama readiness
curl http://localhost:11434/api/tags
```

## 11. Troubleshooting

### Database Connection Issues
```bash
# Test PostgreSQL connection
psql -U user -h localhost -d realestate_dev -c "SELECT 1"

# Check PostGIS is installed
psql -U user -d realestate_dev -c "SELECT postgis_version()"
```

### Redis Connection Errors
```bash
# Verify Redis is running
redis-cli ping

# Check redis config
redis-cli CONFIG GET "*"
```

### Ollama Model Not Found
```bash
# List available models
ollama list

# Pull model explicitly
ollama pull llama-3-2-vision

# Check logs
# Linux/macOS: ~/.ollama/logs
# Windows: %APPDATA%\Ollama\logs
```

### Out of GPU Memory
- Reduce worker concurrency: adjust `GPU_WORKER_CONCURRENCY` in `.env`
- Use smaller model: `ollama pull moondream` instead of `llama-3-2-vision`
- Enable model quantization (INT8 or Q4)

### Slow Scraping
- Check platform rate limits in `configs/app_config.yaml`
- Increase scraper worker concurrency
- Verify network connectivity to scraping targets

## 12. Configuration Files

### `configs/app_config.yaml` Structure
```yaml
platforms:
  quintoandar:
    base_url: "https://api.quintoandar.com.br"
    enabled: true
    rate_limit: 30  # requests per minute
    jitter_min: 2
    jitter_max: 7

deduplication:
  search_radius_m: 50
  area_tolerance_m2: 2.0
  text_similarity_threshold: 0.65

ai:
  model: "llama-3-2-vision"
  base_url: "http://localhost:11434"
  timeout_seconds: 120
  
scoring:
  weights:
    stat_score: 0.5
    ai_score: 0.5
```

## 13. Additional Resources

- **SQLAlchemy Docs**: https://docs.sqlalchemy.org
- **PostGIS Manual**: https://postgis.net/docs
- **Celery Documentation**: https://docs.celeryproject.io
- **FastAPI Guide**: https://fastapi.tiangolo.com
- **Ollama API Docs**: https://github.com/ollama/ollama/blob/main/docs/api.md
