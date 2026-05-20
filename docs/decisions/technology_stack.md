# Technology Stack — Scales Karaoke Platform

> **Document**: technology_stack.md  
> **Version**: 1.0-draft  
> **Synthesized from**: researcher decisions, backend API architecture, devops infrastructure, security review, CTO database schema  
> **Last Updated**: 2026-05-19

---

## 1. Executive Summary

The Scales stack is a **hybrid polyglot architecture**: Python/FastAPI for business logic, Node.js/Socket.IO for real-time fan-out, PostgreSQL for persistent cloud storage, SQLite for local resilience, and Flutter for mobile clients. Every technology choice was evaluated against three dimensions: **production readiness**, **offline/edge resilience** (karaoke venues have spotty connectivity), and **multi-tenant isolation**.

---

## 2. Component-by-Component Decisions

### 2.1 Real-Time Layer — Socket.IO over WebSockets

| Decision | Rationale |
|----------|-----------|
| **WebSockets via Socket.IO** | The only protocol that natively handles both KJ→mobile broadcast AND mobile→KJ requests in a single persistent connection. Proven at 50K+ concurrent connections with Redis adapter. |
| Rooms per venue | Each venue is a Socket.IO room (`venue-123`). The KJ connects as a privileged "host" client; mobile singers connect as standard members. |
| Battery impact | Optimized: single persistent connection, ~25s ping/pong. Comparable to SSE; far superior to long-polling. |
| SSE fallback | Available on `GET /events` for clients unable to maintain WebSockets, but primary is always Socket.IO. |

**Why not SSE?** SSE is server-initiated only. To send a song request from mobile to KJ via SSE, you need a separate HTTP POST path, doubling code surface. For a greenfield system, this is unnecessary overhead.

**Why not long-polling?** New HTTP handshake + headers per event. Impossible to scale to 100+ active singers per venue during peak hours. Only acceptable as Socket.IO automatic fallback behind strict firewalls.

---

### 2.2 Backend — Python FastAPI + Node.js Socket.IO Gateway

| Decision | Rationale |
|----------|-----------|
| **Primary API: Python FastAPI** | Auto-generated OpenAPI docs, Pydantic validation, type safety, and Python ubiquity for ML/data tasks (song recommendation, analytics exports). |
| **Real-time Gateway: Node.js + Socket.io** | Node.js event loop is superior for high-frequency WebSocket fan-out. The `socket.io` + `redis-adapter` combination is the most battle-tested real-time stack available. The gateway is intentionally thin (~200–300 lines). |
| **Redis Pub/Sub** | Connects FastAPI and the gateway: business events publish to Redis, gateway subscribes and fans out to venue rooms. Also used for session cache. |
| **Async workers: Celery** | Background jobs (GDPR data exports, retention cleanup, analytics aggregations) run in Celery workers backed by Redis. |

This is **not** two monoliths — it's a primary API service plus a dedicated gateway microservice. Both share PostgreSQL and Redis. The gateway only does: connection management, room routing, heartbeat, and relay.

**Why not pure FastAPI?** Uvicorn WebSocket support exists but the ecosystem (adapters, horizontal scaling libraries) is thinner than Node.js. Python at WebSocket scale requires care with the GIL and process management.

**Why not pure Node.js?** Fine if the team is Node-first. Risk: Python becomes a "guest language" when you later need ML/data pipelines, fragmenting the stack.

---

### 2.3 Database — PostgreSQL (cloud) + SQLite (edge) + PowerSync

| Decision | Rationale |
|----------|-----------|
| **Cloud: PostgreSQL** | JSONB for flexible song metadata, excellent geospatial for venue location queries, mature row-level security for multi-tenancy. |
| **KJ Local: SQLite** | Zero configuration, instant recovery from disk file, portable. A crashed KJ machine rebuilds from a single `.db` file in seconds. |
| **Sync Engine: PowerSync** | Commercial bidirectional sync between PostgreSQL and SQLite. Production-ready. Flutter-native SDK means the _same engine_ powers both KJ resilience and mobile offline-first caching. |
| **Mobile Offline: PowerSync Flutter SDK** | Replicates venue song catalog to mobile SQLite. Song requests queue locally and sync when online. Reactive UI updates as sync state changes. |

**Why not Firestore?** Vendor-locking the entire platform to Firebase for a karaoke app is unnecessary risk. Song catalogs, user queues, and venue hierarchies are deeply relational. NoSQL document modeling introduces consistency bugs.

**Why not PostgreSQL locally (e.g. via Litestream)?** Running Postgres on a Windows/macOS KJ machine is overkill deployment overhead. SQLite is correct for a single-machine local store.

---

### 2.4 Multi-Tenancy — Shared Schema + Row-Level Security (RLS) via venue_id

**Updated 2026-05-19:** This section was revised from "schema-per-tenant" to "RLS with venue_id" to align with ADR-004 (ratified by t_b3c1b205, t_16f64d05, and t_15b21353).

|| Decision | Rationale |
||----------|-----------|
|| **Shared schema + RLS (primary)** | Every operational table carries `venue_id TEXT NOT NULL`. PostgreSQL RLS policies enforce `venue_id = current_setting('app.current_venue_id')`. Single migration path, one PowerSync config, easy cross-tenant analytics. |
|| **Enterprise path: DB-per-tenant** | For venues requiring true isolation (GDPR audits, compliance), migrate to a dedicated RDS instance. Cleaner for audits than schema-per-tenant; easier via logical replication. |

Application middleware sets `SET LOCAL app.current_venue_id = '<uuid>'` per request from the JWT `venue_id` claim.

**Why not schema-per-tenant?** Migration complexity, N-schema drift, harder ops, and PowerSync requires one replication config per schema. The benefits (query plan isolation) do not outweigh the costs for a platform with 1000+ venues.

---

### 2.5 File Storage — Cloudflare R2

| Decision | Rationale |
|----------|-----------|
| **Cloudflare R2** | S3-compatible API. Zero egress fees. For a karaoke app where users view song metadata images and avatars constantly, zero egress is a 10x cost win over S3 at scale. |

R2 Standard class costs $0.015/GB/mo storage and $0 egress. Compare to S3 + CloudFront: ~$0.09/GB egress. A 1000-venue deployment serving avatars would save thousands per month.

**Why not Google Cloud Storage?** No compelling advantage over R2. Higher egress costs. No free tier for read-heavy patterns.

---

### 2.6 Payments — Stripe Connect Standard

| Decision | Rationale |
|----------|-----------|
| **Stripe Connect Standard accounts** | Zero POS liability for Scales. Venues are seller-managed; they handle disputes, refunds, and KYC. Scales takes an `application_fee_percentage` on each transaction. |

Venues onboard themselves via Stripe's hosted onboarding. Scales focuses on karaoke, not money-transmitter licenses.

---

### 2.7 Push Notifications — Firebase Cloud Messaging (FCM)

| Decision | Rationale |
|----------|-----------|
| **FCM via `firebase_messaging` Flutter plugin** | Free for unlimited notifications. Official Flutter SDK maintained by Google. Topic-based messaging maps perfectly to venue rooms (`venue-123-singers`). |

OneSignal is a conditional upgrade path if the marketing team needs A/B testing and in-app messaging later. Migrating from FCM to OneSignal is a plugin swap (2-day refactor).

---

### 2.8 KJ Crash Recovery — PowerSync Periodic Sync + Full State Restore

| Decision | Rationale |
|----------|-----------|
| **5-minute cloud checkpoint via PowerSync** | Queue state, singer history, and current song position sync automatically in the background. At most one song's worth of queue changes could be lost — acceptable for karaoke venues. |
| **Full state restore on restart** | On crash, KJ app pulls complete venue state from cloud and asks: "Resume from here?" with a 10-second countdown. |
| **S3 backup as disaster-recovery path** | SQLite diffs are also checkpointed to S3 for a secondary restore path (PowerSync is the primary; S3 is the backup-of-backup). |

Real-time sync on every queue change was rejected because karaoke venues are often in cellular-dead zones; blocking on network degrades UX.

---

## 3. Cohesive Architecture — All Layers

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USERS                                            │
│  ┌─────────────┐    ┌─────────────┐                                          │
│  │ Mobile App  │    │ KJ Desktop  │                                          │
│  │ (Flutter)   │    │ (Flutter/   │                                          │
│  │             │    │  Desktop)   │                                          │
│  │ ─ SQLite    │    │ ─ SQLite    │                                          │
│  │   (offline) │    │   (local)   │                                          │
│  │ ─ socket_io │    │ ─ socket_io │                                          │
│  │   client    │    │   client    │                                          │
│  │ ─ FCM SDK   │    │ ─ PowerSync │                                          │
│  │ ─ PowerSync │    │   worker    │                                          │
│  └──────┬──────┘    └──────┬──────┘                                          │
│         │                    │                                                │
│         │                    │                                                │
│         │     ┌──────────────▼─────────────────────────────────────┐        │
│         │     │  REAL-TIME GATEWAY                                │        │
│         └─────►  Node.js + Socket.IO + Redis Adapter              │        │
│               │  • Venue room management                          │        │
│               │  • KJ ⟺ mobile message relay                       │        │
│               │  • Presence/heartbeat tracking                       │        │
│               └──────────────┬─────────────────────────────────────┘        │
│                              │                                               │
│         ┌────────────────────┼────────────────────┐                         │
│         ▼                    ▼                    ▼                         │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                  │
│  │   REST API   │◄───│   Redis      │───►│   Celery     │                  │
│  │  (FastAPI)   │    │ (pub/sub +   │    │  (background │                  │
│  │              │    │  session     │    │   jobs)      │                  │
│  │ ─ Auth       │    │  cache)      │    │              │                  │
│  │ ─ Payments   │    └──────────────┘    │ ─ Exports    │                  │
│  │   (Stripe)   │         │              │ ─ Retention  │                  │
│  │ ─ Analytics  │         │              │ ─ Analytics  │                  │
│  │ ─ GDPR APIs  │         │              └──────────────┘                  │
│  │ ─ Multi-tenant│         │                                               │
│  │   RLS (venue_id)│     │                                               │
│  └──────┬───────┘         │                                               │
│         │                 │                                               │
│         ▼                 │                                               │
│  ┌───────────────────────┘                                               │
│  │  PostgreSQL (Multi-region for GDPR)                                  │
│  │  • Shared schema + RLS (venue_id on every table)                     │
│  │  • Aurora Serverless v2 (auto-scale)                                  │
│  └─────────────────────────────────────────────────────────────────────  │
│                                                                           │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Cloudflare R2 (zero-egress file storage)                           │  │
│  │  • Avatars, song artwork, venue branding assets                       │  │
│  │  • Presigned URLs for uploads from mobile/KJ                         │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                           │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  S3 (disaster recovery & CI artifacts)                                │  │
│  │  • KJ SQLite full backups                                             │  │
│  │  • CI/CD build artifacts                                              │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Why This Stack Works Together

1. **FastAPI** builds the business logic quickly; **Node.js** handles the one thing it does better (WebSocket fan-out at scale).
2. **PowerSync** is the single sync engine for both KJ resilience and mobile offline-first. One technology, two solved problems.
3. **Socket.IO rooms** map 1:1 to venues. Broadcasting is `.to('venue-123')`.
4. **Cloudflare R2** keeps image serving costs near-zero, which matters when 100 singers per venue browse avatars and album art all night.
5. **Stripe Connect Standard** offloads payment compliance to Stripe and the venues. Scales focuses on karaoke, not money-transmitter licenses.
6. **FCM** is free, Flutter-native, and sufficient for "your turn" notifications.
7. **RLS with `venue_id`** enforces tenant isolation at the row level without schema-per-tenant complexity. Enterprise tier migrates to dedicated RDS.

---

## 5. Sources

- RxDB: WebSockets vs SSE vs Long Polling vs WebTransport — https://rxdb.info/articles/websockets-sse-polling-webrtc-webtransport.html
- Ably: Long Polling vs WebSockets at Scale — https://ably.com/blog/websockets-vs-long-polling
- PlanetScale: Approaches to Tenancy in Postgres — https://planetscale.com/blog/approaches-to-tenancy-in-postgres
- KodekX: SaaS Tenant Isolation Strategies — https://kodekx-solutions.medium.com/saas-tenant-isolation-database-schema-and-row-level-security-strategies-7337d2159066
- ChargeKeep: Stripe Connect Comparison — https://www.chargekeep.com/stripe-connect-accounts-comparison/
- DigitalApplied: Cloudflare R2 vs AWS S3 (2025) — https://www.digitalapplied.com/blog/cloudflare-r2-vs-aws-s3-comparison
- PowerSync vs ElectricSQL — https://powersync.com/blog/electricsql-vs-powersync
- OneSignal vs FCM — https://onesignal.com/blog/firebase-vs-onesignal/
