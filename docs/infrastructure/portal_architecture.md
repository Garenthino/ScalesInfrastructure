# Scales Portal Architecture

A multi-tenant web dashboard for venue managers to monitor events, manage merchandise, configure notifications, and analyze performance.

## Overview

| Layer | Technology | Role |
|-------|-----------|------|
| Frontend | React 18 + TypeScript + Vite | Dashboard UI, real-time views |
| State | Zustand (sync) + SWR (server) | Lightweight, no Redux needed |
| Styling | Tailwind CSS + CSS variables | Venue theming via runtime tokens |
| REST API | Python (FastAPI) + Uvicorn | CRUD, auth, payments, analytics, GDPR |
| Real-time Gateway | Node.js + Socket.IO + Redis adapter | Venue rooms, fan-out, auto-reconnect |
| Database | PostgreSQL 15+ | Multi-tenant with RLS |
| Cache | Redis | Session, rate limits, pub/sub between API and gateway |
| Storage | Cloudflare R2 (S3-compatible) | Merch images, export files |
| Exports | Puppeteer (PDF) + fast-csv (Python) | Report generation |

> **Cross-references:**
> - Tech stack rationale: `t_f9f964d4` (decisions.md) — ratified Python/FastAPI + Node.js/Socket.IO hybrid.
> - Real-time protocol details: `t_4cbc5dac` (rt_comm_strategy.md) — Socket.IO rooms, fallback chain, Redis Streams sync.

## Multi-Tenancy Strategy: Row-Level Security (RLS)

**Ratified by ADR-004 (2026-05-19):** The canonical multi-tenancy model for Scales is shared-schema RLS via `venue_id` (or `tenant_id` for platform-level entities). Schema-per-tenant was evaluated and rejected. See `ADR-004-multi-tenancy-strategy.md` for the decision record.

```
Every table has tenant_id (UUID FK → tenants.id).
RLS policies enforce: current_setting('app.current_tenant') = tenant_id::text
Connection pooler (PgBouncer) sets tenant per request via SET LOCAL.
```

Advantages over schema-per-tenant:
- Single migration path, no N-schema drift
- Shared connection pool, better resource usage
- Cross-tenant analytics easier (WHERE tenant_id IN ...)
- One backup/restore story

Trade-off: queries must include tenant_id; ORM must emit it automatically.

## Project Structure

```
scales-portal/
├── frontend/               # React SPA
│   ├── src/
│   │   ├── components/     # Reusable UI (atoms/molecules/organisms)
│   │   ├── pages/          # Route-level views
│   │   ├── hooks/          # Custom React hooks
│   │   ├── services/       # API clients, Socket.IO manager
│   │   ├── stores/         # Zustand stores
│   │   ├── types/          # Shared TS types (mirror shared/)
│   │   └── utils/          # Helpers, validators
│   ├── public/             # Static assets
│   └── vite.config.ts
├── backend/                # Python FastAPI (REST API)
│   ├── app/
│   │   ├── api/            # Route handlers
│   │   ├── dependencies.py # Auth, tenant, rate-limit deps
│   │   ├── middleware/     # TenantRLS, RateLimit middleware
│   │   ├── models/         # SQLAlchemy ORM
│   │   ├── schemas/        # Pydantic request/response
│   │   ├── services/       # Business logic (Stripe, R2, exports)
│   │   └── utils/          # Token helpers, validators
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── tests/
├── gateway/                # Node.js Socket.IO (thin WebSocket gateway)
│   ├── src/
│   │   └── index.ts        # Room management, JWT auth on connect
│   ├── Dockerfile
│   └── package.json
├── database/
│   ├── migrations/         # Sequential SQL migrations
│   ├── seeds/              # Development fixtures
│   └── schemas/            # ER diagrams, DDL snapshots
├── shared/
│   └── types/              # Source-of-truth TS types
└── infra/
    ├── docker-compose.yml  # Dev stack (postgres, redis, minio, backend, gateway, frontend)
    ├── nginx.conf           # Reverse proxy + WebSocket upgrade
    └── k8s/                 # Deployment manifests (optional)
```

## Authentication Flow

```
User → POST /api/auth/login (email + password)
API → issue JWT (access + refresh) with venue_id claim
Frontend → stores access token in memory; refresh in httpOnly cookie
Every API request → Authorization: Bearer ***
API middleware → verify JWT → extract venue_id → SET LOCAL app.current_venue_id
Database RLS → rows filtered to that tenant automatically
```

## Real-Time Hub (Socket.IO)

**Protocol: Socket.IO over WebSockets with HTTP long-polling fallback.**

The thin Node.js gateway manages venue rooms and message routing.
The FastAPI backend publishes events to a Redis pub/sub channel
(`scales:api:broadcasts`) which the gateway consumes and fans out.

```
Client connects to ws://gateway:3001, authenticates via JWT (token in auth handshake).
Gateway joins socket to room 'venue:{venue_id}' on successful auth.
Venue room contains all connected clients (web dashboard, mobile web, KJ host).
KJ host gets additional room 'venue:{venue_id}:host' for host-privileged messages.
```

**Fallback chain (handled automatically by Socket.IO client):**
```
WebSocket (wss://) → HTTP/2 SSE → Long Polling → Manual Refresh
```

**Client-side config:**
```javascript
const socket = io('wss://gateway.scales.com', {
  auth: { token: '<JWT>' },
  transports: ['websocket', 'polling'],
  reconnectionDelayMax: 30000,
})
```

**Backend publish pattern (FastAPI):**
```python
redis_client.publish("scales:api:broadcasts", json.dumps({
    "venueId": str(venue_id),
    "event": "QUEUE_DIFF",
    "payload": {...diff...}
}))
```

**Latency targets:** P99 < 1s from API mutation to client receipt. See `t_4cbc5dac` for detailed SLIs, sequence-number sync, and Redis Streams gap recovery.

## Venue Branding System

Each tenant configures:
- Primary / secondary / accent colors
- Logo asset URL
- Custom CSS overrides (stored as validated string)
- Favicon

Stored in `tenant_config` table. On login, frontend fetches config and injects CSS variables into `:root` before first paint.

```css
:root {
  --sp-color-primary:   #<tenant-primary>;
  --sp-color-secondary: #<tenant-secondary>;
  --sp-logo-url:        url(<tenant-logo>);
}
```

Tailwind config extends colors to read from these variables. No per-tenant build required.

## Push Notification Management

Frequency limits enforced at the service layer:
- Global venue cap: X notifications per user per hour (configurable)
- Per-campaign throttle: minimum interval between re-sends
- Burst protection: exponential backoff on failures

Tables: `notification_templates`, `notification_campaigns`, `notification_logs`.

## Merch Catalog + Dropshipper Integration

```
Catalog tables: products, variants, inventory
Dropshipper: HTTP webhook/API per vendor (Printful, Gooten, etc.)
Sync: scheduled job pulls catalog + pricing → writes to products table
Order flow: customer order → create draft in dropshipper API → hold inventory
```

## Analytics & Reports

Analytics dashboard: aggregated metrics served from materialized views (refreshed every 5 min).

Export jobs (async):
- CSV: fast-csv stream from query → upload to R2 → notify via Socket.IO
- PDF: Puppeteer renders HTML template → PDF → upload to R2 → notify

## Technology Selection Rationale

| Decision | Choice | Why |
|----------|--------|-----|
| Frontend framework | React | Team familiarity; Vite for fast HMR |
| State | Zustand + SWR | Simple, boilerplate-free; SWR for caching/refetching |
| REST API | FastAPI (Python) | Auto-generated OpenAPI, Pydantic validation, ML/data integration ready |
| Real-time gateway | Node.js + Socket.IO | Gold-standard WebSocket rooms, Redis adapter for horizontal scaling |
| Tenancy | PostgreSQL RLS | Simpler ops than schema-per-tenant |
| WebSocket transport | Socket.IO | Auto-reconnect, fallback chain, room semantics built-in |
| Jobs | Celery (Python) | Redis-backed, reliable, retry logic |
| Exports | Puppeteer + fast-csv | Proven, no paid dependencies |
| File storage | Cloudflare R2 | Zero egress cost for read-heavy patterns (avatars, album art) |

See `t_f9f964d4` for full stack decision record including trade-off analysis for FastAPI vs Fastify, Socket.IO vs SSE, and PowerSync vs ElectricSQL.

## Environment Variables

```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:***@localhost:5432/scales

# Redis
REDIS_URL=redis://localhost:6379

# Auth
JWT_SECRET=<random-256-bit>
JWT_ACCESS_EXPIRY=15m
JWT_REFRESH_EXPIRY=7d

# Storage
S3_ENDPOINT=http://localhost:9000
S3_BUCKET=scales-exports
AWS_ACCESS_KEY_ID=minio
AWS_SECRET_ACCESS_KEY=minio123

# Socket.IO Gateway
GATEWAY_PORT=3001
GATEWAY_RECONNECT_DELAY_MAX=30000
GATEWAY_PING_INTERVAL=25000
GATEWAY_PING_TIMEOUT=60000

# Notifications
NOTIF_GLOBAL_RATE_LIMIT=10
NOTIF_WINDOW_SECONDS=3600
```
