# Scales FastAPI Backend

> Sprint 0 scaffold for the Scales Karaoke Platform REST API.

## Stack

- **FastAPI** — REST framework with auto-generated OpenAPI docs
- **SQLAlchemy 2.0** — async ORM with `asyncpg` driver
- **Alembic** — database migrations
- **Pydantic** — request/response validation and settings management
- **PostgreSQL** — primary database (Aurora Serverless v2 in prod)
- **Redis** — session cache + Celery broker (future)
- **Docker** — containerized local development

## Project Structure

```
app/
  core/
    config.py      # Pydantic settings (.env driven)
    db.py          # Async engine, session factory, declarative base
    logging.py     # Structured logging via structlog
  models/
    __init__.py    # All 27 SQLAlchemy ORM models (portable SQL)
  schemas/
    __init__.py    # Pydantic request/response DTOs per domain
  routers/
    venues.py      # Venue management endpoints
    songs.py       # Song catalog endpoints
    singers.py     # Singer / patron endpoints
    queue.py       # Karaoke request queue endpoints
    loyalty.py     # Points, tiers, quests
    commerce.py    # Merchandise / Stripe checkout
    social.py      # Leaderboards / sharing
    analytics.py   # Venue analytics endpoints
  api/
    health.py      # /health check
    router.py      # Aggregates all domain routers under /v1
  main.py          # FastAPI app factory with lifespan
docker-compose.yml # PostgreSQL + Redis + API services
Dockerfile         # Multi-stage build (slim Python image)
alembic/           # Migration scripts + env.py
requirements.txt   # Frozen / range deps
.env.example       # Copy to .env and override locally
tests/             # pytest-asyncio tests (future)
```

## Dev Setup

### 1. Clone & Configure

```bash
git clone https://github.com/Garenthino/ScalesInfrastructure.git
cd ScalesInfrastructure

cp .env.example .env
# Edit .env if you want to override defaults
```

### 2. Docker Compose (recommended)

```bash
docker compose up --build
```

This brings up:
- PostgreSQL on `localhost:5432`
- Redis on `localhost:6379`
- API on `http://localhost:8000`

The API container auto-runs `alembic upgrade head` on startup.

### 3. Local Python (no Docker)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start PostgreSQL (or adjust DATABASE_URL in .env)
docker run -d --name scales-db \
  -e POSTGRES_USER=scales \
  -e POSTGRES_PASSWORD=scales \
  -e POSTGRES_DB=scales \
  -p 5432:5432 \
  postgres:16-alpine

# Run migrations
alembic upgrade head

# Start server
uvicorn app.main:app --reload
```

## Verification

```bash
curl http://localhost:8000/health
curl http://localhost:8000/docs     # OpenAPI (dev only)
```

## Database Principles

- **UUID TEXT primary keys** — app-generated, portable across SQLite and PostgreSQL
- **venue_id on every tenant table** — enables RLS multi-tenancy
- **ISO 8601 TEXT timestamps** — application is the clock source of truth
- **Booleans as INTEGER 0/1** — portable across SQLite↔PostgreSQL
- **JSON stored as TEXT** — upgradeable to JSONB in PostgreSQL via migration
- **Soft deletes** via `deleted_at` (NULL = active)

## Migrations

```bash
# Auto-generate from models
alembic revision --autogenerate -m "description"

# Apply
alembic upgrade head

# Rollback one
alembic downgrade -1
```

## Testing

```bash
pytest -v
```

## Architecture Context

This is the **primary REST API** in the Scales polyglot stack. It handles:
- Auth, payments, analytics
- Multi-tenant data with `venue_id` RLS
- Business events published to Redis for the Node.js Socket.IO gateway to fan-out

See `docs/` in the repo for full architecture, API specification, and ADRs.

## Next Steps (Sprint 1+)

- [ ] JWT auth middleware + role-based access control
- [ ] PostgreSQL RLS policy setup + `SET LOCAL app.current_venue_id`
- [ ] Redis pub/sub integration for gateway events
- [ ] Celery worker scaffold for background jobs
- [ ] Stripe webhook handlers
- [ ] Unit + integration tests with `pytest-asyncio`

## License

MIT
