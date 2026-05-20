# Scales Technology Stack Decisions

## Executive Summary

| Decision | Recommendation | Confidence |
|----------|----------------|------------|
| 1. Real-time Protocol | **WebSockets (Socket.IO)** | High |
| 2. Backend Stack | **Python/FastAPI primary + Node.js/Socket.IO gateway** | High |
| 3. Database | **PostgreSQL (cloud) + SQLite (KJ) + PowerSync** | High |
| 4. KJ Crash Recovery | **Periodic cloud sync (5-min) + full state restore** | Medium |
| 5. Offline-first Mobile | **SQLite cache + request queueing + optimistic updates** | High |
| 6. Multi-tenancy | **Shared schema with Row-Level Security (RLS) via `venue_id`** | High |
| 7. Payment | **Stripe Connect Standard accounts** | High |
| 8. GDPR/CCPA | **API-first compliance: export + deletion endpoints** | Medium |
| 9. Push Notifications | **Firebase Cloud Messaging (FCM)** | High |
| 10. File Storage | **Cloudflare R2** | High |

---

## 1. Real-time Protocol: KJ -> Mobile Broadcast & Mobile -> KJ Requests

### The Dual-Stream Problem
Scales needs TWO distinct real-time channels simultaneously:
- **KJ -> Mobile**: Broadcasting "now playing", queue updates (one-to-many, server push)
- **Mobile -> KJ**: Incoming song requests, tips, reactions (client push, many-to-one)

### Options Ranked

#### GO: WebSockets (via Socket.IO)
| Factor | Assessment |
|--------|------------|
| Battery Impact | Low when optimized: single persistent connection; ping/pong every ~25s. SSE with polyfills drains similarly. Long-polling worse (new HTTP per message). |
| Scalability | Proven at 50K+ concurrent connections with Redis adapter. Socket.IO handles reconnects, fallbacks, rooms natively. |
| Bidirectional | Natively supports both KJ->mobile broadcast AND mobile->KJ requests in a single connection per venue. |
| Mobile Fit | Flutter has first-class socket_io_client package. iOS/Android keepalive works with background modes. |
| Reasoning | **The only protocol that natively handles both broadcast and interactive directions without dual-connection complexity.** SSE would need a second path (HTTP POST) for mobile->KJ, doubling code surface. Long-polling is unsustainable for song request bursts. |

#### CONDITIONAL GO: SSE (Server-Sent Events) + HTTP POST
| Factor | Assessment |
|--------|------------|
| Battery Impact | Marginally better than raw WebSockets (only server-initiated heartbeats). |
| Scalability | Simpler horizontal scaling — stateless HTTP can be served by CDN edge workers. |
| Bidirectional | **Requires TWO technologies**: SSE for KJ->mobile stream, separate HTTP endpoints for mobile->KJ. Adds client and server complexity. |
| Mobile Fit | Native EventSource on mobile is limited to GET; POST song requests need fetch/fetch-event-source polyfill. |
| Reasoning | Acceptable if your team already runs an event-sourcing architecture. Adds architectural overhead that Scales, as a greenfield system, should avoid. |

#### NO GO: Long Polling
| Factor | Assessment |
|--------|------------|
| Battery Impact | Worst of all — new HTTP handshake + headers per event. Measurable drain on mobile under active use. |
| Scalability | Impossible to scale to venues with 100+ active singers during peak hours. Connection overhead dominates. |
| Reliability | High risk of missed "now playing" updates during reconnect gaps. Karaoke timing is user-facing. |
| Reasoning | Only useful as a Socket.IO fallback for corporate firewalls. Not a primary strategy. |

### Final Decision
**Socket.IO over WebSockets** for the real-time layer. It provides rooms (one room per venue), automatic reconnection, and a mature Flutter client. The KJ desktop app connects as a privileged "host" client; mobile singers connect as standard clients in the same room.

---

## 2. Backend Stack

### Options Ranked

#### GO: Hybrid — FastAPI (main API) + Node.js (Socket.IO gateway)
| Factor | Assessment |
|--------|------------|
| Async Handling | FastAPI's `async/await` gives Pythonic concurrency for DB-heavy operations. Node.js event loop is superior for high-frequency WebSocket fan-out. |
| WebSocket Maturity | Socket.IO is the gold standard. Node.js libraries (socket.io + redis-adapter) have been production-hardened for years. Python socket.io libraries exist but are less battle-tested at scale and have narrower ecosystem. |
| Developer Velocity | FastAPI's auto-generated OpenAPI docs, Pydantic validation, and type safety dramatically speed API development. Python is ubiquitous for ML/data tasks (song recommendation, analytics). |
| Team Size Impact | A small team benefits from FastAPI's scaffolding speed. The Node.js gateway is thin (~200 lines) and maintainable. |
| Reasoning | **Best of both worlds.** FastAPI handles CRUD, auth, payments, song metadata, analytics. A lightweight Node.js service handles exclusively the WebSocket gateway — venues connect, rooms are managed, messages are routed. Use Redis as the pub/sub backbone between FastAPI and the gateway. |

#### CONDITIONAL GO: Pure Node.js/Express
| Factor | Assessment |
|--------|------------|
| Async Handling | Native event loop is excellent for I/O-bound workloads. CPU-bound tasks (analytics, ML) require worker threads or external services. |
| WebSocket Maturity | Unmatched. socket.io + Express is the most deployed real-time stack on the internet. |
| Developer Velocity | Good for JavaScript/TypeScript teams; poor if the team is Python-native. |
| Reasoning | Fine if the team is already Node-first. Risk: Python becomes a "guest language" when you later need ML/data pipelines, fragmenting the stack. |

#### CONDITIONAL GO: Pure FastAPI
| Factor | Assessment |
|--------|------------|
| Async Handling | Uvicorn + ASGI handles concurrency well for HTTP. WebSocket support exists but the ecosystem (adapters, scaling libraries) is thinner than Node.js. |
| WebSocket Maturity | Acceptable for <1000 concurrent connections. Running Python at WebSocket scale requires care with GIL and process management. |
| Developer Velocity | Excellent for API-only. Adding WebSocket rooms and horizontal scaling is where friction appears. |
| Reasoning | Viable for an MVP with <20 venues. Plan a migration to the hybrid model before hitting scale. |

#### NO GO: Pure Go
| Factor | Assessment |
|--------|------------|
| Async Handling | Goroutines are the best concurrency primitive here. Fastest raw performance. |
| WebSocket Maturity | gorilla/websocket is solid. But the ecosystem for auth, ORMs, and billing plugins is immature compared to Python/Node. |
| Developer Velocity | Slowest for a small team. Every feature is hand-rolled. |
| Reasoning | Revisit Go for a dedicated high-throughput microservice later (e.g., a payment ledger or ML inference worker). Not the right choice for the core platform where velocity matters. |

### Final Decision
**Hybrid: Python/FastAPI for REST API + Node.js/Socket.IO for real-time gateway.** The Node.js service is <5% of total code surface but handles 100% of the critical-path real-time traffic. Database (PostgreSQL) and cache (Redis) are shared.

---

## 3. Database Strategy

### Options Ranked

#### GO: PostgreSQL (cloud) + SQLite (KJ local) + PowerSync
| Factor | Assessment |
|--------|------------|
| Cloud Database | PostgreSQL is the default choice: JSONB for flexible song metadata, excellent geospatial for venue location queries, mature row-level security for multi-tenancy. |
| KJ Local Database | SQLite is perfect for a single-machine karaoke setup: zero configuration, instant recovery from disk file, portable. |
| Sync Strategy | **PowerSync** (commercial) or **ElectricSQL** (open-source, recently re-architected) provide bidirectional sync between Postgres and SQLite. PowerSync has Flutter-native support and is production-ready today. |
| Offline-first Mobile | The same sync engine (PowerSync) that keeps KJ local<->cloud in sync can power the mobile app's offline SQLite cache. |
| Reasoning | **One sync strategy serves both KJ and mobile.** SQLite on KJ means the machine still works if internet drops. PowerSync syncs in the background when connectivity returns. |

#### CONDITIONAL GO: PostgreSQL (cloud) + PostgreSQL (KJ local via litestream)
| Factor | Assessment |
|--------|------------|
| KJ Local Database | Running Postgres on a Windows/macOS KJ machine is overkill deployment overhead. |
| Sync Strategy | Litestream can stream SQLite WAL to S3, but it's unidirectional (backup, not sync). |
| Reasoning | SQLite for local is correct. The question is sync tooling. PowerSync is purpose-built for this. |

#### NO GO: MongoDB/Firestore
| Factor | Assessment |
|--------|------------|
| Offline-first | Firestore has offline support, but vendor-locking the entire platform to Firebase for a karaoke app is unnecessary risk. |
| Relational Fit | Song catalogs, user queues, and venue hierarchies are deeply relational. NoSQL document modeling introduces subtle consistency bugs. |
| Reasoning | The user already configured Feishu — avoid adding another vendor lock-in from Google Firebase at the database layer. |

### Final Decision
**PostgreSQL (cloud) + SQLite (KJ) + PowerSync.** PowerSync's Flutter SDK and Postgres backend sync solve the offline-first requirement for both KJ machine resilience and mobile caching.

---

## 4. KJ Crash Recovery

### Options Ranked

#### GO: Periodic cloud sync (5-minute) + full state restore
| Factor | Assessment |
|--------|------------|
| Sync Frequency | Every 5 minutes: queue state, singer history, current song position, and settings are synced to PostgreSQL. |
| Full State Restore | On restart, the KJ app pulls the complete venue state from cloud and asks the KJ: "Resume from here?" with a 10-second countdown. |
| Downtime Tolerance | A 5-minute window means at most one song's worth of queue changes could be lost. Karaoke venues accept this (singers re-request). |
| Reasoning | **Balance of simplicity and safety.** Real-time sync on every queue change would be fragile network overhead. PowerSync handles the periodic sync automatically. The "resume from cloud" UI is a single confirmation dialog. |

#### CONDITIONAL GO: Real-time sync on every state change
| Factor | Assessment |
|--------|------------|
| Data Loss | Zero — every song add, remove, re-order is persisted immediately. |
| Network Dependency | If the KJ machine is offline (common in basements/bars), every operation blocks or queues, degrading UX. |
| Reasoning | Only worthwhile if you can guarantee venue internet. Karaoke is often in cellular-dead zones or overloaded WiFi. Not worth the fragility. |

#### NO GO: No sync, local-only
| Factor | Assessment |
|--------|------------|
| Data Loss | Complete loss on crash. 10,000+ song libraries gone (this is a known karaoke software pain point per Reddit reports). |
| User Impact | KJ must manually rebuild queue. Audience waits. Venue revenue stops. |
| Reasoning | Unacceptable. Cloud backup is table stakes. |

### Final Decision
**PowerSync-based 5-minute periodic sync with full state restore on restart.** The KJ app keeps a local SQLite journal; PowerSync's background worker syncs deltas. On crash, the KJ app reads from cloud and rebuilds local state.

---

## 5. Offline-first Mobile

### Strategy: SQLite Cache + Request Queueing + Optimistic Updates

#### GO: PowerSync Flutter SDK
| Factor | Assessment |
|--------|------------|
| Cached Song DB | PowerSync replicates a subset of the venue's song catalog to the mobile SQLite. Users search/browse offline. |
| Request Queueing | Song requests, tips, ratings are written to SQLite immediately. PowerSync queues them for upload when online. |
| Stale Data | Song metadata freshness is acceptable: artists/albums don't change often. A "last synced at" timestamp is shown. |
| Sync Conflicts | PowerSync uses timestamp-based last-write-wins with optional custom conflict resolvers. For karaoke: queue position conflicts are resolved server-side (the KJ's screen is the source of truth). |
| Reasoning | **PowerSync is purpose-built for this exact pattern.** It replaces hand-rolled REST + local cache with a reactive sync engine. |

#### CONDITIONAL GO: Custom REST + Hive/Drift local cache
| Factor | Assessment |
|--------|------------|
| Flexibility | Full control over conflict resolution and caching logic. |
| Complexity | Estimated +3 weeks of dev time for a robust offline queue, retry logic, and conflict resolution. PowerSync solves this in days. |
| Reasoning | Only if budget absolutely prohibits a sync engine license. PowerSync has a generous free tier. |

#### NO GO: Firestore offline mode
| Factor | Assessment |
|--------|------------|
| Vendor Lock-in | Locks mobile offline into Firebase. See Database decision. |
| Query Flexibility | Firestore's offline query capabilities are limited compared to SQLite (no full-text search, no joins). |
| Reasoning | Not worth the lock-in for a problem with a superior open-source/commercial solution. |

### Final Decision
**PowerSync Flutter SDK.** It provides offline SQLite with automatic bidirectional sync, conflict resolution, and reactive UI updates (SQFlite-like API with sync built-in).

---

## 6. Multi-tenancy: Venue Isolation

**Updated 2026-05-19:** This section was revised from "schema-per-tenant" to "RLS with venue_id" to align with t_b3c1b205, t_16f64d05, and t_15b21353. See ADR-004 for full rationale.

### Final Decision: Shared Schema + Row-Level Security (RLS) via `venue_id`

**Why:**
- t_b3c1b205 (Database Schema) already implements 27 tables with `venue_id` columns and RLS policies.
- t_15b21353 (Infrastructure) rejected schema-per-tenant due to migration complexity and cost.
- t_16f64d05 (Portal) built auth middleware around `SET LOCAL app.current_venue_id`.
- PowerSync sync engine is simpler with a single schema (one replication config, not per-schema).
- Cross-tenant analytics (platform-wide metrics, churn) are straightforward SQL.

**Enforcement:**
```sql
ALTER TABLE songs ENABLE ROW LEVEL SECURITY;
CREATE POLICY songs_tenant_isolation ON songs
    USING (venue_id = current_setting('app.current_venue_id')::TEXT);
```
Application middleware sets `app.current_venue_id` per-request from JWT claim.

**Enterprise Path:** For venues requiring true isolation (GDPR, compliance), migrate to a dedicated RDS instance (DB-per-tenant) rather than schema-per-tenant. This is cleaner for audits and easier to migrate via logical replication.

---

## 7. Payment: Stripe Connect for Venue Payouts

### Options Ranked

#### GO: Stripe Connect Standard Accounts
| Factor | Assessment |
|--------|------------|
| POS Liability | **Zero for Scales.** Standard accounts are seller-managed. The venue (seller) handles disputes, refunds, and KYC. Scales is just the platform routing payments. |
| Onboarding | Venue clicks a link, creates their own Stripe account in minutes. No dev work for Scales. |
| Fees | Standard Stripe processing fees only. No extra Connect fee per account. |
| Sub-merchant | Each venue is a full Stripe merchant. Scales takes an application_fee_percentage on each transaction. |
| Reasoning | ** Lowest risk, lowest overhead.** Karaoke venues are already handling cash/tips; they're comfortable managing their own Stripe dashboard. |

#### CONDITIONAL GO: Stripe Connect Express Accounts
| Factor | Assessment |
|--------|------------|
| POS Liability | Platform-managed disputes. Scales takes on liability for chargebacks. |
| Onboarding | Stripe handles ID verification; Scales customizes the onboarding flow. |
| Fees | Processing fee + $0.25/account/month (approximate). |
| Control | Platform sets payout schedule (e.g., daily for venues). |
| Reasoning | Consider only if you want to brand the onboarding and control payout timing. Adds liability and operational burden for marginal UX gain. |

#### NO GO: Stripe Standard (non-Connect)
| Factor | Assessment |
|--------|------------|
| Payouts | All money flows to Scales' account. Scales must manually pay venues. |
| Compliance | You become a money transmitter in most jurisdictions. Legal nightmare. |
| Reasoning | Never use this model for marketplace/platform payouts. It's for e-commerce where you're the seller. |

### Final Decision
**Stripe Connect Standard accounts.** Venues onboard themselves, Scales takes a platform fee (e.g., 5% + $0.30), Stripe handles the rest.

---

## 8. GDPR/CCPA Compliance

### Strategy: API-first compliance

### Requirements
- **Data Export**: User requests their data; system generates a ZIP with their song history, requests, tips, and profile.
- **Data Deletion**: Right to be forgotten. Cascade delete across all tenant schemas where the user appears.
- **Retention Policies**: Automatic purging of inactive accounts after X years (configurable per jurisdiction).

### Implementation
| Decision | Rationale |
|----------|-----------|
| **PostgreSQL for data residency** | Deploy EU region PostgreSQL for EU venues; US region for US venues. Stripe Connect handles payment data residency separately. |
| **Export API** | FastAPI endpoint: `/me/export` triggers a background job (Celery/RQ) to collate user data from all schemas into a JSON + CSV bundle stored in R2. User receives a signed download link via email. |
| **Deletion API** | `/me/delete` soft-deletes immediately (anonymizes profile), hard-deletes after a 30-day grace period per GDPR Article 17. |
| **Retention** | Cron job queries for inactive users (no login for 3 years) and queues them for deletion. |

### Confidence
Medium. Compliance is a moving target. Budget for a privacy lawyer review before public launch. The technical architecture (API endpoints + cron + data residency regions) is sound, but policy language and DPA agreements need professional review.

---

## 9. Push Notifications

### Options Ranked

#### GO: Firebase Cloud Messaging (FCM)
| Factor | Assessment |
|--------|------------|
| Flutter Support | Official firebase_messaging plugin maintained by Google. First-class integration. |
| Cost | Free for unlimited notifications. The only truly free enterprise-grade push service. |
| Vendor Lock-in | Yes, but it's Google. Push notifications are already a commodity; switching to a different provider is a 2-day refactor using the flutter_local_notifications bridge. |
| Features | Topic-based messaging ("venue-123-singers"), data-only notifications (silent pushes for sync triggers), rich images. |
| Reasoning | **FCM is the default choice for Flutter apps.** OneSignal is just FCM + a dashboard on top. For a developer-built product like Scales, the extra dashboard isn't worth the per-message cost. |

#### CONDITIONAL GO: OneSignal
| Factor | Assessment |
|--------|------------|
| Flutter Support | Excellent. Official SDK. |
| Cost | Free tier: unlimited push to 10K subscribers. Paid tiers start at $9/mo for advanced segmentation. |
| Features | A/B testing, rich analytics, in-app messaging. |
| Reasoning | Worth considering if the non-technical team wants to send marketing pushes without engineering. For Scales' current stage, engineering-triggered pushes ("your song is up next") via FCM are sufficient. |

#### NO GO: AWS SNS
| Factor | Assessment |
|--------|------------|
| Flutter Support | No official Flutter SDK. Requires platform-channel native code for iOS/Android. |
| Cost | Competitive but not free. |
| Complexity | SNS is a general pub/sub system. Configuring it for mobile push is 10x the effort of FCM. |
| Reasoning | Wrong tool for the job. SNS shines for server-to-server eventing, not consumer push notifications. |

### Final Decision
**FCM for push notifications.** Cost is $0. Official Flutter support is best-in-class. Topic-based messaging maps perfectly to venue rooms. If marketing needs grow, migrating to OneSignal from FCM is a plugin swap.

---

## 10. File Storage

### Options Ranked

#### GO: Cloudflare R2
| Factor | Assessment |
|--------|------------|
| CDN | Native integration with Cloudflare's 300+ PoP network. Images load fast globally. |
| Egress Cost | **$0.** For a karaoke app where users view song metadata images and user avatars constantly, this is transformative. S3 would bill $0.09 per GB of user views. |
| Storage Cost | $0.015/GB/mo (vs S3 $0.023). Slightly cheaper. |
| S3 API | Compatible with existing S3 SDKs. boto3 and aws-sdk-js work out of the box. |
| Limitations | Only 2 storage classes (Standard, IA). No lifecycle rules for Glacier. For Scales' use case (hot images/avatars), this is irrelevant. |
| Reasoning | **R2's zero egress is the deciding factor.** Karaoke apps have high-read, low-write file patterns (avatars viewed constantly, uploaded once). R2 saves thousands annually versus S3 at scale. |

#### CONDITIONAL GO: AWS S3 + CloudFront
| Factor | Assessment |
|--------|------------|
| CDN | CloudFront is mature and fast. |
| Egress Cost | $0.09/GB + CloudFront $0.085/GB. Adds up fast. |
| Ecosystem | Unmatched integrations (Lambda, Athena, etc.). |
| Reasoning | Only if you're already all-in on AWS. Even then, R2 is cheaper for this read-heavy pattern. |

#### NO GO: Google Cloud Storage
| Factor | Assessment |
|--------|------------|
| Egress Cost | $0.08-0.12/GB. No free egress. |
| Ecosystem | Good for ML/data workloads. No advantage for file storage over R2. |
| Reasoning | No compelling advantage over R2. Higher egress costs. |

### Final Decision
**Cloudflare R2.** The S3-compatible API means zero migration risk if requirements change later. For Scales' read-heavy avatar/song-image pattern, zero egress is a 10x cost win over S3.

---

## Cohesive Stack Summary

```
┌─────────────────────────────────────────────────────────────┐
│  MOBILE APP (Flutter)                                       │
│  ──── Offline-first SQLite (PowerSync SDK)                  │
│  ──── Real-time: socket_io_client (rooms per venue)          │
│  ──── Push: FCM (firebase_messaging)                         │
│  ──── File uploads: presigned R2 URLs                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│  REAL-TIME GATEWAY (Node.js + Socket.IO + Redis Adapter)   │
│  ──── Manages venue rooms                                    │
│  ──── Broadcasts KJ state to all mobiles in room             │
│  ──── Relays mobile requests to KJ and REST API              │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│  REST API (Python FastAPI + Uvicorn)                          │
│  ──── Auth, payments (Stripe), song metadata, analytics    │
│  ──── GDPR export/delete endpoints                           │
│  ──── RLS middleware (SET LOCAL app.current_venue_id per request)  │
│  ──── Background jobs: Celery for exports, retention cleanup │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│  DATA LAYER                                                 │
│  ──── PostgreSQL (multi-region for GDPR)                    │
│  ──── Redis (pub/sub between API and gateway; session cache)│
│  ──── PowerSync (bidirectional sync: cloud ↔ KJ)           │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│  KJ DESKTOP APP                                             │
│  ──── Local SQLite database (complete venue state)           │
│  ──── Socket.IO client (connects as "host" to venue room)    │
│  ──── PowerSync background sync worker                       │
│  ──── 5-min cloud checkpoint + full restore on crash         │
└─────────────────────────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│  FILE STORAGE: Cloudflare R2 (zero egress)                │
│  PAYMENTS: Stripe Connect Standard (venue-managed accounts) │
└─────────────────────────────────────────────────────────────┘
```

### Why This Stack Works Together
1. **FastAPI** builds the business logic quickly; **Node.js** handles the one thing it does better (WebSockets at scale).
2. **PowerSync** is the single sync engine for both KJ resilience and mobile offline-first. One technology, two solved problems.
3. **Socket.IO rooms** map 1:1 to venues. A venue room has one host (KJ) and N members (singers). Broadcasting is `.to('venue-123')`.
4. **Cloudflare R2** keeps image serving costs near-zero, which matters when 100 singers per venue browse avatars and album art all night.
5. **Stripe Connect Standard** offloads payment compliance to Stripe and the venues. Scales focuses on karaoke, not money-transmitter licenses.
6. **FCM** is free, Flutter-native, and sufficient for "your turn" notifications.
7. **RLS with `venue_id`** enforces tenant isolation at the row level. Shared schema keeps migrations simple and PowerSync config clean. Enterprise tier migrates to dedicated RDS.
---

## Sources
- RxDB: WebSockets vs SSE vs Long Polling vs WebTransport — https://rxdb.info/articles/websockets-sse-polling-webrtc-webtransport.html
- Ably: Long Polling vs WebSockets at Scale — https://ably.com/blog/websockets-vs-long-polling
- PlanetScale: Approaches to Tenancy in Postgres — https://planetscale.com/blog/approaches-to-tenancy-in-postgres
- KodekX: SaaS Tenant Isolation Strategies — https://kodekx-solutions.medium.com/saas-tenant-isolation-database-schema-and-row-level-security-strategies-7337d2159066
- ChargeKeep: Stripe Connect Comparison — https://www.chargekeep.com/stripe-connect-accounts-comparison/
- DigitalApplied: Cloudflare R2 vs AWS S3 (2025) — https://www.digitalapplied.com/blog/cloudflare-r2-vs-aws-s3-comparison
- PowerSync vs ElectricSQL — https://powersync.com/blog/electricsql-vs-powersync
- PowerSync: Postgres<>SQLite Sync — https://powersync.com/
- OneSignal vs FCM — https://onesignal.com/blog/firebase-vs-onesignal/
- LinkedIn: FastAPI WebSocket Performance 2025 — https://www.linkedin.com/posts/utsav-donda-5aaa71271_fastapi-backenddevelopment-api-activity-7317758575353749504-4ORr
- Reddit: Do WebSockets Drain Battery? — https://www.reddit.com/r/androiddev/comments/ldvbro/do_sockets_drain_phone_battery/
- StackOverflow: WebSockets Energy Consumption — https://stackoverflow.com/questions/29282070/websockets-energy-consumption
