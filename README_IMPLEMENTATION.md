# Real-Estate Ingestion, Deduplication & VLM Enrichment

**A modular, resilient Python backend for multi-platform real-estate listing aggregation with local Vision-Language Model enrichment.**

## 🎯 Project Overview

This backend system ingests real-estate listings from multiple platforms (QuintoAndar, OLX, etc.), deduplicates them using deterministic heuristics, stores historical price changes in PostgreSQL+PostGIS, and enriches listings with local Vision-Language Models (VLMs) running on a high-end local GPU.

### Key Features
- ✅ **Multi-platform ingestion** via add-on scrapers (QuintoAndar, OLX, etc.)
- ✅ **Intelligent deduplication** using geo-spatial queries, heuristics, and text similarity
- ✅ **Price history tracking** with temporal database views
- ✅ **Local VLM enrichment** (Ollama, LM Studio) for property image analysis
- ✅ **Async task orchestration** via Celery + Redis with GPU resource management
- ✅ **Admin control** for worker management and GPU scaling
- ✅ **Production-ready** with CI/CD, monitoring, and deployment guides

## 🏗️ Architecture

### Clean/Hexagonal Design
```
src/
├── api/                          # FastAPI routers, admin endpoints
├── adapters/                     # External service integrations
│   ├── db/                       # SQLAlchemy ORM models
│   ├── scrapers/                 # Platform-specific scrapers (add-on pattern)
│   │   ├── base.py              # BaseScraper interface
│   │   ├── circuit_breaker.py   # Resilience pattern
│   │   └── quintoandar.py       # Example scraper
│   ├── ai/                       # LocalAIClient abstraction
│   │   └── client.py            # Ollama, LM Studio implementations
│   ├── queue/                    # Celery task definitions
│   └── metrics/                  # Scoring & analytics
├── core/                         # Business logic
│   ├── entities.py              # Domain entities
│   └── dedupe.py                # Deduplication heuristics
└── infra/                        # Infrastructure (DB, Redis, Proxy)
```

### Data Flow
```
[Scraper] → [Normalize] → [Dedupe] → [DB] → [Metrics] → [AI Enrich]
   API        Platform       Core    Persist  Scoring    GPU Worker
  Worker      Adapter      Service   Store   Compute     Async
```

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- PostgreSQL 13+ with PostGIS
- Redis 6+
- GPU with 12GB+ VRAM (recommend 20GB+)

### Installation

#### 1. Clone & Setup Environment
```bash
git clone <repo>
cd PyCharmMiscProject
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

#### 2. Database Setup
```bash
# PostgreSQL + PostGIS
createdb realestate_dev
psql realestate_dev -c "CREATE EXTENSION postgis;"
cd alembic && alembic upgrade head
```

#### 3. Redis
```bash
redis-server  # Or docker run -d -p 6379:6379 redis:7
```

#### 4. Ollama (Local VLM)
```bash
ollama serve &
ollama pull llama-3-2-vision
```

#### 5. Run Application

**Terminal 1 - API**
```bash
cd src && uvicorn api.main:app --reload
# http://127.0.0.1:8000/docs
```

**Terminal 2 - Scraper Workers**
```bash
celery -A src.adapters.queue.celery_app worker -Q scrapers -n scraper-1 --concurrency=4
```

**Terminal 3 - AI Workers**
```bash
celery -A src.adapters.queue.celery_app worker -Q ai -n ai-worker-1 --concurrency=1
```

### Test API
```bash
curl http://127.0.0.1:8000/health
# {"status":"ok"}

curl http://127.0.0.1:8000/admin/workers/status
# {"ai_workers_paused":false}
```

## 📚 Documentation

### Core Guides
| Document | Purpose |
|----------|---------|
| [SETUP_GUIDE.md](docs/SETUP_GUIDE.md) | Development environment setup, database, GPU configuration |
| [DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md) | Production deployment (Kubernetes, Docker Compose), scaling, monitoring |
| [MODEL_QUANTIZATION.md](docs/MODEL_QUANTIZATION.md) | Model optimization, INT8/INT4 quantization, benchmarking |
| [rocm_directml_setup.md](docs/rocm_directml_setup.md) | AMD GPU setup (DirectML/ROCm) |

## 🔧 Key Components

### Deduplication Engine
```python
from core.dedupe import match_or_create_property

# Automatically detects duplicates using:
# 1. PostGIS spatial query (50m radius)
# 2. Discrete field matching (bedrooms, bathrooms, parking)
# 3. Area tolerance (±2 m²)
# 4. Text similarity (0.65 threshold)
result = match_or_create_property(
    session, 
    incoming_property,
    radius_m=50,
    area_tol=2.0,
    text_threshold=0.65
)
```

### AI Enrichment
```python
from adapters.ai.client import OllamaClient

client = OllamaClient(base_url='http://localhost:11434', model='llama-3-2-vision')

# Analyze property images
visual_analysis = await client.analyze_visuals(['bedroom.jpg', 'kitchen.jpg'])

# Analyze text description
text_analysis = await client.analyze_text('Modern 2BR apartment with ocean view')
```

### Admin Control API
```bash
# Pause AI workers
curl -X POST http://127.0.0.1:8000/admin/workers/pause

# Scale GPU concurrency
curl -X POST http://127.0.0.1:8000/admin/gpu/scale -H "Content-Type: application/json" -d '{"limit": 2}'

# Check status
curl http://127.0.0.1:8000/admin/workers/status
```

## 📊 Database Schema

### Core Tables
- **properties** - Unified property view across platforms
- **price_history** - Temporal price changes
- **metrics_scoring** - Statistical and AI scores
- **platform_configs** - Platform-specific settings
- **platform_checkpoints** - Scraper state for resumption

### Indexes
- `properties(platform, platform_id)` - Fast platform dedup
- `properties(location)` - PostGIS spatial index
- `price_history(property_id)` - History queries
- `metrics_scoring(combined_score)` - Top-N queries

## 🧪 Testing

### Run Tests
```bash
# Unit tests
pytest src/tests/unit/ -v

# Integration tests
pytest src/tests/integration/ -v

# Full suite with coverage
pytest src/tests/ --cov=src --cov-report=html
```

### Test Structure
```
src/tests/
├── unit/
│   ├── test_cb.py              # Circuit breaker
│   └── test_dedupe.py          # Deduplication
└── integration/
    └── test_e2e.py             # End-to-end workflows
```

## 🚢 Deployment

### Local Development
```bash
docker-compose up  # Full stack: API, workers, DB, Redis, Ollama
```

### Production (Kubernetes)
```bash
helm install realestate ./realestate-helm -f values-prod.yaml -n prod
```

### Scaling
- **Scraper workers**: 4-8 replicas (I/O-bound)
- **API servers**: 3-10 replicas (CPU-bound)
- **AI workers**: 1-2 replicas (GPU-bound)
- **Database**: Read replicas for analytics

## 📈 Monitoring

### Key Metrics
- API latency (p50, p95, p99)
- Celery task duration (scrape, ai_enrich)
- Queue depth and backlog
- GPU memory/compute utilization
- Database connection pool usage

### Dashboards
- Grafana for real-time metrics
- Prometheus for scraping
- Flower for Celery monitoring

## 🔐 Security

### Best Practices
- Environment variables for secrets (use AWS Secrets Manager, Azure Key Vault)
- No hardcoded credentials in code
- Rate limiting on public endpoints
- Circuit breaker on scraper failures
- Input validation on all API endpoints

### Secrets Management
```bash
# AWS Secrets Manager
aws secretsmanager create-secret --name realestate/db-password

# Kubernetes
kubectl create secret generic realestate-secrets --from-file=.env.prod
```

## 📋 Configuration

### `configs/app_config.yaml`
```yaml
platforms:
  quintoandar:
    base_url: "https://api.quintoandar.com.br"
    rate_limit: 30  # requests/minute
    enabled: true

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

## 🛠️ Development

### Adding a New Scraper
```python
from adapters.scrapers.base import BaseScraper

class MyPlatformScraper(BaseScraper):
    def start(self):
        # Initialize session, auth, etc.
        pass
    
    def fetch_pages(self, checkpoint):
        # Yield raw listings, update checkpoint
        pass
    
    def normalize(self, raw):
        # Map to canonical Property fields
        pass
```

### Adding a New AI Model
```python
from adapters.ai.client import LocalAIClient

class MyAIClient(LocalAIClient):
    async def analyze_visuals(self, image_paths):
        # Call custom model endpoint
        pass
    
    async def analyze_text(self, text):
        # Process text
        pass
```

## 🐛 Troubleshooting

### Common Issues

#### "Connection refused" on Database
```bash
# Check PostgreSQL
psql -U user -h localhost -c "SELECT 1"

# Verify PostGIS
psql -U user -d realestate_dev -c "SELECT postgis_version()"
```

#### GPU Out of Memory
```bash
# Reduce worker concurrency
# Reduce model size (use Moondream instead of Llama)
# Enable quantization (INT4)
GPU_WORKER_CONCURRENCY=1 celery -A app worker -Q ai
```

#### Slow Scraping
```bash
# Check rate limits
redis-cli LLEN celery  # Queue depth

# Increase scraper concurrency
celery -A app worker -Q scrapers --concurrency=8

# Check platform availability
curl https://api.quintoandar.com.br/
```

## 📞 Support

- **Issues**: GitHub Issues
- **Documentation**: /docs folder
- **API Docs**: http://127.0.0.1:8000/docs (when running)
- **Monitoring**: http://127.0.0.1:5555 (Flower)

## 📝 License

MIT License - See LICENSE file

## 👥 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 🎉 Project Status

**Status**: ✅ All Milestones Complete

- ✅ Design & Architecture
- ✅ Database Schema & Migrations
- ✅ Base Scraper Framework
- ✅ Platform Scrapers (QuintoAndar)
- ✅ Deduplication Engine
- ✅ Celery Queue Setup
- ✅ AI Client & Ollama Integration
- ✅ Scoring Engine
- ✅ Documentation & Setup Guides
- ✅ End-to-End Tests & CI/CD

**Next Steps**: Production deployment, performance tuning, additional platform scrapers.

---

**Built with ❤️ for scalable, local-first real-estate data processing.**
