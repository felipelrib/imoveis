# Deployment & Operations Guide

## Overview

This guide covers production deployment, scaling, monitoring, and operational procedures for the Real-Estate ingestion system.

## 1. Production Deployment Strategies

### 1.1 Kubernetes Deployment (Recommended for Scale)

#### Prerequisites
- Kubernetes cluster 1.24+ (GKE, EKS, AKS, or self-hosted)
- kubectl configured
- Helm 3.x
- Container registry (Docker Hub, ECR, ACR, or private)

#### Deployment Architecture
```
┌─────────────────────────────────────────────┐
│         Ingress Controller (nginx)          │
└─────────────────────────────────────────────┘
           ↓              ↓              ↓
    ┌──────────────┬──────────────┬──────────────┐
    │ API Pod (3)  │ API Pod (3)  │ API Pod (3)  │
    └──────────────┴──────────────┴──────────────┘
           ↓              ↓              ↓
    ┌─────────────────────────────────────────┐
    │  Service (ClusterIP - load balanced)    │
    └─────────────────────────────────────────┘
           ↓              ↓              ↓
    ┌──────────────┬──────────────┬──────────────┐
    │Scraper Pod(4)│Scraper Pod(4)│Scraper Pod(4)│
    └──────────────┴──────────────┴──────────────┘
           ↓              ↓
    ┌──────────────────────────────────┐
    │  AI Worker Pod (GPU) (1-2)       │
    └──────────────────────────────────┘
           ↓              ↓              ↓
    ┌─────────────────────────────────────────┐
    │   PostgreSQL (RDS/CloudSQL/Primary)     │
    └─────────────────────────────────────────┘
```

#### Helm Chart Structure
```
realestate-helm/
├── Chart.yaml
├── values.yaml
├── values-dev.yaml
├── values-prod.yaml
└── templates/
    ├── api-deployment.yaml
    ├── api-service.yaml
    ├── api-hpa.yaml
    ├── worker-deployment.yaml
    ├── worker-hpa.yaml
    ├── redis-deployment.yaml
    ├── configmap.yaml
    ├── secrets.yaml
    └── ingress.yaml
```

#### Deployment Commands
```bash
# Add repo
helm repo add realestate https://your-registry.io/helm

# Install to dev
helm install realestate realestate/realestate -f values-dev.yaml -n dev --create-namespace

# Upgrade to prod
helm upgrade realestate realestate/realestate -f values-prod.yaml -n prod

# Scale API replicas
kubectl scale deployment realestate-api --replicas=5 -n prod

# Monitor rollout
kubectl rollout status deployment/realestate-api -n prod

# Rollback on failure
helm rollback realestate 1 -n prod
```

### 1.2 Docker Compose (Development/Testing)

```yaml
version: "3.8"

services:
  postgres:
    image: postgis/postgis:15-3.3
    environment:
      POSTGRES_USER: realestate
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: realestate_prod
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U realestate"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD}
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  ollama:
    image: ollama/ollama:latest
    volumes:
      - ollama_models:/root/.ollama
    environment:
      OLLAMA_MODELS: /root/.ollama/models
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:11434/api/tags"]
      interval: 30s
      timeout: 10s
      retries: 3

  api:
    build:
      context: .
      dockerfile: docker/Dockerfile.api
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://realestate:${DB_PASSWORD}@postgres:5432/realestate_prod
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379/0
      OLLAMA_BASE_URL: http://ollama:11434
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  scraper-worker:
    build:
      context: .
      dockerfile: docker/Dockerfile.worker
    environment:
      DATABASE_URL: postgresql://realestate:${DB_PASSWORD}@postgres:5432/realestate_prod
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379/0
      CELERY_BROKER_URL: redis://:${REDIS_PASSWORD}@redis:6379/0
    command: celery -A src.adapters.queue.celery_app worker -Q scrapers -n scraper-1 --concurrency=4
    depends_on:
      - postgres
      - redis
    deploy:
      replicas: 2

  ai-worker:
    build:
      context: .
      dockerfile: docker/Dockerfile.worker
    environment:
      DATABASE_URL: postgresql://realestate:${DB_PASSWORD}@postgres:5432/realestate_prod
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379/0
      CELERY_BROKER_URL: redis://:${REDIS_PASSWORD}@redis:6379/0
      OLLAMA_BASE_URL: http://ollama:11434
    command: celery -A src.adapters.queue.celery_app worker -Q ai -n ai-worker-1 --concurrency=1
    depends_on:
      - postgres
      - redis
      - ollama
    deploy:
      replicas: 1
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

volumes:
  postgres_data:
  redis_data:
  ollama_models:

networks:
  default:
    name: realestate-network
```

## 2. Environment Configuration

### 2.1 Production Secrets (.env.prod)
```env
# Never commit to version control!
# Use managed secrets services (AWS Secrets Manager, Azure Key Vault, etc.)

ENVIRONMENT=production
LOG_LEVEL=info

# PostgreSQL
DATABASE_URL=postgresql://prod_user:${SECURE_PASSWORD}@managed-postgres.aws.amazon.com:5432/realestate_prod
DATABASE_POOL_SIZE=20
DATABASE_POOL_RECYCLE=3600

# Redis
REDIS_URL=redis://:${REDIS_PASSWORD}@managed-redis.aws.amazon.com:6379/0
REDIS_DB=0

# AI Model
OLLAMA_BASE_URL=http://gpu-server.internal:11434
OLLAMA_MODEL=llama-3-2-vision
OLLAMA_TIMEOUT=120

# Scraping
SCRAPER_RATE_LIMIT_PER_MINUTE=30
SCRAPER_JITTER_MIN=2
SCRAPER_JITTER_MAX=7
SCRAPER_TIMEOUT_SECONDS=30

# GPU Management
GPU_WORKER_CONCURRENCY=2
GPU_SEMAPHORE_TIMEOUT_SECONDS=120
GPU_MEMORY_FRACTION=0.8

# API
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=4
API_TIMEOUT=60

# Monitoring
SENTRY_DSN=https://key@sentry.io/project_id
METRICS_EXPORT_INTERVAL=60
```

### 2.2 Secrets Management Best Practices

#### AWS Secrets Manager
```bash
# Store secret
aws secretsmanager create-secret --name realestate/prod/db-password --secret-string "secure_password"

# Retrieve in application
import boto3
client = boto3.client('secretsmanager')
secret = client.get_secret_value(SecretId='realestate/prod/db-password')
db_password = secret['SecretString']
```

#### Kubernetes Secrets
```bash
# Create secret from file
kubectl create secret generic realestate-secrets --from-file=.env.prod -n prod

# Use in Pod
env:
  - name: DATABASE_URL
    valueFrom:
      secretKeyRef:
        name: realestate-secrets
        key: DATABASE_URL
```

## 3. Scaling Strategies

### 3.1 Horizontal Scaling

#### API Server
- Start with 3 replicas, auto-scale to 10 based on CPU/memory
- Use load balancer (ALB/NLB) for traffic distribution
- Set target group health checks to `/health`

#### Scraper Workers
- Scale to 4-8 replicas based on queue length
- Monitor Redis queue size: `redis-cli LLEN celery`
- Each worker handles 30-50 concurrent requests

#### AI Workers
- Keep at 1-2 replicas (GPU-bound)
- Monitor GPU memory with `nvidia-smi`
- Queue depth indicates if more GPUs needed

### 3.2 Database Scaling

#### Read Replicas
```sql
-- Create read replica (AWS RDS example)
aws rds create-db-instance-read-replica \
  --db-instance-identifier realestate-read-1 \
  --source-db-instance-identifier realestate-primary

-- Point analytics queries to replica
SELECT * FROM properties WHERE created_at > NOW() - INTERVAL '7 days';  -- Primary
-- Route via application logic or read pool
```

#### Connection Pooling
```python
# PgBouncer in front of PostgreSQL
# Database connection in app: postgresql://pgbouncer:6432/realestate

# pgbouncer.ini
[databases]
realestate = host=actual-postgres.aws.com port=5432 dbname=realestate

[pgbouncer]
pool_mode = transaction
max_client_conn = 1000
default_pool_size = 25
min_pool_size = 5
reserve_pool_size = 5
reserve_pool_timeout = 5
```

### 3.3 Cache Layer (Redis)

#### Sentinel for High Availability
```
Sentinel monitors Redis primary/replica
Auto-failover if primary fails
Application uses Sentinel connection string
```

#### Cluster for Horizontal Scaling
```
redis-cluster-node-1.internal:6379
redis-cluster-node-2.internal:6379
redis-cluster-node-3.internal:6379
```

## 4. Monitoring & Observability

### 4.1 Metrics to Track

#### Application Metrics
- API response time (p50, p95, p99)
- Requests per second by endpoint
- Error rate by platform
- Celery task duration (scrape, ai_enrich)
- Queue depth and processing latency

#### Database Metrics
- Connection pool usage
- Query duration (slow queries)
- Transaction rollback rate
- Index hit ratio
- Storage usage growth

#### GPU Metrics
- GPU memory utilization
- GPU compute utilization
- Temperature
- Power consumption

#### System Metrics
- CPU usage per container
- Memory RSS and VSZ
- Disk I/O
- Network throughput

### 4.2 Prometheus Scrape Config

```yaml
# prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'api'
    static_configs:
      - targets: ['api:8000']
    metrics_path: '/metrics'

  - job_name: 'postgres'
    static_configs:
      - targets: ['postgres-exporter:9187']

  - job_name: 'redis'
    static_configs:
      - targets: ['redis-exporter:9121']

  - job_name: 'gpu'
    static_configs:
      - targets: ['dcgm-exporter:9400']
```

### 4.3 Grafana Dashboards

Create dashboards for:
1. **Overview**: API health, queue status, error rate
2. **Performance**: Latencies, throughput, resource usage
3. **Database**: Connections, queries, replication lag
4. **GPU**: Memory, compute, temperature
5. **Business Metrics**: Properties ingested, duplicates found, AI enrichment success rate

### 4.4 Alerting Rules

```yaml
# alert.rules.yml
groups:
  - name: realestate_alerts
    interval: 30s
    rules:
      - alert: APIHighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.05
        for: 5m
        annotations:
          summary: "API error rate > 5%"

      - alert: GPUMemoryFull
        expr: gpu_memory_used_mb / gpu_memory_total_mb > 0.95
        for: 2m
        annotations:
          summary: "GPU memory > 95%"

      - alert: RedisConnPoolExhausted
        expr: redis_connected_clients / redis_maxclients > 0.9
        for: 5m
        annotations:
          summary: "Redis connections > 90%"

      - alert: QueueBacklog
        expr: celery_queue_length > 1000
        for: 10m
        annotations:
          summary: "Celery queue backlog > 1000 tasks"
```

## 5. Backup & Disaster Recovery

### 5.1 Database Backups

#### Automated Backups (AWS RDS)
```bash
# Configure automated backups
aws rds modify-db-instance \
  --db-instance-identifier realestate \
  --backup-retention-period 30 \
  --preferred-backup-window "03:00-04:00"

# Manual snapshot
aws rds create-db-snapshot \
  --db-instance-identifier realestate \
  --db-snapshot-identifier realestate-snapshot-$(date +%Y%m%d)
```

#### Point-in-Time Recovery
```bash
# Restore from snapshot
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier realestate-restored \
  --db-snapshot-identifier realestate-snapshot-20231205
```

### 5.2 Data Replication

```sql
-- Logical replication for near-zero-downtime migrations
CREATE SUBSCRIPTION migrate_sub CONNECTION 'postgresql://source:5432/db' 
  PUBLICATION migrate_pub;

-- Monitor replication lag
SELECT slot_name, restart_lsn, confirmed_flush_lsn 
FROM pg_replication_slots;
```

### 5.3 Redis Persistence

```
# In redis.conf
save 900 1        # 15 min if at least 1 key changed
save 300 10       # 5 min if at least 10 keys changed
save 60 10000     # 1 min if at least 10000 keys changed

# AOF (Append-Only File)
appendonly yes
appendfsync everysec
```

## 6. Incident Response

### 6.1 Common Incidents

#### High API Latency
1. Check API CPU/memory usage
2. Review database slow query log
3. Check Redis connection pool
4. Increase API replicas or database connections

#### Workers Not Processing Tasks
1. Check Celery worker logs: `celery -A app inspect active`
2. Verify Redis connectivity
3. Check task queue depth
4. Restart workers if needed

#### GPU Worker OOM
1. Reduce batch size or model size
2. Use model quantization
3. Add more GPU memory
4. Scale to dedicated GPU node

#### Database Replication Lag
1. Check network latency between primary and replica
2. Monitor replica server resources
3. Optimize heavy queries
4. Increase WAL level if needed

### 6.2 Runbook Template

**Incident**: [Title]

**Severity**: [P1/P2/P3]

**Detection**: [How to detect]

**Investigation**:
1. Step 1
2. Step 2

**Mitigation**:
1. Step 1
2. Step 2

**Resolution**:
1. Step 1
2. Step 2

**Post-Incident**:
- [ ] Root cause analysis
- [ ] Update playbook
- [ ] Implement monitoring

## 7. Maintenance Windows

### 7.1 Database Migrations
```bash
# Backup before migration
aws rds create-db-snapshot --db-instance-identifier realestate

# Run Alembic migration
alembic upgrade head

# Rollback plan
alembic downgrade -1
```

### 7.2 Model Updates
```bash
# Stage new model
ollama pull new-model:latest

# Test with subset of data
celery -A app send_task 'tasks.ai_enrich' --args=['test_prop_id', [], '']

# Gradual rollout
# Update 10% of workers → 50% → 100%
```

### 7.3 Zero-Downtime Deployments
```bash
# Blue-green deployment
1. Deploy to new pods (green)
2. Run smoke tests
3. Switch ingress to green
4. Keep blue for rollback (5 min)
5. Terminate blue

# Canary deployment
1. Deploy to 5% of traffic
2. Monitor error rate
3. Gradually increase to 25%, 50%, 100%
```

## 8. Cost Optimization

### 8.1 Resource Right-Sizing
- API: t3.medium (2 vCPU, 4 GB) → p95 CPU < 60%
- Workers: t3.small (2 vCPU, 2 GB) → scale horizontally
- Database: m5.large (2 vCPU, 8 GB RAM, 100 GB storage) → monitor growth

### 8.2 Scheduled Scaling
```python
# Scale down at night (if offline batch processing)
scheduler.add_job(scale_workers, 'cron', hour=22, kwargs={'replicas': 1})
scheduler.add_job(scale_workers, 'cron', hour=6, kwargs={'replicas': 4})
```

### 8.3 Reserved Instances / Spot Instances
- Use Reserved Instances for stable base load (API, database)
- Use Spot Instances for bursty scraper workers (save 70%)
- Use OnDemand for GPU workers (stability over cost)
