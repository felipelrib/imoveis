# Deployment

## Local Development

The standard workflow uses Docker Compose with isolated worktrees:

```bash
bash scripts/agent/setup-worktree.sh <feature-slug>
cd .worktrees/<feature-slug>
bash scripts/agent/run-services.sh
```

See [Setup Guide](setup.md) for details.

## Production

For a solo/small-team deployment, Docker Compose on a single server is sufficient:

```bash
# Clone and configure
git clone https://github.com/felipelrib/imoveis.git
cd imoveis
cp .env.local.example .env.local
# Edit .env.local with production values

# Start all services
docker compose --env-file .env.local up -d

# Run migrations
docker compose exec api alembic upgrade head
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

## CI/CD

GitHub Actions runs on every push and PR:

- **Linting**: flake8, black, isort
- **Tests**: unit + integration with PostGIS + Redis services
- **Build**: Docker image build verification
- **Security**: bandit + safety checks

### Docs Deployment

Documentation auto-deploys to GitHub Pages on push to `main`:

```bash
# Local preview
pip install mkdocs-material
mkdocs serve
```

For the full deployment guide including Kubernetes, monitoring, and disaster recovery, see the [Linear project document](https://linear.app/felipelrib/project/imoveis-deal-tracker-37f4f47e8f59).