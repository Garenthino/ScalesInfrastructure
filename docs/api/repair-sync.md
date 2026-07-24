# Full Database Repair Sync API

## Overview

The repair sync endpoints let a KJ/venue admin push a complete local snapshot
(singers, queue/history, venue settings, and now-playing state) to the cloud in
one operation. The backend detects conflicts against the current server state,
supports `client_wins` and `prompt` reconciliation modes, and preserves
server-managed fields such as loyalty points, tier, and linked account identity.

These endpoints are intended as a manual recovery tool after database restores,
singer merges, or extended offline operation.

## Base path

All URLs are relative to the API root, e.g. `https://api.scales.app/v1`.

```
POST   /v1/kj/sync/repair
GET    /v1/kj/sync/repair/{sync_id}
POST   /v1/kj/sync/repair/{sync_id}/resolve
DELETE /v1/kj/sync/repair/{sync_id}
```

## Authentication

- `x-api-key` header with a valid KJ device API key, **or**
- `Authorization: Bearer <token>` with an `owner`, `admin`, or `kj` token that
  includes a `venue_id` claim.

Every request must include the target `venue_id` in the body and must match the
authenticated venue.

## Idempotency

`POST /v1/kj/sync/repair` requires the header:

```
X-Idempotency-Key: <uuid>
```

Repeating the same key within the TTL returns the original job without
re-applying the snapshot.

## Start repair sync

### Request

```http
POST /v1/kj/sync/repair
X-Idempotency-Key: 018f...7
x-api-key: my-kj-device-key
Content-Type: application/json
```

```json
{
  "venue_id": "ven_123",
  "mode": "client_wins",
  "snapshot": {
    "singers": {
      "items": [
        {
          "id": "singer-001",
          "stage_name": "Diva Von Teese",
          "first_name": "Diva",
          "last_name": "Von Teese",
          "real_name": "Diva Von Teese",
          "pronouns": "she/her",
          "email": "diva@example.com",
          "phone": "+1-555-0100",
          "total_points": 0,
          "loyalty_tier_id": null,
          "account_id": null,
          "last_seen": "2026-07-14T18:00:00Z",
          "deactivated_at": null,
          "created_at": "2026-01-01T00:00:00Z",
          "updated_at": "2026-07-14T18:00:00Z"
        }
      ],
      "deleted_ids": [],
      "last_modified_at": "2026-07-14T18:00:00Z"
    },
    "queue": {
      "items": [
        {
          "request_id": "req-001",
          "singer_id": "singer-001",
          "singer_name": "Diva Von Teese",
          "song_id": "song-001",
          "song_title": "I Will Survive",
          "song_artist": "Gloria Gaynor",
          "status": "pending",
          "position": 1,
          "notes": "Upbeat opener",
          "requested_at": "2026-07-14T18:00:00Z",
          "updated_at": "2026-07-14T18:00:00Z"
        }
      ],
      "deleted_ids": [],
      "last_modified_at": "2026-07-14T18:00:00Z"
    },
    "settings": {
      "items": [
        {"key": "rotation_mode", "value": "weighted", "updated_at": "2026-07-14T18:00:00Z"},
        {"key": "allow_priority_bump", "value": "true", "updated_at": "2026-07-14T18:00:00Z"}
      ],
      "last_modified_at": "2026-07-14T18:00:00Z"
    },
    "now_playing": {
      "singer_id": "singer-001",
      "song_id": "song-001",
      "song_title": "I Will Survive",
      "song_artist": "Gloria Gaynor",
      "singer_name": "Diva Von Teese",
      "is_dj_track": false,
      "started_at": "2026-07-14T18:00:00Z"
    }
  }
}
```

### Response `202 Accepted`

```json
{
  "sync_id": "sync-uuid",
  "status": "completed",
  "mode": "client_wins",
  "created_at": "2026-07-14T18:00:01Z",
  "updated_at": "2026-07-14T18:00:01Z",
  "progress": {
    "total_steps": 6,
    "current_step": 6,
    "step_label": "Finalizing…",
    "percent": 100
  },
  "summary": {
    "singers_synced": 1,
    "queue_synced": 1,
    "settings_synced": 2,
    "now_playing_synced": true,
    "conflicts_resolved": 0,
    "server_modified_at": "2026-07-14T18:00:01Z"
  },
  "conflicts": null,
  "error": null
}
```

### Modes

| Mode | Behaviour |
|------|-----------|
| `client_wins` | Conflicts are resolved in favour of the pushed snapshot. Server-managed fields (loyalty, tier, account) are still preserved. |
| `prompt` | The job stops at `needs_resolution` and returns a `conflicts` array. The client must POST `/resolve` with a decision per conflict. |

## Conflict detection

A conflict is raised when the server row has an `updated_at` timestamp newer than
the snapshot's `last_modified_at` for the same entity.

Conflict payload (singer example):

```json
{
  "entity_type": "singers",
  "entity_id": "singer-001",
  "display_label": "Diva Von Teese",
  "changed_fields": ["stage_name", "pronouns"],
  "server_state": { "stage_name": "Server Diva", "pronouns": "she/her", ... },
  "client_state": { "stage_name": "Client Diva", "pronouns": "they/them", ... },
  "resolution": "server_wins",
  "locked_fields": ["total_points", "loyalty_tier_id", "account_id"],
  "mergeable_fields": ["stage_name", "first_name", "last_name", "real_name", "pronouns", "email", "phone"]
}
```

- `locked_fields` cannot be overwritten by the client.
- `mergeable_fields` may be resolved per-field when `resolution` is `merge`.
- Queue conflicts support `server_wins` or `client_wins` only.
- Settings conflicts support per-key `merge`.

## Resolve conflicts

```http
POST /v1/kj/sync/repair/{sync_id}/resolve
```

```json
{
  "resolutions": [
    {
      "entity_type": "singers",
      "entity_id": "singer-001",
      "resolution": "merge",
      "field_resolutions": {
        "stage_name": "client",
        "pronouns": "server"
      }
    }
  ]
}
```

Response schema is the same as the start endpoint; `status` becomes `completed`.

## Poll status

```http
GET /v1/kj/sync/repair/{sync_id}
```

Returns the current job state. The frontend polls every second while the dialog
is open and stops when `status` is `needs_resolution`, `completed`, or `failed`.

## Cancel

```http
DELETE /v1/kj/sync/repair/{sync_id}
```

Best-effort cancel. Returns `202 Accepted` with the job in `cancelled` state.
If the job already finished, it returns the final state.

## Error schema

On terminal failure:

```json
{
  "type": "about:blank",
  "title": "Repair sync failed",
  "status": 500,
  "detail": "Unexpected error during apply",
  "code": "support_required"
}
```

On validation/permission errors the response uses the standard `ProblemDetail`
shape with `status` 400, 401, 403, 404, or 422.

## Data integrity notes

- Singer `total_points`, `loyalty_tier_id`, and `account_id` are never
  overwritten by a repair sync; they remain under server control.
- Unknown queue requesters are auto-created as stub singers with a unique stage
  name inside the venue.
- Unknown songs referenced by title/artist are auto-created as stub catalog
  entries so that queue rows can satisfy the `song_id NOT NULL` constraint.
- `now_playing` state is broadcast via the queue WebSocket when a singer track
  is applied.
