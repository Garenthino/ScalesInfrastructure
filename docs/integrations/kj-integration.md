# DragonHost2-Hermes / Scales Integration Architecture

## System Context

```
+------------------+         +------------------+         +------------------+
|  DragonHost2     |<------->|   Scales Cloud   |<------->|   Scales Mobile  |
|  (Windows KJ)    |  sync   |   (REST + WS)    |  sync   |   (iOS/Android)  |
+------------------+         +------------------+         +------------------+
        |                            |                            |
        |                      [PostgreSQL]                        |
        |                    [Redis + Events]                      |
        |                                                            |
   local SQLite                                                   push notify
```

## Design Principles

1. **Offline-first**: DragonHost2 runs standalone. Network is optional.
2. **Eventual consistency**: Sync is asynchronous and tolerant of partitions.
3. **Conflict resolution**: Mobile singer is source of truth for profile; KJ app is source of truth for queue state and rotation.
4. **Observability**: Every sync attempt is logged with trace IDs, retry counts, and last-success timestamps.

---

## Component Breakdown

### 1. API Client Assembly (`ScalesApiClient.dll`)
- Thin C# wrapper around the Scales REST API.
- `HttpClient` reuse via `SocketsHttpHandler` + `PooledConnectionLifetime`.
- JWT bearer token refreshed via `POST /auth/refresh` before expiry.
- Circuit breaker + exponential backoff on transport failures.
- Structured logging via `Microsoft.Extensions.Logging`.

### 2. Real-Time Receiver (`ScalesRealtimeClient.dll`)
- WebSocket client built on `ClientWebSocket` with `System.Net.WebSockets`.
- Auto-reconnect with configurable jitter (300ms–5s).
- Message dispatch: inbound events are pushed onto an in-memory `Channel<T>` so the UI thread never blocks on I/O.
- Heartbeat/ping-pong to detect silent disconnects.
- If WebSocket unavailable, falls back to long-polling via `GET /kj/events`.

### 3. Singer Sync Bridge (`SingerSyncService`)
- Maps local SQLite `Singers` table ↔ Scales `GET /singers` & `POST /singers/bulk`.
- Identity resolution: `mobile_uid` (UUID) is the stable key. Local `singer_id` is auto-increment internal.
- Conflict rules:
  - **New field in mobile, not local** → create locally.
  - **Field exists in both, mobile is newer** → overwrite local, mark `needs_sync`.
  - **Local stage name changed by KJ** → local wins, push back to cloud with `kj_override` flag.
- Sync runs every `SYNC_INTERVAL` seconds (default 30), or on-demand after explicit KJ actions.

### 4. Song Request Handler (`RequestProcessor`)
- Ingests incoming requests via WS or polling.
- Presents an approval queue in the KJ UI:
  - Approve → append to rotation according to current mode.
  - Reject → notify mobile with optional reason.
  - Auto-approve option for trusted singers (flag in settings).
- Supports two rotation modes:
  - **ROUND_ROBIN**: insert at end of current cycle, preserving fairness.
  - **BACK_TO_BACK**: insert immediately after current singer.
- Metadata attached to queue entry: `request_id`, `uid`, `stage_name`, `song_id`, `pitch`, `tempo`, `kj_notes`.

### 5. Offline Resilience Layer (`OfflineManager`)
- SQLite tables:
  - `outbox` — queued API calls (method, endpoint, body, headers, retry_count).
  - `sync_state` — last-success timestamps per endpoint.
  - `local_queue` — mirror of current rotation state for crash recovery.
- Outbox processor: drains `outbox` oldest-first when connectivity returns.
- Idempotency: every outbox row carries `Scales-Idempotency-Key` (UUID7).
- Crash recovery on startup:
  1. Read `local_queue` into memory.
  2. Read `outbox`; attempt drain.
  3. Perform full sync with cloud.
  4. Reconcile any conflicts.

### 6. Configuration (`AppSettings`)
```json
{
  "Scales": {
    "ApiBaseUrl": "https://api.scales.example.com",
    "ApiKey": "",
    "VenueId": "uuid",
    "SyncIntervalSeconds": 30,
    "RealtimeRetryMaxSeconds": 300,
    "LogLevel": "Information",
    "OfflineBufferMax": 10000,
    "AutoApproveTrusted": false
  }
}
```

---

## Data Flow: New Mobile Request

```
Mobile App
    |
    POST /api/v1/requests
    |
Scales Cloud (persist, enqueue WS broadcast)
    |
    WebSocket "event:request.new"
    |
ScalesRealtimeClient (DragonHost2)
    |
    Channel.Writer.TryWrite(event)
    |
RequestProcessor (UI thread picks up)
    |
    Approval Popup -> KJ clicks Approve
    |
SingerSyncService updates local SQLite
    |
QueueManager appends to rotation (round-robin / b2b)
    |
LocalQueueSnapshot.write()  -- offline resilience
    |
    (async) POST /api/v1/kj/queue -- syncs to cloud
```

---

## Failure Modes

| Scenario | Mitigation |
|---|---|
| Network partition | Outbox buffers all mutations. UI remains responsive using local data. |
| Cloud API 5xx | Exponential backoff (1s, 2s, 4s, 8s, 16s, 32s, max 60s). Circuit breaker after 5 errors in 60s. |
| WebSocket silent drop | Detection via 30s heartbeat. Reconnect attempts with jitter. Fallback to polling after 3 failures. |
| Duplicate sync ops | Idempotency keys in HTTP headers (`Scales-Idempotency-Key`). |
| Singer name collision | Timestamp + `kj_override` flag. If both changed within 1s, KJ app wins. |
| Large sync payload | Chunked upload with `POST /singers/bulk` (max 500 / request). Cursor-based pagination for download. |
| KJ crashes mid-show | `local_queue` table is authoritative. On startup, restore from `local_queue` before syncing to cloud. |

---

## Security Considerations

- API key stored in Windows Credential Manager (`CredWrite`/`CredRead`), never plaintext in SQLite.
- JWT short-lived (15 min). Refresh token rotated on every use.
- `VenueId` scoped: a key only grants access to its venue’s endpoints.
- TLS 1.3 enforced on all transports. Certificate pinning optional via config.
- All payloads validated against JSON Schema before processing.
