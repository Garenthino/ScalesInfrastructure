# ScalesInfrastructure

Backend infrastructure, API services, and web portal for the Scales karaoke ecosystem.

## Overview

ScalesInfrastructure powers the real-time synchronization, payment processing, and management layer connecting venue KJ software, mobile apps, and web dashboards.

## Services

| Service | Technology | Purpose |
|---------|------------|---------|
| API Gateway | FastAPI | RESTful API, auth, rate limiting |
| Real-time | WebSocket Server | Live queue sync, notifications |
| Web Portal | Next.js | Venue dashboards, analytics, song library |
| Payments | Stripe | Subscriptions, tips, ticket sales |
| Telemetry | Prometheus/Grafana | Metrics, monitoring |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         Clients                              │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────┐ │
│  │ ScalesMobile │  │DragonHost2   │  │    Web Portal       │ │
│  │  (Flutter)   │  │  (Windows)   │  │   (Next.js)         │ │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬──────────┘ │
└─────────┼─────────────────┼─────────────────────┼──────────────┘
          │                 │                     │
          └────────┬────────┴────────┬────────────┘
                   │               │
         ┌─────────▼─────────┐    │
         │   Load Balancer   │────┤
         └─────────┬─────────┘    │
                   │              │
         ┌─────────▼─────────┐   │
         │    API Gateway    │   │
         │    (FastAPI)      │   │
         └─────────┬─────────┘   │
                   │              │
    ┌──────────────┼──────────────┼──────────────┐
    │              │              │              │
┌───▼───┐    ┌────▼────┐    ┌────▼─────┐  ┌────▼────┐
│PostgreSQL│  │  Redis   │    │WebSocket │  │  Stripe   │
│(Primary) │  │ (Cache)  │    │ Server   │  │ (Payments)│
└─────────┘  └─────────┘    └──────────┘  └─────────┘
```

## Repository Structure

```
ScalesInfrastructure/
├── api/                    # FastAPI application
│   ├── routes/
│   ├── models/
│   ├── services/
│   └── main.py
├── websocket/              # WebSocket server for real-time sync
├── web_portal/             # Next.js web application
├── migrations/             # Database migrations
├── docs/                   # Architecture decisions, specifications
├── infra/                  # Terraform, Docker, K8s manifests
└── tests/                  # Integration tests, load tests
```

## Design Documents

- `docs/architecture/` — System architecture decisions
- `docs/api/` — API specifications
- `docs/security/` — Security architecture, compliance
- `docs/sync/` — CRDT sync protocol documentation

## Quick Start

```bash
# API Gateway
cd api
pip install -r requirements.txt
uvicorn main:app --reload

# WebSocket Server
cd websocket
npm install
npm start

# Web Portal
cd web_portal
npm install
npm run dev
```

## Related Repositories

- [ScalesMobile](https://github.com/Garenthino/ScalesMobile) — Flutter mobile apps
- DragonHost2-Hermes — Windows KJ software (private repo)

## License

MIT License - see LICENSE file
