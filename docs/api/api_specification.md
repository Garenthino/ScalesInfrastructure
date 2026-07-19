# Scales Karaoke Platform — API Specification

> **Version**: 1.1.0  
> **Base URL**: `https://api.scales.app/v1`  
> **Protocol**: HTTPS (REST) / WSS (WebSocket) / SSE (server-sent events)  
> **Content-Type**: `application/json`  
> **Cross-references**: [Security Architecture](security_architecture.md)
> **Synthesized from**: t_97abe5ff (API Spec) + t_20644505 (Token/Rate Limit Reconciliation)

---

## Authentication

The API uses **JWT Bearer tokens** passed in the `Authorization` header.

```
Authorization: Bearer <jwt>
```

### Token Types

Scales uses a **two-model authentication system**: dual-token OAuth2 for human users, and long-lived service tokens for machine-to-machine (M2M) clients.

#### Human users (dual-token OAuth2)

All authenticated human users — singer, kj, venue_admin, and platform_admin — share a single token model. The access token is short-lived and the refresh token allows background re-authentication without re-entering credentials.

| Token Type | Issued To | Scope | Lifetime |
|------------|-----------|-------|----------|
| `anonymous` | Unauthenticated users | Public read-only endpoints | 24h |
| `access` | All human users (singer, kj, venue_admin, platform_admin) | Role-scoped API access | **15 minutes** |
| `refresh` | All human users | Re-issue access token | **7 days** (single-use, rotated) |
| `service` | M2M / service accounts | Internal service communication | **30 days** |

Role differentiation is carried in the JWT `role` and `venue_id` claims, not by token lifetime. See `security_architecture.md` §Token Architecture for implementation details (device binding, refresh rotation, Keychain/Keystore storage).

#### KJ device authentication (M2M API key + JWT)

KJ desktop apps authenticate using a machine-to-machine flow:

1. **Register** a device (admin only): `POST /v1/kj/register` → returns `api_key` (shown once)
2. **Exchange** API key for JWT: `POST /v1/kj/token` → returns short-lived `access_token` (15 min)
3. **Call API** with either:
   - `x-api-key: <api_key>` header — direct API key auth
   - `Authorization: Bearer <access_token>` — JWT auth

4. **Manage devices** (admin only):
   - `GET /v1/kj/devices` — list devices per venue
   - `POST /v1/kj/devices/{id}/revoke` — revoke a device
   - `POST /v1/kj/devices/{id}/rotate` — rotate API key (un-revokes if revoked)

API keys are stored as bcrypt hashes. The backend dependency `kj_auth()` validates both header styles.

### Auth Schemes Per Endpoint

- 🔓 **public** — No authentication required
- 🔒 **singer** — Requires valid singer session token
- 🔒 **kj** — Requires valid KJ session token
- 🔒 **kj_device** — Requires valid KJ device API key or KJ device JWT
- 🔒 **venue_admin** — Requires venue admin token
- 🔒 **platform_admin** — Requires platform admin token
- 🔒 **venue_staff** — Accepts KJ or venue_admin token

---

## Rate Limiting

Rate limits are split into **two tiers**: a generous UX tier for normal usage and a strict abuse-prevention tier for write-heavy operations.

### Tier A — UX Tier (per authenticated session)

These limits apply to routine browsing and management flows. They are enforced by access-token identity (not by IP).

| Endpoint Class | Rate Limit | Burst |
|----------------|------------|-------|
| Public reads (songs, leaderboards) | 60 req/min | 10 |
| Song browse / search | 100 req/min | 15 |
| Social reads (history, stats) | 60 req/min | 10 |
| Social writes (favorites, check-ins, follows) | 20 req/min | 5 |
| Merchandise reads (catalog, cart, orders) | 60 req/min | 10 |
| Venue admin CRUD | 30 req/min | 5 |
| Platform admin | 120 req/min | 20 |
| Realtime (WebSocket) | 10 msg/sec | — |

### Tier B — Abuse-Prevention Tier (per device / per singer-venue combo)

These limits protect queue integrity and prevent queue flooding. They are enforced independently of Tier A and have much smaller windows.

| Operation | Limit | Window | Scope Key |
|-----------|-------|--------|-----------|
| Submit song request | 3 | hour | `singer_id + venue_id` |
| Enter queue (anonymous / device) | 10 | hour | `device_id` |
| Queue modifications (approve, reject, skip, reorder) | 30 | minute | `kj_id` (role-scoped) |
| Check-in (new session) | 5 | hour | `device_id` |
| Account creation / login | 5 | hour | `IP` |
| Password reset / auth recovery | 3 | hour | `IP` |

### Response Headers

All throttled responses include:
- `X-RateLimit-Limit`: Rate limit ceiling
- `X-RateLimit-Remaining`: Remaining requests in current window
- `X-RateLimit-Reset`: Unix timestamp when window resets
- `X-RateLimit-Tier`: `ux` or `abuse_prevention` (which tier triggered the limit)

### Error Response

When a Tier B limit is exceeded the 429 `rate_limit_exceeded` Problem Detail includes a `retry_after_minutes` hint:

```json
{
  "type": "https://api.scales.app/errors/rate-limit-exceeded",
  "title": "Rate Limit Exceeded",
  "status": 429,
  "detail": "You have exceeded the 3 requests per hour limit for song requests at this venue.",
  "instance": "/venues/ven_123/queue",
  "retry_after_minutes": 42
}
```

---

## Endpoint Inventory

### 1. Venue Management

| Auth | Method | Path | Description |
|------|--------|------|-------------|
| 🔓 | GET | `/venues` | List active venues (public discovery) |
| 🔓 | GET | `/venues/{venue_id}` | Get venue public profile |
| 🔓 | GET | `/venues/{venue_id}/status` | Real-time venue status (open, closed, queue depth) |
| 🔒 venue_admin | POST | `/venues` | Create new venue |
| 🔒 venue_admin | PUT | `/venues/{venue_id}` | Update venue settings |
| 🔒 venue_admin | DELETE | `/venues/{venue_id}` | Deactivate venue (soft delete) |
| 🔒 venue_admin | GET | `/venues/{venue_id}/admin` | Get full venue config |
| 🔒 venue_admin | PUT | `/venues/{venue_id}/branding` | Update logo, colors, custom CSS |
| 🔒 venue_admin | GET | `/venues/{venue_id}/analytics` | Venue performance dashboard data |
| 🔒 platform_admin | GET | `/admin/venues` | List all venues (platform-wide) |

**Parameters (POST/PUT `/venues`)**:
```json
{
  "name": "string (required, 1-100 chars)",
  "slug": "string (required, unique, slug format)",
  "address": {
    "street": "string",
    "city": "string",
    "state": "string",
    "zip": "string",
    "country": "string (ISO 3166-1 alpha-2)"
  },
  "contact": {
    "phone": "string",
    "email": "string (email format)"
  },
  "settings": {
    "max_queue_depth": "integer (default: 50)",
    "require_approval": "boolean (default: false)",
    "allow_duplicates": "boolean (default: true)",
    "rotation_mode": "string (fifo|weighted|vip_priority)"
  },
  "operating_hours": {
    "timezone": "string (IANA tz, e.g., America/New_York)",
    "schedule": [
      {"day": 1, "open": "19:00", "close": "02:00"}
    ]
  }
}
```

---

### 2. Song Database

Venue-scoped song catalogs. Songs are either global (platform) or venue-custom.

| Auth | Method | Path | Description |
|------|--------|------|-------------|
| 🔓 | GET | `/venues/{venue_id}/songs` | Browse venue song catalog |
| 🔓 | GET | `/venues/{venue_id}/songs/{song_id}` | Get song metadata |
| 🔓 | GET | `/venues/{venue_id}/songs/search` | Search by title/artist/lyrics |
| 🔒 venue_staff | POST | `/venues/{venue_id}/songs` | Add custom song to venue |
| 🔒 venue_staff | PUT | `/venues/{venue_id}/songs/{song_id}` | Update custom song |
| 🔒 venue_staff | DELETE | `/venues/{venue_id}/songs/{song_id}` | Remove custom song |
| 🔒 venue_admin | POST | `/venues/{venue_id}/songs/{song_id}/disable` | Temporarily disable song |
| 🔒 platform_admin | GET | `/admin/songs` | Global song registry |
| 🔒 platform_admin | POST | `/admin/songs` | Add to global catalog |

**Query Parameters (GET `/songs`)**:
- `genre` — Filter by genre (rock, pop, country, etc.)
- `language` — ISO 639-1 code
- `decade` — 1980s, 1990s, etc.
- `difficulty` — easy, medium, hard
- `duration_min` — Minimum song duration (seconds)
- `duration_max` — Maximum song duration (seconds)
- `page` — Pagination page (default: 1)
- `per_page` — Items per page (default: 20, max: 100)

**Search Query (GET `/songs/search`)**:
- `q` — Search query (title, artist, lyrics snippet)
- `type` — `title`, `artist`, `all` (default: all)
- `fuzzy` — Enable fuzzy matching (boolean, default: true)

---

### 3. Singer / Patron

Per-venue singer profiles and session management.

| Auth | Method | Path | Description |
|------|--------|------|-------------|
| 🔓 | POST | `/venues/{venue_id}/checkin` | Anonymous check-in (returns singer token) |
| 🔒 singer | GET | `/singer/profile` | Get current singer profile |
| 🔒 singer | PUT | `/singer/profile` | Update profile (nickname, avatar) |
| 🔒 singer | POST | `/venues/{venue_id}/favorites` | Add song to favorites |
| 🔒 singer | DELETE | `/venues/{venue_id}/favorites/{song_id}` | Remove from favorites |
| 🔒 singer | GET | `/venues/{venue_id}/favorites` | List singer's favorites for venue |
| 🔒 singer | GET | `/singer/history` | Performance history across venues |
| 🔒 singer | GET | `/singer/stats` | Personal stats (songs sung, points earned) |
| 🔒 singer | DELETE | `/singer/account` | Delete all personal data (GDPR) |
| 🔒 venue_staff | GET | `/venues/{venue_id}/singers` | List checked-in singers |
| 🔒 venue_staff | GET | `/venues/{venue_id}/singers/{singer_id}` | Get singer details |
| 🔒 venue_staff | POST | `/venues/{venue_id}/singers/{singer_id}/kick` | Remove singer from venue |

**Check-in Request**:
```json
{
  "nickname": "string (optional, 1-30 chars)",
  "table_number": "string (optional)",
  "party_size": "integer (optional)",
  "phone": "string (optional, for notifications)",
  "marketing_consent": "boolean (default: false)"
}
```

**Check-in Response**:
```json
{
  "singer_id": "uuid",
  "access_token": "jwt_string",
  "access_token_expires": "ISO8601 (15 minutes from now)",
  "refresh_token": "jwt_string",
  "refresh_token_expires": "ISO8601 (7 days from now)",
  "venue": { /* venue summary */ },
  "loyalty": {
    "current_points": 150,
    "tier": "regular|vip|regular_plus",
    "next_tier_progress": 0.65
  }
}
```

---

### 4. Request Queue

The core karaoke request system.

| Auth | Method | Path | Description |
|------|--------|------|-------------|
| 🔓 | GET | `/venues/{venue_id}/queue` | View current queue (public) |
| 🔒 singer | POST | `/venues/{venue_id}/queue` | Submit song request |
| 🔒 singer | GET | `/venues/{venue_id}/queue/my` | Get singer's active requests |
| 🔒 singer | DELETE | `/venues/{venue_id}/queue/me/{request_id}` | Cancel own pending request |
| 🔒 singer | DELETE | `/venues/{venue_id}/queue/{request_id}` | Cancel own request (legacy) |
| 🔒 kj | PATCH | `/venues/{venue_id}/queue/{request_id}` | Approve/reject/prioritize request |
| 🔒 kj | POST | `/venues/{venue_id}/queue/{request_id}/start` | Mark as "now playing" |
| 🔒 kj | POST | `/venues/{venue_id}/queue/{request_id}/complete` | Mark as completed |
| 🔒 kj | POST | `/venues/{venue_id}/queue/{request_id}/skip` | Skip current song |
| 🔒 kj | PUT | `/venues/{venue_id}/queue/reorder` | Manual queue reorder |
| 🔒 venue_staff | DELETE | `/venues/{venue_id}/queue/{request_id}` | Admin remove request |
| 🔒 venue_staff | POST | `/venues/{venue_id}/queue/clear` | Clear entire queue |

**Queue Item Schema**:
```json
{
  "request_id": "uuid",
  "position": 1,
  "status": "pending|approved|now_playing|completed|skipped",
  "song": {
    "song_id": "uuid",
    "title": "string",
    "artist": "string",
    "duration": 240
  },
  "singer": {
    "singer_id": "uuid",
    "nickname": "string",
    "tier": "regular|vip|regular_plus"
  },
  "submitted_at": "ISO8601",
  "estimated_start": "ISO8601",
  "notes": "string (singer notes for KJ)",
  "dedication": "string (optional, to another singer)"
}
```

**Submit Request**:
```json
{
  "song_id": "uuid (required)",
  "notes": "string (optional, 0-200 chars)",
  "dedication_to": "singer_id (optional)",
  "priority_boost": "boolean (optional, uses loyalty points)"
}
```

---

### 5. Loyalty System

Points, tiers, quests, and redemption.

| Auth | Method | Path | Description |
|------|--------|------|-------------|
| 🔒 singer | GET | `/singer/loyalty` | Current points and tier status |
| 🔒 singer | GET | `/singer/loyalty/transactions` | Points transaction history |
| 🔒 singer | GET | `/singer/loyalty/quests` | Available quests for singer |
| 🔒 singer | POST | `/singer/loyalty/quests/{quest_id}/claim` | Claim quest reward |
| 🔒 singer | GET | `/venues/{venue_id}/rewards` | Redeemable rewards for venue |
| 🔒 singer | POST | `/venues/{venue_id}/rewards/{reward_id}/redeem` | Redeem reward |
| 🔒 venue_admin | GET | `/venues/{venue_id}/loyalty/config` | Get loyalty config |
| 🔒 venue_admin | PUT | `/venues/{venue_id}/loyalty/config` | Update loyalty settings |
| 🔒 venue_admin | GET | `/venues/{venue_id}/loyalty/quests` | Manage venue quests |
| 🔒 venue_admin | POST | `/venues/{venue_id}/loyalty/quests` | Create new quest |
| 🔒 venue_admin | PUT | `/venues/{venue_id}/loyalty/quests/{quest_id}` | Update quest |
| 🔒 venue_admin | DELETE | `/venues/{venue_id}/loyalty/quests/{quest_id}` | Delete quest |
| 🔒 venue_admin | GET | `/venues/{venue_id}/loyalty/rewards` | Manage venue rewards |
| 🔒 venue_admin | POST | `/venues/{venue_id}/loyalty/rewards` | Create reward |

**Points Earning Rules (venue-configured)**:
```json
{
  "points_per_song": 10,
  "points_per_dollar_spent": 1,
  "checkin_bonus": 5,
  "first_time_bonus": 25,
  "referral_bonus": 50
}
```

**Quest Schema**:
```json
{
  "quest_id": "uuid",
  "name": "string",
  "description": "string",
  "type": "sing_n_songs|spend_n_dollars|visit_n_times|refer_friend",
  "target": 5,
  "reward_points": 100,
  "start_date": "ISO8601",
  "end_date": "ISO8601",
  "is_recurring": false
}
```

**Tier Configuration**:
```json
{
  "tier_id": "regular|regular_plus|vip",
  "name": "string",
  "points_threshold": 500,
  "benefits": {
    "queue_priority": 0,
    "discount_percent": 10,
    "free_song_per_visit": false
  }
}
```

---

### 6. Merchandise

Catalog, Stripe checkout, and dropshipper webhooks.

| Auth | Method | Path | Description |
|------|--------|------|-------------|
| 🔓 | GET | `/venues/{venue_id}/merch` | List merchandise catalog |
| 🔓 | GET | `/merch/{product_id}` | Get product details |
| 🔒 singer | POST | `/cart` | Add item to cart |
| 🔒 singer | GET | `/cart` | View cart |
| 🔒 singer | DELETE | `/cart/{line_item_id}` | Remove from cart |
| 🔒 singer | POST | `/checkout` | Create Stripe checkout session |
| 🔒 singer | GET | `/orders` | Order history |
| 🔒 singer | GET | `/orders/{order_id}` | Order details + tracking |
| 🔒 singer | POST | `/orders/{order_id}/cancel` | Cancel order (if unshipped) |
| 🔒 venue_admin | GET | `/venues/{venue_id}/merch/admin` | Manage catalog |
| 🔒 venue_admin | POST | `/venues/{venue_id}/merch` | Add product |
| 🔒 venue_admin | PUT | `/venues/{venue_id}/merch/{product_id}` | Update product |
| 🔒 venue_admin | DELETE | `/venues/{venue_id}/merch/{product_id}` | Remove product |
| 🔒 venue_admin | GET | `/venues/{venue_id}/orders` | View venue orders |
| 🔒 venue_admin | PUT | `/venues/{venue_id}/orders/{order_id}/status` | Update fulfillment status |
| 🔒 platform_admin | POST | `/webhooks/stripe` | Stripe webhook handler |
| 🔒 platform_admin | POST | `/webhooks/dropshipper/{provider}` | Dropshipper fulfillment webhooks |

**Product Schema**:
```json
{
  "product_id": "uuid",
  "venue_id": "uuid|null (null = platform merch)",
  "name": "string",
  "description": "string",
  "price_cents": 2500,
  "currency": "USD",
  "images": ["url"],
  "sku": "string",
  "inventory_count": 100,
  "is_digital": false,
  "fulfillment_provider": "internal|printful|shipstation|null"
}
```

**Stripe Checkout Flow**:
1. Client calls `POST /checkout` with `cart_id` and `success_url`, `cancel_url`
2. Server validates cart, creates Stripe Checkout Session
3. Returns `{ checkout_url: "https://checkout.stripe.com/..." }`
4. Client redirects to Stripe
5. Stripe sends `checkout.session.completed` webhook → order created

**Webhook Events**:
- `payment_intent.succeeded` — Payment confirmed
- `checkout.session.completed` — Checkout finished
- `invoice.payment_failed` — Subscription/recurring payment failed
- Dropshipper: `order.shipped`, `order.delivered`, `inventory.updated`

---

### 7. Social

Leaderboards, consent management, and sharing.

| Auth | Method | Path | Description |
|------|--------|------|-------------|
| 🔓 | GET | `/venues/{venue_id}/leaderboard` | Top singers this week/month/all-time |
| 🔓 | GET | `/venues/{venue_id}/leaderboard/songs` | Most requested songs |
| 🔒 singer | GET | `/singer/privacy` | Current privacy/consent settings |
| 🔒 singer | PUT | `/singer/privacy` | Update consent toggles |
| 🔒 singer | POST | `/share` | Generate shareable link |
| 🔒 singer | POST | `/singer/follow/{singer_id}` | Follow another singer |
| 🔒 singer | DELETE | `/singer/follow/{singer_id}` | Unfollow singer |
| 🔒 singer | GET | `/singer/following` | List following |
| 🔒 singer | GET | `/singer/followers` | List followers |
| 🔒 singer | GET | `/venues/{venue_id}/friends` | Friends checked in at venue |
| 🔒 venue_staff | GET | `/venues/{venue_id}/social/analytics` | Social engagement metrics |

**Consent Toggles**:
```json
{
  "allow_leaderboard": true,
  "allow_sharing": true,
  "share_nickname_publicly": true,
  "allow_tagging": true,
  "allow_friends_find_by_phone": false,
  "allow_marketing": false
}
```

**Leaderboard Entry**:
```json
{
  "rank": 1,
  "singer_id": "uuid",
  "nickname": "string (anonymized if no consent)",
  "avatar_url": "string|null",
  "score": 1250,
  "songs_sung": 15,
  "trend": "up|down|stable"
}
```

---

### 8. Analytics

Aggregated metrics and reporting.

| Auth | Method | Path | Description |
|------|--------|------|-------------|
| 🔒 venue_admin | GET | `/venues/{venue_id}/analytics/summary` | Daily/weekly/monthly summary |
| 🔒 venue_admin | GET | `/venues/{venue_id}/analytics/attendance` | Check-ins over time |
| 🔒 venue_admin | GET | `/venues/{venue_id}/analytics/engagement` | Singer retention, repeat visits |
| 🔒 venue_admin | GET | `/venues/{venue_id}/analytics/songs` | Popular songs, genres, artists |
| 🔒 venue_admin | GET | `/venues/{venue_id}/analytics/loyalty` | Points issued, redemptions |
| 🔒 venue_admin | GET | `/venues/{venue_id}/analytics/revenue` | Merch sales breakdown |
| 🔒 venue_admin | GET | `/venues/{venue_id}/analytics/peaks` | Busiest hours/days |
| 🔒 platform_admin | GET | `/admin/analytics/venues` | Cross-venue comparison |
| 🔒 platform_admin | GET | `/admin/analytics/platform` | Platform-wide metrics |
| 🔒 platform_admin | GET | `/admin/analytics/retention` | Cohort analysis |

**Time Range Parameters** (all analytics):
- `from` — ISO8601 start date (default: 30 days ago)
- `to` — ISO8601 end date (default: now)
- `granularity` — `hour`, `day`, `week`, `month`

**Attendance Response**:
```json
{
  "total_checkins": 1234,
  "unique_singers": 456,
  "return_rate": 0.35,
  "average_party_size": 2.4,
  "by_day": [
    {"date": "2025-05-01", "checkins": 45}
  ],
  "by_hour": [
    {"hour": 19, "checkins": 120}
  ]
}
```

---

### 9. Export

CSV and PDF report generation.

| Auth | Method | Path | Description |
|------|--------|------|-------------|
| 🔒 venue_admin | POST | `/venues/{venue_id}/exports/csv` | Generate CSV export |
| 🔒 venue_admin | GET | `/venues/{venue_id}/exports` | List available exports |
| 🔒 venue_admin | GET | `/venues/{venue_id}/exports/{export_id}` | Get export download URL |
| 🔒 venue_admin | DELETE | `/venues/{venue_id}/exports/{export_id}` | Delete export file |
| 🔒 venue_admin | POST | `/venues/{venue_id}/exports/pdf` | Generate PDF report |
| 🔒 venue_admin | POST | `/venues/{venue_id}/exports/schedule` | Schedule recurring export |

**Export Types**:
- `singer_list` — All singers with contact info
- `song_history` — Complete request log
- `loyalty_transactions` — Points audit trail
- `orders` — Merchandise sales
- `revenue_summary` — Aggregated revenue data

**CSV Export Request**:
```json
{
  "type": "song_history",
  "format": "csv",
  "from": "2025-05-01",
  "to": "2025-05-31",
  "include_fields": ["song_id", "title", "artist", "singer_nickname", "sung_at"],
  "delivery": "download|email"
}
```

**PDF Report Types**:
- `monthly_summary` — Branded monthly performance report
- `song_catalog` — Printable song book
- `loyalty_dashboard` — Points program overview

---

### 10. KJ Sync

State upload/download for crash recovery and multi-device KJ setups.

| Auth | Method | Path | Description |
|------|--------|------|-------------|
| 🔒 kj | GET | `/venues/{venue_id}/kj/state` | Download current KJ state |
| 🔒 kj | PUT | `/venues/{venue_id}/kj/state` | Upload state snapshot |
| 🔒 kj | POST | `/venues/{venue_id}/kj/sync` | Trigger cross-device sync |
| 🔒 kj | GET | `/venues/{venue_id}/kj/history` | KJ action log |
| 🔒 venue_admin | GET | `/venues/{venue_id}/kj/sessions` | Active KJ sessions |
| 🔒 venue_admin | DELETE | `/venues/{venue_id}/kj/sessions/{session_id}` | Force KJ logout |

**KJ State Snapshot**:
```json
{
  "snapshot_id": "uuid",
  "venue_id": "uuid",
  "kj_id": "uuid",
  "captured_at": "ISO8601",
  "queue": [ /* full queue items */ ],
  "now_playing": { /* request object or null */ },
  "rotation_position": 5,
  "settings": { /* KJ settings */ },
  "announcements": [ /* active announcements */ ]
}
```

**Sync Protocol**: Last-write-wins with conflict detection. If two KJs upload simultaneously, the server keeps both versions and notifies of conflict.

---

## Real-Time Event Schemas

### WebSocket Connection

**Endpoint**: `wss://ws.scales.app/v1`

**Authentication**: Pass JWT token in connection `Authorization` header.

### Event Flow Patterns

| Publisher | Subscriber | Event | Purpose |
|-----------|------------|-------|---------|
| Server → | Singer | `queue.updated` | Singer's position changed |
| Server → | Singer | `request.approved` | Their request approved |
| Server → | Singer | `request.rejected` | Their request rejected |
| Server → | Singer | `points.earned` | Loyalty points awarded |
| Server → | KJ | `request.submitted` | New request incoming |
| Server → | KJ | `request.cancelled` | Singer cancelled |
| Server → | Venue | `singer.checked_in` | New check-in |
| Server → | Venue | `song.completed` | Song finished |
| KJ → Server | — | `action.play` | Mark song playing |
| KJ → Server | — | `action.skip` | Skip current song |

### Event Payload Schemas

#### `queue.updated`
```json
{
  "event": "queue.updated",
  "timestamp": "2025-05-19T16:30:00Z",
  "venue_id": "uuid",
  "data": {
    "your_position": 3,
    "estimated_wait_minutes": 25,
    "queue_length": 12,
    "now_playing": {
      "song_title": "Don't Stop Believin'",
      "singer_nickname": "JourneyFan22"
    }
  }
}
```

#### `request.submitted`
```json
{
  "event": "request.submitted",
  "timestamp": "2025-05-19T16:30:00Z",
  "venue_id": "uuid",
  "data": {
    "request_id": "uuid",
    "song": { /* song object */ },
    "singer": { /* singer object */ },
    "notes": "string"
  }
}
```

#### `request.approved`
```json
{
  "event": "request.approved",
  "timestamp": "2025-05-19T16:30:00Z",
  "venue_id": "uuid",
  "data": {
    "request_id": "uuid",
    "position": 7,
    "estimated_start": "2025-05-19T17:00:00Z"
  }
}
```

#### `request.rejected`
```json
{
  "event": "request.rejected",
  "timestamp": "2025-05-19T16:30:00Z",
  "venue_id": "uuid",
  "data": {
    "request_id": "uuid",
    "reason": "string (shown to singer)",
    "can_retry": true
  }
}
```

#### `singer.checked_in`
```json
{
  "event": "singer.checked_in",
  "timestamp": "2025-05-19T16:30:00Z",
  "venue_id": "uuid",
  "data": {
    "singer_id": "uuid",
    "nickname": "string",
    "is_vip": false,
    "party_size": 3
  }
}
```

#### `points.earned`
```json
{
  "event": "points.earned",
  "timestamp": "2025-05-19T16:30:00Z",
  "venue_id": "uuid",
  "data": {
    "singer_id": "uuid",
    "points": 10,
    "new_balance": 160,
    "reason": "song_completed",
    "tier_changed": false
  }
}
```

#### `tier.upgraded`
```json
{
  "event": "tier.upgraded",
  "timestamp": "2025-05-19T16:30:00Z",
  "venue_id": "uuid",
  "data": {
    "singer_id": "uuid",
    "old_tier": "regular",
    "new_tier": "vip",
    "new_benefits": {
      "queue_priority": 1,
      "discount_percent": 15
    }
  }
}
```

#### `action.play` (KJ → Server)
```json
{
  "event": "action.play",
  "timestamp": "2025-05-19T16:30:00Z",
  "venue_id": "uuid",
  "data": {
    "request_id": "uuid",
    "song_title": "string",
    "singer_nickname": "string"
  }
}
```

#### `action.skip` (KJ → Server)
```json
{
  "event": "action.skip",
  "timestamp": "2025-05-19T16:30:00Z",
  "venue_id": "uuid",
  "data": {
    "request_id": "uuid",
    "reason": "string (optional)"
  }
}
```
