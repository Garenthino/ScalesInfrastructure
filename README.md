# Scales Dev Stack

One-command development environment for the Scales karaoke platform.

## Quick Start

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Start the full stack
docker compose up

# 3. Visit services
- API docs:   http://localhost:8000/docs
- Gateway:    ws://localhost:3001
- Web portal: http://localhost:3000
- Postgres:   localhost:5432
- Redis:      localhost:6379
```

## Services

| Service | Port | Description |
|---------|------|-------------|
| postgres | 5432 | PostgreSQL 16 (persistent volume) |
| redis | 6379 | Redis 7 (pub/sub, session cache) |
| backend | 8000 | FastAPI + Uvicorn (hot reload) |
| gateway | 3001 | Socket.IO server (nodemon reload) |
| web | 3000 | Next.js dev server (HMR) |

## Environment Variables

Copy `.env.example` to `.env` and adjust as needed. No secrets are committed.

## Hot Reload

All code services mount the local source directory and run in dev mode with file-watchers:
- **backend**: `uvicorn --reload`
- **gateway**: `nodemon`
- **web**: Next.js HMR

## Health Checks

Postgres and Redis include Docker healthchecks. Backend and gateway depend on database readiness before starting.

## Persistent Data

- `postgres_data`: Docker volume for PostgreSQL data
- `redis_data`: Docker volume for Redis AOF persistence

## Architecture

See `docs/system_architecture.md` and `docs/infrastructure/infra_arch.md` for production design.
