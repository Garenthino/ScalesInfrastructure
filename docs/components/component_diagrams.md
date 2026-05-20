# Scales Karaoke Platform — Component Interaction Diagrams

> **Version**: 1.0  
> **Status**: Final  
> **Date**: 2026-05-19

---

## 1. Mobile App ↔ Backend

```mermaid
sequenceDiagram
    autonumber
    participant M as Singer Mobile
    participant A as REST API (FastAPI)
    participant R as Redis
    participant G as Socket.IO Gateway
    participant D as PostgreSQL

    Note over M,D: Check-in & Connection
    M->>A: POST /venues/{id}/checkin
    A->>D: INSERT singer, issue tokens
    A-->>M: access_token + refresh_token
    M->>G: WSS connect + AUTH (JWT)
    G->>R: Validate token, subscribe room
    G-->>M: joined venue:{id}

    Note over M,D: Browse Songs (Offline-friendly)
    M->>A: GET /venues/{id}/songs?genre=rock
    A->>D: SELECT ... WHERE venue_id = ?
    D-->>A: Paginated song list
    A-->>M: {songs: [...], cache_headers}
    M->>M: Cache in SQLite (PowerSync)

    Note over M,D: Submit Song Request
    M->>A: POST /venues/{id}/queue {song_id}
    A->>R: Check rate limit (Tier B: 3/hr)
    A->>D: INSERT queue_requests
    A->>R: PUBLISH scales:api:broadcasts
    R-->>G: Fan-out event
    G->>G: Broadcast to venue:{id}
    G-->>M: {event: request.approved, position: 7}
    G-->>KJ: {event: request.submitted, ...}
```

### Key Details
- **REST is source of truth** for all mutations (queue, favorites, profile updates).
- **WebSocket is notification layer** — the client receives events but must not trust them for state mutations.
- **SQLite cache** on mobile enables offline browsing. Stale data is acceptable for song catalogs.
- **Tier B rate limiting** (3 song requests/hour per singer+venue) is enforced at the API layer before any DB write.

---

## 2. KJ App ↔ Backend

```mermaid
sequenceDiagram
    autonumber
    participant K as KJ Desktop
    participant A as REST API (FastAPI)
    participant R as Redis
    participant G as Socket.IO Gateway
    participant D as PostgreSQL

    Note over K,D: Connection (Host Privilege)
    K->>A: POST /auth/login
    A-->>K: JWT with role=kj, venue_id
    K->>G: WSS connect + AUTH
    G->>R: Validate + join venue:{id} + venue:{id}:host
    G-->>K: Host privileges enabled

    Note over K,D: Download State (Crash Recovery)
    K->>A: GET /venues/{id}/kj/state
    A->>D: SELECT latest snapshot
    D-->>A: Full queue + rotation
    A-->>K: KJ State Snapshot JSON

    Note over K,D: Live Queue Management
    K->>G: WS {event: action.play, request_id}
    G->>A: (via Redis bridge) Update status
    A->>D: UPDATE queue_requests SET status='now_playing'
    A->>R: PUBLISH queue.updated + song.completed
    R-->>G: Fan-out
    G->>G: Broadcast venue:{id}
    G-->>K: Confirmation + next song hint
    G-->>M: Queue position updated
```

### Key Details
- **KJ connects as "host"** in a privileged Socket.IO room (`venue:{id}:host`) for operations that singers cannot perform (skip, reorder, approve/reject).
- **State snapshots** are pulled on login/crash. The KJ app rebuilds local SQLite from the snapshot and resumes.
- **Action events from KJ** go through the gateway → Redis bridge → FastAPI → DB → Redis broadcast → all clients. Latency target: P99 < 1s.

---

## 3. KJ App ↔ Cloud Sync

```mermaid
sequenceDiagram
    autonumber
    participant K as KJ Desktop
    participant L as Local SQLite
    participant P as PowerSync SDK
    participant N as Cloud PostgreSQL
    participant S as S3
    participant A as REST API

    Note over K,N: Background Sync (Periodic)
    K->>P: Every 5 minutes: sync deltas
    P->>L: Read WAL, compute changes
    P->>N: Push INSERT/UPDATE/DELETE
    N-->>P: Ack + server-side conflicts
    P-->>K: Sync complete

    Note over K,N: Secondary Backup Path
    K->>S: Upload SQLite WAL every 30s
    S-->>K: Confirm receipt

    Note over K,N: Crash Recovery Flow
    K->>K: App crashes / machine reboots
    K->>A: GET /venues/{id}/kj/state
    A->>N: Fetch latest venue snapshot
    N-->>A: {queue, rotation, settings}
    A-->>K: State Snapshot JSON
    K->>L: Rebuild SQLite from snapshot
    K->>K: UI: "Resume from here?" (10s countdown)

    Note over K,N: Conflict Resolution
    P->>N: Push queue_requests update
    N->>N: Check kj_session active?
    alt KJ session active
        N->>N: Accept KJ update (KJ-authoritative)
    else KJ offline
        N->>N: Standard LWW on updated_at
    end
    N-->>P: Merge result
```

### Key Details
- **PowerSync** is the primary sync engine. It reads SQLite WAL, computes deltas, and pushes them to PostgreSQL.
- **Conflict resolution** is per-table: LWW for config, append-only for events, KJ-authoritative for live queue.
- **S3 is the disaster-recovery backup** — a secondary restore path if PowerSync is unavailable.
- **SQLite on KJ** is encrypted with SQLCipher for local security.

---

## 4. Mobile App ↔ KJ App (Indirect via Backend)

```mermaid
sequenceDiagram
    autonumber
    participant M as Singer Mobile
    participant G as Socket.IO Gateway
    participant A as REST API
    participant K as KJ Desktop

    Note over M,K: There is NO direct connection.
    All interaction between Singer and KJ is brokered by the platform.

    M->>A: POST /venues/{id}/queue {song_id}
    A->>A: Validate (rate limit, open venue, song available)
    A->>G: Redis PUBLISH event
    G-->>K: WS: request.submitted
    K->>K: UI shows new request
    K->>G: WS: action.approve {request_id}
    G->>A: Redis PUBLISH + API call
    A->>A: Update DB, award points
    A->>G: Redis PUBLISH confirmation
    G-->>M: WS: request.approved + position + est_start
    G-->>M: WS: points.earned {+10}
```

### Key Details
- **Mobile and KJ never talk directly** — not via Bluetooth, local network, or peer-to-peer sockets. All coordination is through the platform.
- This design:
  - Prevents venue-hopping (a singer can only interact with queues they checked into).
  - Enables cloud-side analytics (every queue action is logged).
  - Allows multi-KJ setups (two KJs can manage the same venue from different devices, state synced via cloud).
  - Supports remote oversight (venue manager can monitor queue from anywhere).
- **If internet is down**: KJ SQLite runs locally (queue can still be managed manually). Mobile SQLite cache allows browsing but queue submission is queued for later sync.

---

## 5. Venue Manager Portal ↔ Backend

```mermaid
sequenceDiagram
    autonumber
    participant V as Venue Portal (React)
    participant A as REST API (FastAPI)
    participant R as Redis
    participant G as Socket.IO Gateway
    participant D as PostgreSQL

    Note over V,D: Authentication & Tenant Isolation
    V->>A: POST /auth/login {email, password}
    A->>D: Verify credentials, issue tokens
    A-->>V: JWT (role=venue_admin, venue_id=...)
    A->>A: Middleware: SET LOCAL app.current_venue_id = ?

    Note over V,D: Dashboard (Real-Time Views)
    V->>G: WSS connect + AUTH
    G->>R: Join venue:{id} (read-only participation)
    G-->>V: Real-time queue updates

    Note over V,D: Admin CRUD Operations
    V->>A: PUT /venues/{id}/loyalty/config
    A->>D: UPDATE venue_configs
    A->>R: PUBLISH config.changed
    R-->>G: Fan-out
    G-->>KJ: Update settings in real time

    Note over V,D: Analytics & Exports
    V->>A: GET /venues/{id}/analytics/summary
    A->>D: SELECT (venue_id scoped via RLS)
    D-->>A: Aggregated metrics
    A-->>V: JSON dashboard payload

    V->>A: POST /venues/{id}/exports/csv
    A->>C: Enqueue Celery job
    C-->>A: Job scheduled
    A-->>V: {export_id, status: queued}
    C->>S: Upload CSV to R2
    C->>A: Mark complete
```

### Key Details
- **The portal is a standard React SPA** that consumes the same FastAPI the mobile app uses.
- **Real-time views** (live queue, check-ins) are fed via Socket.IO in the same venue room as singers and KJ.
- **CRUD changes** by venue admin propagate immediately to the KJ via the Redis → gateway fan-out path.
- **Analytics and exports** are Celery-backed because they may scan large date ranges and must not block API workers.

---

## 6. Data Flow Summary Table

| Flow | Primary Transport | Backup Transport | Source of Truth |
|------|-------------------|------------------|-----------------|
| Singer → Queue Request | REST API + Socket.IO push | Queued in SQLite if offline | PostgreSQL |
| KJ → Queue Control | Socket.IO action → REST bridge | Local SQLite always writable | PostgreSQL |
| KJ ↔ Cloud State | PowerSync (bidirectional) | S3 SQLite WAL backups | PostgreSQL |
| Mobile ↔ Cloud Songs | PowerSync (bidirectional) | HTTP GET on cache miss | PostgreSQL |
| Venue Admin → Config | REST API + Socket.IO fan-out | Retry with exponential backoff | PostgreSQL |
| Payments (All) | Stripe Checkout + Webhooks | Manual reconciliation dashboard | Stripe + PostgreSQL |
| Push Notifications | FCM topic message | In-app unread badge count | FCM + PostgreSQL |

---

## 7. Failure Modes

| Scenario | Behavior | Recovery |
|----------|----------|----------|
| Mobile offline | SQLite cache serves browse. Requests queue locally. FCM not received. | Auto-sync when connectivity returns. |
| KJ internet drops | Local SQLite remains writable. Queue continues operating. No mobile updates. | PowerSync catches up on reconnect. Full restore available from API. |
| Gateway (Socket.IO) down | REST API still functions. Mobile falls back to polling for queue state. | Auto-reconnect with exponential backoff. |
| FastAPI down | Socket.IO gateway queues events but cannot persist. Queue actions stall. | Health checks trigger ECS replacement. |
| PostgreSQL primary fails | Aurora auto-failover to reader (~60s). API returns 503 briefly. | Read replica promotion. |
| Redis down | Rate limits fail open (allow). Gateway loses pub/sub — single-node messages still work. | ElastiCache multi-AZ failover. |
