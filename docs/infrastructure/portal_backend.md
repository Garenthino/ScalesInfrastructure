# Scales Portal — FastAPI Backend

## Stack
- **Python 3.11+**, FastAPI, Uvicorn
- **SQLAlchemy 2.0 (async)** with asyncpg
- **Alembic** for migrations
- **Redis** for sessions, rate limits, pub/sub
- **JWT** auth (python-jose) with refresh tokens

## Architecture
The REST API handles CRUD, auth, payments, analytics, and GDPR exports.
Real-time is delegated to the thin **Socket.IO gateway** in `../gateway/`.

## Structure
```
app/
  main.py              FastAPI app factory, CORS, lifespan
  config.py            Pydantic settings from env
  db.py                Async SQLAlchemy engine + session
  dependencies.py      Auth, tenant, rate-limit deps
  middleware/
    tenant.py          SET LOCAL app.current_venue_id
    rate_limit.py      Token bucket per user/IP
  api/
    auth.py            /auth/login, /auth/refresh, /auth/me
    venues.py          /venues, /venues/{id}/events, /venues/{id}/analytics
    notifications.py   /notifications/campaigns, /notifications/schedule
    products.py        /products, /products/{id}/variants
    reports.py         /reports/exports (async CSV/PDF)
    exports.py         /me/export (GDPR)
    delete.py          /me/delete (GDPR)
  models/              SQLAlchemy ORM models
  schemas/             Pydantic request/response models
  services/            Business logic (Stripe, R2, export generators)
  utils/               Token helpers, validators
```

## Environment Variables
```bash
DATABASE_URL=postgresql+asyncpg://scales:scales@localhost:5432/scales
REDIS_URL=redis://localhost:6379
JWT_SECRET=<256-bit>
JWT_ACCESS_EXPIRY=15m
JWT_REFRESH_EXPIRY=7d
API_PORT=8000
```

## Running
```bash
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```
