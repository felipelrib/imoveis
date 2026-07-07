#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# start.sh — Imoveis stack launcher (Git Bash / zsh migration of start.ps1).
#
#   ./start.sh                 start the full stack (default ports)
#   ./start.sh --stop          stop containers
#   ./start.sh --logs          follow logs
#   ./start.sh --no-frontend   skip the React dev server
#   ./start.sh --model NAME    Ollama VLM model to ensure present
#
# This drives the MAIN checkout on default ports. Parallel agents do NOT use
# this — they use scripts/agent/run-services.sh inside their own worktree.
# ---------------------------------------------------------------------------
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

MODEL="llama3.2-vision"; NO_FRONTEND=0; MODE="up"
while [ $# -gt 0 ]; do
  case "$1" in
    --stop) MODE="stop" ;;
    --logs) MODE="logs" ;;
    --no-frontend) NO_FRONTEND=1 ;;
    --model) MODEL="$2"; shift ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
  shift
done

c() { printf '\033[%sm' "$1"; }
step() { printf '%s\n> %s%s\n' "$(c 36)" "$*" "$(c 0)"; }
ok()   { printf '%s  [OK] %s%s\n' "$(c 32)" "$*" "$(c 0)"; }
warn() { printf '%s  [WARN] %s%s\n' "$(c 33)" "$*" "$(c 0)"; }
fail() { printf '%s  [FAIL] %s%s\n' "$(c 31)" "$*" "$(c 0)" >&2; exit 1; }
dc() { if docker compose version >/dev/null 2>&1; then docker compose "$@"; else docker-compose "$@"; fi; }

if [ "$MODE" = "stop" ]; then step "Stopping all containers..."; dc down; ok "stopped"; exit 0; fi
if [ "$MODE" = "logs" ]; then dc logs -f; exit 0; fi

step "Checking Docker..."
docker info >/dev/null 2>&1 || fail "Docker is not running. Start Docker Desktop first."
ok "Docker is running"

step "Starting PostgreSQL + Redis..."
dc up -d postgres redis
for i in $(seq 1 20); do dc ps postgres | grep -qi healthy && { ok "PostgreSQL healthy"; break; }; sleep 3; done
for i in $(seq 1 10); do dc ps redis    | grep -qi healthy && { ok "Redis healthy"; break; }; sleep 3; done

step "Checking Ollama..."
if curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1; then
  ok "Ollama is running"
else
  warn "Ollama not responding — start it with 'ollama serve' in another terminal"
fi
if curl -fsS http://localhost:11434/api/tags 2>/dev/null | grep -q "$MODEL"; then
  ok "Model $MODEL available"
else
  warn "Model $MODEL not found — pulling (may take a while)..."; ollama pull "$MODEL" || warn "pull failed; continuing"
fi

step "Building images + running migrations..."
dc build api worker_ai worker_scraper
dc run --rm api python -m alembic upgrade head && ok "migrations applied" || warn "alembic failed"

step "Starting API + workers..."
dc up --build -d api worker_ai worker_scraper
for i in $(seq 1 20); do curl -fsS http://localhost:8000/health >/dev/null 2>&1 && { ok "API up at http://localhost:8000"; break; }; sleep 3; done

if [ "$NO_FRONTEND" -eq 0 ]; then
  step "Starting React frontend..."
  ( cd frontend && { [ -d node_modules ] || npm install; } && npm run dev ) &
  sleep 4
  ok "Frontend at http://localhost:5173"
fi

printf '\n%s  [+] STACK RUNNING%s\n' "$(c 35)" "$(c 0)"
echo "      Frontend -> http://localhost:5173"
echo "      API docs -> http://localhost:8000/docs"
echo "      Ollama   -> http://localhost:11434"
echo "  Stop: ./start.sh --stop   Logs: ./start.sh --logs"
