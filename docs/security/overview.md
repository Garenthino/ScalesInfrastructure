# Scales Karaoke Platform: Security Architecture & Compliance Framework

**Version:** 1.1  
**Classification:** Internal  
**Last Updated:** May 2026  
**Cross-references:** [API Specification](../t_97abe5ff/api_spec.md)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Threat Model (STRIDE)](#threat-model-stride)
3. [Authentication & Authorization Architecture](#authentication--authorization-architecture)
4. [Data Classification & Encryption](#data-classification--encryption)
5. [API & Infrastructure Security](#api--infrastructure-security)
6. [Compliance Framework](#compliance-framework)
7. [Security Controls Matrix](#security-controls-matrix)
8. [Incident Response Plan](#incident-response-plan)
9. [Secrets Management Strategy](#secrets-management-strategy)
10. [Security Checklist & Recommendations](#security-checklist--recommendations)

---

## Executive Summary

The Scales karaoke platform handles sensitive data across multiple categories:
- **Venue business data** (financial, operational)
- **Singer/staff PII** (names, emails, phone numbers, device IDs)
- **Payment card data** (via Stripe - platform is PCI compliant by outsourcing to Stripe)
- **Content data** (recorded performances)
- **Analytics data** (usage patterns, preferences)

This document establishes security architecture, compliance mechanisms, and operational controls to protect this data while enabling the platform's core functionality across mobile, desktop, and web interfaces.

---

## Threat Model (STRIDE)

### System Context

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SCALES KARAOKE PLATFORM                              │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐          │
│  │  MOBILE APP     │    │  DESKTOP APP    │    │  VENUE WEB APP  │          │
│  │  (iOS/Android)  │    │  (KJ Console)    │    │  (Management)   │          │
│  └────────┬────────┘    └────────┬────────┘    └────────┬────────┘          │
│           │                      │                      │                   │
│           └──────────────────────┼──────────────────────┘                   │
│                                  │                                           │
│                    ┌─────────────▼─────────────┐                            │
│                    │      API GATEWAY           │                            │
│                    │  (Auth, Rate Limiting)     │                            │
│                    └───────────────────────────┘                            │
│                                  │                                           │
│        ┌─────────────────────────┼─────────────────────────┐                │
│        ▼                         ▼                         ▼                │
│  ┌──────────┐             ┌──────────┐             ┌──────────┐            │
│  │   REST   │             │WebSocket │             │  Stripe  │            │
│  │   API    │             │  Server  │             │  Webhook │            │
│  └────┬─────┘             └────┬─────┘             └─────┬────┘            │
│       │                        │                        │                  │
│  ┌────▼────┐              ┌─────▼────┐             ┌─────▼────┐            │
│  │Cloud DB │              │  Redis   │             │ Payment  │            │
│  │(SQLite/ │              │(Queues)  │             │Service   │            │
│  │  Files) │              └──────────┘             └──────────┘            │
│  └─────────┘                                                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

### STRIDE Analysis

#### 1. Spoofing (Authentication Threats)

| Threat | Description | Risk | Priority |
|--------|-------------|------|----------|
| T-SPOOF-01 | Fake singer profile creation with stolen identity | Medium | P2 |
| T-SPOOF-02 | Stolen admin/Venue Manager credentials | **Critical** | P0 |
| T-SPOOF-03 | Device spoofing (impersonating legitimate device) | Medium | P2 |
| T-SPOOF-04 | WebSocket connection impersonation | High | P1 |

**Mitigations:**
- JWT tokens with short expiry (15 min access + 7 day refresh)
- Device ID binding + device fingerprinting
- Multi-factor authentication for admin roles
- WebSocket token validation per-message

#### 2. Tampering (Data Integrity Threats)

| Threat | Description | Risk | Priority |
|--------|-------------|------|----------|
| T-TAMP-01 | Modifying song queue order maliciously | Medium | P2 |
| T-TAMP-02 | Modifying performance scores/votes | High | P1 |
| T-TAMP-03 | Modifying payment amounts in transit | **Critical** | P0 |
| T-TAMP-04 | Modifying local database on desktop app | Medium | P2 |

**Mitigations:**
- HMAC signatures on queue operations
- Signed performance records with singer ID
- TLS 1.3 for all payment-related traffic
- Encrypted local DB with MAC verification

#### 3. Repudiation (Audit Threats)

| Threat | Description | Risk | Priority |
|--------|-------------|------|----------|
| T-REPU-01 | Singer denies requesting a song | Low | P3 |
| T-REPU-02 | Venue denies receiving payment | **Critical** | P0 |
| T-REPU-03 | Admin denies data deletion | High | P1 |
| T-REPU-04 | KJ denies skipping a singer | Low | P3 |

**Mitigations:**
- Immutable audit logs (write-once storage)
- Cryptographically signed receipts
- Deletion confirmation with email notification
- Queue action logging with timestamps

#### 4. Information Disclosure (Data Leakage Threats)

| Threat | Description | Risk | Priority |
|--------|-------------|------|----------|
| T-DISC-01 | Leaking singer email/phone to other singers | High | P1 |
| T-DISC-02 | Exposing venue financial data across venues | **Critical** | P0 |
| T-DISC-03 | Leaking recorded performances | High | P1 |
| T-DISC-04 | API response showing all venues' data | **Critical** | P0 |
| T-DISC-05 | Error messages exposing DB schema | Medium | P2 |

**Mitigations:**
- Field-level access control on API responses
- Venue-scoped queries (mandatory WHERE venue_id = ?)
- Encrypted storage for recordings with singer-only keys
- Generic error messages; detailed logs to SIEM

#### 5. Denial of Service (Availability Threats)

| Threat | Description | Risk | Priority |
|--------|-------------|------|----------|
| T-DOS-01 | Queue flooding with fake singers | High | P1 |
| T-DOS-02 | WebSocket connection exhaustion | Medium | P2 |
| T-DOS-03 | API rate limit exhaustion | Medium | P2 |
| T-DOS-04 | Database connection pool exhaustion | Medium | P2 |

**Mitigations:**
- Sliding window rate limiting per IP + per singer
- WebSocket connection quotas per venue
- Circuit breakers on DB operations
- Queue request throttling (max 3 per singer per hour)

#### 6. Elevation of Privilege (Authorization Threats)

| Threat | Description | Risk | Priority |
|--------|-------------|------|----------|
| T-ELEV-01 | Singer accessing venue admin APIs | **Critical** | P0 |
| T-ELEV-02 | Venue A accessing Venue B's data | **Critical** | P0 |
| T-ELEV-03 | KJ escalating to superadmin | High | P1 |
| T-ELEV-04 | Staff accessing deleted data | Medium | P2 |

**Mitigations:**
- Role-based access control (RBAC) with 4 roles
- Mandatory data isolation checks at every layer
- Permission checks on every API endpoint
- Soft deletes with strict role requirements for restore

---

## Authentication & Authorization Architecture

### Identity Model

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              IDENTITY HIERARCHY                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         SUPERADMIN                                   │   │
│  │                    (Platform Operator Only)                          │   │
│  │                   • Read all venues (audit only)                     │   │
│  │                   • Manage system configuration                      │   │
│  │                   • Cannot modify venue data                         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                      ┌─────────────┼─────────────┐                          │
│                      ▼             ▼             ▼                          │
│  ┌───────────────────────┐                                    ┌─────────┐│
│  │    VENUE_MANAGER      │                                    │ SINGER  ││
│  │    (Venue Owner)      │                                    │         ││
│  │ • Full venue access   │                                    │• Mobile ││
│  │ • Manage billing      │                                    │• Queue  ││
│  │ • Administer staff    │                                    │• History││
│  │ • Export data         │                                    └─────────┘│
│  └───────────────────────┘                                             │    │
│          │                                                            │    │
│          ▼                                                            │    │
│  ┌───────────────────────┐                                    ┌───────▼──┐│
│  │         KJ            │                                    │  PATRON   ││
│  │    (DJ/Operator)      │                                    │ (Venue)   ││
│  │ • Manage queue        │                                    │ • No app  ││
│  │ • Skip/bump singers   │                                    │ • Via QR  ││
│  │ • View history        │                                    │ • Queue   ││
│  │ • Cannot delete data  │                                    │   only     ││
│  └───────────────────────┘                                    └───────────┘│
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Token Architecture

We use a **dual-token system** with device binding for all human users.  Role
differentiation (singer, kj, venue_admin, platform_admin) is expressed via the `role`
claim inside the JWT, not by varying token lifetime.  Machine-to-machine (M2M)
clients use a separate, long-lived service-token model.

#### Access Token (JWT) — Human users
```json
{
  "sub": "singer_abc123",
  "role": "singer",
  "venue_id": null,
  "device_id": "device_xyz789",
  "iss": "scales-api",
  "aud": "scales-app",
  "iat": 1779228000,
  "exp": 1779228900
}
```

**Lifetime:** 15 minutes for all human roles.  
**Scope:** Determined by `role` + `venue_id` claims.  
**Rotation:** Monthly key rotation with 7-day grace period (see Key Management below).

#### Refresh Token — Human users
- 7-day expiration
- Single-use (rotates on each refresh)
- Stored in secure httpOnly cookie for web
- Stored in Keychain/Keystore for mobile

> **Cross-reference:**  
> - Access/refresh lifetimes are listed in [`api_spec.md` — Token Types](../t_97abe5ff/api_spec.md#token-types).  
> - Check-in response returns both tokens in [`api_spec.md` §3.1 Singer/Patron APIs](../t_97abe5ff/api_spec.md#singerpatron-apis).

#### Service Token — M2M / service accounts
- 30-day expiration (non-rotating unless manually revoked)
- No refresh token; services re-authenticate with client-credentials grant
- Stored in HashiCorp Vault, injected at deploy time
- Used for: batch jobs, analytics pipelines, inter-service sync

#### Device Tokens
- Generated on first app open without signup
- Used for queue operations before account creation
- Migrated to user token on signup/login
- Enables "queue without account" feature
- Bound to `device_id`; throttled under Tier B abuse-prevention limits

### Auth Flow

```
MOBILE APP                     API                    AUTH SERVICE
    │                           │                           │
    │── Register Device ──────▶│                           │
    │◁── device_token ─────────│                           │
    │                           │                           │
    │── Signup/Login ──────────▶│── Create Session ────────▶│
    │                           │◁── access_token + refresh_token ───│
    │◁── access_token ─────────│                           │
    │                           │                           │
    │── Refresh ───────────────▶│── Rotate Refresh ────────▶│
    │◁── new_access_token ─────│                           │
    │                           │                           │
    │── API Call ──────────────▶│── Validate JWT ──────────▶│
    │                           │◁── claims ────────────────│
    │◁── Response ─────────────│                           │
    │                           │                           │
    │── Revoke/Logout ─────────▶│── Clear Session ─────────▶│
    │◁── 200 OK ───────────────│                           │
    │                           │                           │
```

### Authorization Pattern: Resource Scoping

Every API request MUST validate two things:

```python
# Pseudocode for every protected endpoint
def require_venue_access(func):
    def wrapper(request, *args, **kwargs):
        token = extract_token(request)
        claims = verify_jwt(token)
        
        # Check 1: User has required role
        if claims.role not in REQUIRED_ROLES:
            raise InsufficientPermissions()
        
        # Check 2: Venue isolation
        if claims.role in ['kj', 'venue_manager']:
            # Venue-scoped roles can only access their venue
            if request.venue_id != claims.venue_id:
                raise CrossVenueAccessAttempt()
        
        # Check 3: Patron verification (QR/session)
        if request.path == '/api/songs/request':
            verify_patron_session(request)
        
        return func(request, *args, **kwargs)
    return wrapper
```

#### Venue Isolation Checklist

| Layer | Implementation |
|-------|---------------|
| Database | Every query has `WHERE venue_id = :venue_id` |
| API | Path parameters validated against token venue_id |
| WebSocket | Connection token includes venue_id, messages validated |
| Cache | Cache keys prefixed with `venue:{venue_id}:` |
| Files | Upload paths scoped to `/uploads/{venue_id}/` |

---

## Data Classification & Encryption

### Data Classification Matrix

| Data Type | Classification | Storage | Retention |
|-----------|-------------|---------|-----------|
| Singer email/phone | **PII - Sensitive** | Encrypted at rest | Until deletion request |
| Payment card tokens | **PCI Protected** | Stripe only | Per Stripe policy |
| Song queue data | Internal | Encrypted | 30 days |
| Performance scores | Internal | Encrypted | Venue-configurable |
| Session recordings | **PII - Sensitive** | Encrypted + access controlled | Singer-controlled |
| Venue financial data | **Confidential** | Encrypted at rest | 7 years (tax) |
| Anonymous analytics | Public | Anonymized | Indefinite |

### Encryption Strategy

#### At-Rest Encryption

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ENCRYPTION AT REST                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Cloud Database (PostgreSQL)                                               │
│   ┌────────────────────────────────────────────────────────────────┐       │
│   │  Field-Level Encryption                                         │       │
│   │  • PII columns: AES-256-GCM (application-layer)                 │       │
│   │  • DEK per venue (Data Encryption Key)                          │       │
│   │  • KEK in HSM (Key Encryption Key)                              │       │
│   └────────────────────────────────────────────────────────────────┘       │
│                                                                             │
│   Recording Files (Object Storage - S3/MinIO)                               │
│   ┌────────────────────────────────────────────────────────────────┐       │
│   │  Server-Side Encryption                                         │       │
│   │  • SSE-KMS: AWS KMS or HashiCorp Vault                        │       │
│   │  • Per-singer key derivation                                    │       │
│   │  • Access via signed URLs only                                │       │
│   └────────────────────────────────────────────────────────────────┘       │
│                                                                             │
│   Desktop App Local DB (SQLite)                                             │
│   ┌────────────────────────────────────────────────────────────────┐       │
│   │  SQLCipher with AES-256-CBC                                     │       │
│   │  • Key derived from user password + salt                      │       │
│   │  • Auto-lock after 5 min idle                                 │       │
│   └────────────────────────────────────────────────────────────────┘       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### In-Transit Encryption

- **TLS 1.3** minimum for all connections
- **Certificate pinning** in mobile apps (primary + backup pin)
- **HSTS** headers on web app
- **WebSocket wss://** only (no ws:// in production)

#### Key Management (HashiCorp Vault)

```yaml
# Vault secrets structure
secret/
├── scales/
│   ├── database/
│   │   └── postgres: {url, username, password}
│   ├── stripe/
│   │   ├── publishable_key: pk_live_xxx
│   │   ├── secret_key: sk_live_xxx  # RESTRICTED
│   │   └── webhook_secret: whsec_xxx
│   ├── encryption/
│   │   ├── kek_master: auto-rotated monthly
│   │   └── deks/  # per-venue keys
│   └── signing/
│       ├── jwt_primary: {key, alg: RS256}
│       └── jwt_old: {key, alg: RS256}  # rotation grace period
```

**Key Rotation:**
- JWT signing keys: monthly rotation, 7-day grace
- Database DEKs: annually or on suspected compromise
- API keys: on staff departure or suspected leak

---

## API & Infrastructure Security

### Rate Limiting Strategy

Rate limits are organised in **two independent tiers**: a generous UX tier for
routine browsing, and a strict abuse-prevention tier for write-heavy / sensitive
operations.  Both tiers apply simultaneously; exceeding either returns HTTP 429.

#### Tier A — UX Tier (per authenticated session)

| Endpoint Class | Limit | Window | Scope |
|--------------|-------|--------|-------|
| Public reads (songs, leaderboards) | 60 | minute | IP / token |
| Song browse / search | 100 | minute | singer / kj |
| Social reads (history, stats) | 60 | minute | singer |
| Social writes (favorites, check-ins, follows) | 20 | minute | singer |
| Merchandise reads (catalog, cart, orders) | 60 | minute | singer |
| Venue admin CRUD | 30 | minute | admin token |
| Platform admin | 120 | minute | admin token |
| Realtime (WebSocket) | 10 | second | connection |

#### Tier B — Abuse-Prevention Tier

| Endpoint | Limit | Window | Scope Key | Purpose |
|----------|-------|--------|-----------|---------|
| Auth flows (`/api/auth/*`) | 5 | hour | IP | Credential stuffing protection |
| Submit song request | 3 | hour | `singer_id + venue_id` | Queue flooding |
| Enter queue (anonymous / device) | 10 | hour | `device_id` | Device-based spam |
| Check-in (new session) | 5 | hour | `device_id` | Session abuse |
| Account creation / login | 5 | hour | IP | Bulk account creation |
| Password reset / recovery | 3 | hour | IP | Password-spray mitigation |
| Queue modifications (approve, reject, skip, reorder) | 30 | minute | `kj_id` | Accidental KJ mis-clicks |
| Stripe webhooks | 1000 | minute | Stripe IPs | Webhook ingestion safety |

The `X-RateLimit-Tier` response header declares which tier triggered a 429 (value
`ux` or `abuse_prevention`).  The 429 Problem Detail body includes a
`retry_after_minutes` hint for clients.

> **Cross-reference:** Tier limits are also listed in [`api_spec.md` — Rate Limiting](../t_97abe5ff/api_spec.md#rate-limiting), with response-header and error-schema detail.

### Input Validation Rules

```yaml
# API validation schema examples
song_request:
  singer_name:
    max_length: 50
    pattern: "^[A-Za-z0-9 _.-]+$"  # No script tags
    sanitize: true
  
email:
  format: RFC 5322
  max_length: 254
  normalize: lowercase
  verify_mx: optional  # For signup

sms_phone:
  format: E.164
  max_length: 15
  
user_message:
  max_length: 500
  html_escape: true
  strip_tags: true
```

### CORS Policy

```yaml
# CORS configuration
allowed_origins:
  - "https://app.scaleskaraoke.com"
  - "https://console.scaleskaraoke.com"
  - "https://cdn.scaleskaraoke.com"
  
allowed_methods: [GET, POST, PUT, DELETE, PATCH]
allowed_headers: [Authorization, Content-Type, X-Request-ID]
allow_credentials: true
max_age: 3600
```

### Security Headers

| Header | Value | Purpose |
|--------|-------|---------|
| Strict-Transport-Security | max-age=31536000; includeSubDomains | HSTS |
| Content-Security-Policy | default-src 'self'; ... | XSS prevention |
| X-Content-Type-Options | nosniff | MIME sniffing prevention |
| X-Frame-Options | DENY | Clickjacking prevention |
| Referrer-Policy | strict-origin-when-cross-origin | Referrer control |
| Permissions-Policy | geolocation=(self), camera=(self) | Feature limit |

---

## Compliance Framework

### GDPR Compliance

#### Data Mapping

| Category | Examples | Legal Basis | Retention |
|----------|----------|-------------|-----------|
| Account data | Email, password | Consent | Indefinite (until deletion) |
| Queue participation | Name, time, song choice | Legitimate interest | 30 days |
| Performance recordings | Video/audio files | Explicit consent | Until withdrawal |
| Marketing comms | Email preferences | Consent | Until opt-out |

#### GDPR Checklist

| Requirement | Implementation | Status |
|-------------|---------------|--------|
| **Lawful Basis** | | |
| Consent tracking | UI consent banners with granular options | ☐ |
| Legitimate interest documented | LIA for core service operations | ☐ |
| Privacy notice | Plain English privacy policy | ☐ |
| **Data Subject Rights** | | |
| Right to access | `/api/account/export-data` endpoint | ☐ |
| Right to rectification | In-app profile editing | ☐ |
| Right to erasure (RTBF) | `/api/account/delete` with 30-day wipe | ☐ |
| Right to restriction | Soft-delete mode for disputes | ☐ |
| Right to portability | JSON/CSV export per Singer | ☐ |
| Right to object | One-click marketing opt-out | ☐ |
| **Security & Accountability** | | |
| Data breach notification | 72h internal notification process | ☐ |
| Privacy by design | Security review in dev process | ☐ |
| DPO appointed | Required if systematic monitoring | ☐ |
| Records of processing | Data inventory maintained | ☐ |
| **Third Parties** | | |
| DPA with Stripe | Signed Data Processing Addendum | ☐ |
| DPA with cloud provider | AWS/GCP DPA signed | ☐ |
| Subprocessor list | Public on website | ☐ |

#### Right to Erasure (RTBF) Implementation

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          DATA DELETION FLOW                                 │
└─────────────────────────────────────────────────────────────────────────────┘

User requests deletion
         │
         ▼
┌─────────────────┐
│ Soft delete     │ ──► Mark account_deleted = true
│ (immediate)     │ ──► Revoke all sessions
└────────┬────────┘ ──► Cancel all subscriptions
         │
         ▼ (30 days)
┌─────────────────┐
│ Hard delete     │ ──► Delete PII from database
│ (permanent)     │ ──► Schedule S3 file deletion
└────────┬────────┘ ──► Notify Stripe of user deletion
         │
         ▼ (30 more days = 60 total)
┌─────────────────┐
│ Verify          │ ──► Confirm deletion from backups
│ completeness    │ ──► Log completion for audit
└─────────────────┘

BACKUP RETENTION: Encrypted backups retained 90 days, then shredded.
NOTE: Anonymized analytics data retained (no PII).
```

### CCPA Compliance

| Requirement | Implementation |
|-------------|---------------|
| "Do Not Sell" | No data sales. If we add this: dedicated toggle |
| Opt-out of sharing | Per-account setting in privacy dashboard |
| Deletion requests | Same as GDPR RTBF |
| Disclosure of categories | Privacy policy lists all categories collected |
| Collection notice | Notice at point of collection |
| Financial incentives | Document if any rewards programs added |

### PCI DSS Scope (Using Stripe Elements)

**Good news: PCI scope is minimal**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PCI DSS SCOPE FOR SCALES                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │   OUT OF SCOPE (Stripe handles)                                      │  │
│  │   • Card number collection                                           │  │
│  │   • CVV handling                                                     │  │
│  │   • Token storage (Stripe does this)                                 │  │
│  │   • PCI DSS Level 1 compliance audit                                 │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │   IN SCOPE (Scales must secure)                                      │  │
│  │   • Stripe tokens received (last4, brand) - encrypt at rest            │  │
│  │   • Webhook receiving - verify signature                             │  │
│  │   • SAQ-A compliance for self (simplest level)                       │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  Compliance: Complete SAQ-A annually                                        │
│  Provider: Stripe handles all card data; we never see full PAN/CVV        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### COPPA Assessment

**Initial Assessment: COPPA likely does NOT apply**

Rationale:
- Scales is a B2B2C platform (venues purchase, adults use)
- Primary use case: bars, clubs, adult entertainment venues
- No child-directed features or marketing

**COPPA Triggers (must monitor):**
| If this happens... | COPPA applies | Action needed |
|-------------------|---------------|---------------|
| Marketing to family venues | Maybe | Age gate + parental consent |
| "Kids karaoke" mode added | Yes | Full COPPA compliance |
| User reports under 13 account | Yes | Delete account immediately |

**Preventive Controls:**
- Terms of Service require age 13+
- No collecting of child-specific interests
- Report button for underage accounts

### Data Residency

| Data Type | Primary | Replicas | Notes |
|-----------|---------|----------|-------|
| EU singer data | EU region (Frankfurt) | EU only | GDPR requirement |
| US singer data | US region | US multi-region | Default |
| Venue configuration | Same as venue location | Same region | Latency |
| Backups | Same region | Cross-region (encrypted) | Disaster recovery |

---

## Security Controls Matrix

| Threat ID | STRIDE | Control | Implementation | Status |
|-----------|--------|---------|---------------|--------|
| T-SPOOF-01 | Spoofing | Device fingerprinting + SMS verification | Device ID + optional SMS | ☐ |
| T-SPOOF-02 | Spoofing | MFA for admin roles | TOTP via authenticator app for Venue Manager+ | ☐ |
| T-SPOOF-03 | Spoofing | Device binding | JWT includes device_id, rejects mismatches | ☐ |
| T-SPOOF-04 | Spoofing | WebSocket token validation | Auth token in connection, re-verify on sensitive ops | ☐ |
| T-TAMP-01 | Tampering | Signed queue operations | HMAC on queue modifications | ☐ |
| T-TAMP-02 | Tampering | Immutable performance records | Appends-only with singer-signed hash | ☐ |
| T-TAMP-03 | Tampering | TLS 1.3 + cert pinning | Enforced on all payment paths | ☐ |
| T-TAMP-04 | Tampering | Encrypted local DB with MAC | SQLCipher on desktop | ☐ |
| T-REPU-01 | Repudiation | Queue request logging | Immutable log of all song requests | ☐ |
| T-REPU-02 | Repudiation | Stripe receipt logging | Webhook signature verification + audit log | ☐ |
| T-REPU-03 | Repudiation | Deletion confirmation emails | Email notification on GDPR deletion | ☐ |
| T-REPU-04 | Repudiation | KJ action audit log | Every skip/bump logged with KJ ID | ☐ |
| T-DISC-01 | Disclosure | Field-level access control | API serializer excludes fields based on role | ☐ |
| T-DISC-02 | Disclosure | Mandatory venue_id scoping | SQL queries always filter by venue_id | ☐ |
| T-DISC-03 | Disclosure | Encryption at rest + signed URLs | Recordings encrypted, URLs expire | ☐ |
| T-DISC-04 | Disclosure | Query parameter validation | Path param vs token venue_id validation | ☐ |
| T-DISC-05 | Disclosure | Generic error messages | Production errors = generic; logs detailed | ☐ |
| T-DOS-01 | DoS | Rate limiting per singer | 3 requests/hour per singer per venue | ☐ |
| T-DOS-02 | DoS | WebSocket connection limits | 100 connections per venue | ☐ |
| T-DOS-03 | DoS | API rate limiting | Sliding window per IP and per user | ☐ |
| T-DOS-04 | DoS | Connection pooling | PgBouncer with limits per app | ☐ |
| T-ELEV-01 | Elevation | RBAC enforcement | Every endpoint checks role | ☐ |
| T-ELEV-02 | Elevation | Data isolation | Venue_id check on every query | ☐ |
| T-ELEV-03 | Elevation | Permission checks on elevation | Self-elevation attempts blocked | ☐ |
| T-ELEV-04 | Elevation | Soft delete restrictions | Only Venue Manager+ can restore | ☐ |

---

## Incident Response Plan

### Incident Classification

| Severity | Criteria | Response Time | Examples |
|----------|----------|---------------|----------|
| **SEV-1** | Data breach confirmed, service down, financial impact | 15 min | DB dumped, payment leak, venue crossing |
| **SEV-2** | Security incident suspected, degraded performance | 1 hour | Unusual API patterns, possible injection |
| **SEV-3** | Minor security issue, no confirmed impact | 4 hours | Failed auth attempts above threshold |
| **SEV-4** | Security question, documentation | 24 hours | "Is this secure?", pen test feedback |

### Response Playbooks

#### SEV-1: Data Breach Confirmed

```
T+0      Detect via alert or report
         ├── Page on-call security engineer
         └── Enable incident Slack channel
         
T+15min  Establish facts
         ├── What data was accessed?
         ├── When did it start/end?
         ├── Who was affected?
         └── How was access gained?
         
T+30min  Contain
         ├── Revoke compromised credentials/tokens
         ├── Block malicious IPs
         ├── Patch exploited vulnerability
         └── Enable additional logging
         
T+1hr    Assess
         ├── Determine if reportable breach
         ├── Prepare breach notification (if required)
         └── Identify regulatory obligations
         
T+4hrs   Notify
         ├── Internal: CTO, CEO, legal
         ├── External: Affected venues/singers
         └── Regulatory: GDPR = 72h, state law varies
         
T+24hrs  Recover
         ├── Restore from clean backup if needed
         ├── Force password resets if creds leaked
         └── Additional monitoring deployed
         
T+7days  Post-incident
         ├── Root cause analysis
         ├── Process improvements
         └── Public disclosure if material
```

#### Payment Security Incident (Stripe)

1. **Immediately**: Contact security@stripe.com
2. **Do not**: Process any new transactions until cleared
3. **Document**: All tokens potentially accessed
4. **Coordinate**: With Stripe's security team

### Contact Information

| Role | Primary | Secondary |
|------|---------|-----------|
| Security Lead | security@scaleskaraoke.com | PagerDuty |
| CTO | [cto phone] | [cto email] |
| Legal | [legal counsel] | [law firm] |
| Stripe Security | security@stripe.com | - |
| Cloud Provider | AWS/GCP security contact | Support escalation |

### Logging & Monitoring

**Security Events to Log:**
- All authentication attempts (success + failure)
- All privilege changes
- All data export operations
- All failed access control checks
- All token refreshes
- All WebSocket connections/disconnections
- All queue management actions (skip, bump, delete)
- All subscription/payment changes

**Retention:**
- Security logs: 1 year (compliance)
- Authentication logs: 90 days
- Operational logs: 30 days
- Archive: Encrypted S3 Glacier (7 years)

---

## Secrets Management Strategy

### Secret Classification

| Tier | Examples | Storage | Rotation |
|------|----------|---------|----------|
| Tier 1 | Stripe secret key, DB passwords, JWT signing keys | Vault only | Monthly |
| Tier 2 | API keys for internal services, SMTP credentials | Vault + env | Quarterly |
| Tier 3 | Feature flags, non-sensitive config | Config service | On change |

### Application Secret Handling

```python
# Pattern: Secrets fetched at startup, cached in memory only
# Never: Hardcoded, in repo, in env for production

from dataclasses import dataclass
from functools import lru_cache
import hvac  # HashiCorp Vault client

@dataclass
class Secrets:
    db_url: str
    stripe_secret_key: str
    stripe_webhook_secret: str
    jwt_signing_key: str
    
@lru_cache()
def load_secrets() -> Secrets:
    """Load secrets from Vault once at startup."""
    client = hvac.Client(url=VAULT_ADDR, token=get_vault_token())
    
    return Secrets(
        db_url=client.secrets.kv.v2.read_secret('scales/database')['data']['url'],
        stripe_secret_key=client.secrets.kv.v2.read_secret('scales/stripe')['data']['secret_key'],
        # ... etc
    )

# Usage
@app.on_event("startup")
async def init_app():
    app.state.secrets = load_secrets()
```

### Leak Prevention

| Risk | Mitigation |
|------|------------|
| Accidental code commit | Git pre-commit hook scanning for secrets |
| Log exposure | Automatic PII redaction in logs |
| Memory dump | Secrets never written to swap |
| Network sniffing | TLS 1.3 + mTLS between services |
| Insider threat | Vault audit logging, no manual DB access |

---

## Security Checklist & Recommendations

### Pre-Launch Security Checklist

#### Authentication & Authorization
- [ ] JWT signing uses RS256 with 2048+ bit keys
- [ ] Token expiry is 15 minutes max
- [ ] Refresh tokens rotate and are single-use
- [ ] RBAC enforced on every API endpoint
- [ ] Venue isolation verified (no cross-venue access possible)
- [ ] WebSocket connections authenticated per-message on sensitive ops
- [ ] MFA available for admin/venue manager roles
- [ ] Rate limiting implemented and tested

#### Data Protection
- [ ] PII encrypted at rest (AES-256-GCM)
- [ ] TLS 1.3 enforced (no downgrade)
- [ ] Certificate pinning configured in mobile apps
- [ ] Desktop app local DB encrypted (SQLCipher)
- [ ] Recording storage uses SSE-KMS
- [ ] Backup encryption with separate keys

#### API Security
- [ ] Input validation on all endpoints
- [ ] SQL injection prevention (parameterized queries)
- [ ] XSS prevention (output encoding)
- [ ] CSRF tokens for web forms
- [ ] CORS whitelist configured
- [ ] Security headers set

#### Compliance
- [ ] Privacy policy published and reviewed
- [ ] Terms of Service (13+ age requirement)
- [ ] Consent flows for data collection
- [ ] GDPR data export endpoint
- [ ] GDPR deletion endpoint
- [ ] Cookie consent banner (GDPR)
- [ ] Stripe DPA signed

#### Infrastructure
- [ ] Secrets in Vault (not repo)
- [ ] Database not publicly accessible
- [ ] API gateway configured with WAF rules
- [ ] Security logging to SIEM
- [ ] Automated security scanning in CI
- [ ] Dependency vulnerability scanning

#### Incident Response
- [ ] Security contact page published
- [ ] Incident response runbook written
- [ ] PagerDuty configured for SEV-1 alerts
- [ ] Legal counsel on retainer
- [ ] Breach notification templates prepared

### Security Roadmap

| Phase | Feature | Priority |
|-------|---------|----------|
| MVP | Basic auth, TLS, SQL injection prevention | P0 |
| MVP | Venue isolation, RBAC | P0 |
| MVP | Stripe integration w/ webhook verification | P0 |
| MVP | Rate limiting, input validation | P0 |
| V1.1 | Security audit by external firm | P1 |
| V1.1 | Automated pen testing in CI | P1 |
| V1.1 | Bug bounty program | P1 |
| V1.2 | Advanced MFA (biometric) | P2 |
| V1.2 | Runtime application self-protection (RASP) | P2 |
| V2.0 | Multi-region disaster recovery | P2 |

---

## Appendix A: WebSocket Security

### Authentication Flow

```
1. Client establishes WebSocket connection
2. Sends AUTH message with JWT: {"type": "auth", "token": "..."}
3. Server validates token, extracts venue_id
4. Server adds client to venue:{venue_id} room
5. All messages broadcast only to room members
6. On venue_id mismatch in message → disconnect
```

### Message Validation

```yaml
all_messages:
  - type: enum[queue_update, song_complete, singer_update, ...]
  - venue_id: must_match_token
  - payload: schema_validated
  - timestamp: within_5_min_skew
```

---

## Appendix B: Mobile App Security

### Implementation Requirements

| Control | iOS | Android |
|---------|-----|---------|
| Certificate pinning | TrustKit / Alamofire | Network Security Config |
| Root/jailbreak detection | runtime checks | SafetyNet / Play Integrity |
| Key storage | Secure Enclave | Android Keystore |
| Memory protection | Avoid sensitive data in logs | Same |
| Obfuscation | Swift code obfuscation | ProGuard/R8 |

---

## Appendix C: Stripe Webhook Security

```python
import stripe
import hmac
import hashlib

def verify_stripe_webhook(request):
    payload = request.body
    sig_header = request.headers['Stripe-Signature']
    webhook_secret = load_secrets().stripe_webhook_secret
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except ValueError:
        raise InvalidPayload()
    except stripe.error.SignatureVerificationError:
        raise InvalidSignature()  # Log and alert
    
    return event

# Idempotency: Track processed event IDs for 24 hours
PROCESSED_EVENTS = {}  # Redis in production

def handle_webhook(event):
    if event.id in PROCESSED_EVENTS:
        return  # Already processed, return 200
    
    # Process event...
    
    PROCESSED_EVENTS[event.id] = True
    PROCESSED_EVENTS.expire(event.id, 86400)
```

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | May 2026 | Security Team | Initial draft |
| 1.0 | May 2026 | Security Team | Review complete, approved |

---

**Next Review Date:** November 2026  
**Owner:** Security Team  
**Approval:** CTO, Legal
