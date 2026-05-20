# Scales Karaoke Platform — Security Architecture

> **Version**: 1.1  
> **Status**: Final  > **Date**: 2026-05-19  
> **Synthesized from**: t_47927d77 (Security Arch) + t_20644505 (Token/Rate Limit Reconciliation) + t_97abe5ff (API Spec)  
> **Classification**: Internal

---

## 1. Executive Summary

Scales handles four categories of sensitive data: (1) **singer/staff PII** (names, emails, phones, device IDs), (2) **venue business data** (financials, operations), (3) **payment tokens** (outsourced to Stripe), and (4) **content data** (recorded performances). This document establishes the threat model, authentication/authorization architecture, encryption strategy, compliance posture, and operational controls.

---

## 2. Threat Model (STRIDE)

### 2.1 System Context

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

### 2.2 Threat Register

| ID | STRIDE | Threat | Risk | Priority |
|----|--------|--------|------|----------|
| T-SPOOF-01 | Spoofing | Fake singer profile with stolen identity | Medium | P2 |
| T-SPOOF-02 | Spoofing | **Stolen admin/venue manager credentials** | **Critical** | P0 |
| T-SPOOF-04 | Spoofing | WebSocket connection impersonation | High | P1 |
| T-TAMP-01 | Tampering | Malicious song queue reorder | Medium | P2 |
| T-TAMP-02 | Tampering | Modified performance scores/votes | High | P1 |
| T-TAMP-03 | Tampering | **Modified payment amounts in transit** | **Critical** | P0 |
| T-REPU-02 | Repudiation | **Venue denies receiving payment** | **Critical** | P0 |
| T-DISC-01 | Disclosure | Leaking singer email/phone to other singers | High | P1 |
| T-DISC-02 | Disclosure | **Exposing venue financial data across venues** | **Critical** | P0 |
| T-DISC-04 | Disclosure | API response showing all venues' data | **Critical** | P0 |
| T-DOS-01 | DoS | Queue flooding with fake singers | High | P1 |
| T-DOS-02 | DoS | WebSocket connection exhaustion | Medium | P2 |
| T-ELEV-01 | Elevation | **Singer accessing venue admin APIs** | **Critical** | P0 |
| T-ELEV-02 | Elevation | **Venue A accessing Venue B's data** | **Critical** | P0 |
| T-ELEV-03 | Elevation | KJ escalating to superadmin | High | P1 |

**Full register**: 20 threats modeled. See source document for complete listings.

---

## 3. Authentication & Authorization Architecture

### 3.1 Identity Model

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              IDENTITY HIERARCHY                              │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         PLATFORM_ADMIN                               │   │
│  │                    (Platform Operator Only)                          │   │
│  │                   • Read all venues (audit only)                     │   │
│  │                   • Manage system configuration                      │   │
│  │                   • Cannot modify venue data                         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                      ┌─────────────┼─────────────┐                          │
│                      ▼             ▼             ▼                          │
│  ┌───────────────────────┐                                    ┌─────────┐│
│  │    VENUE_ADMIN      │                                    │ SINGER  ││
│  │    (Venue Owner)      │                                    │         ││
│  │ • Full venue access   │                                    │• Mobile ││
│  │ • Manage billing      │                                    │• Queue  ││
│  │ • Administer staff    │                                    │• History││
│  │ • Export data         │                                    └─────────┘│
│  └───────────────────────┘                                             │    │
│          │                                                            │    │
│          ▼                                                            │    │
│  ┌───────────────────────┐                                    ┌───────▼──┐│
│  │         KJ            │                                    │  ANON     ││
│  │    (DJ/Operator)      │                                    │ (Device)  ││
│  │ • Manage queue        │                                    │ • No app  ││
│  │ • Skip/bump singers   │                                    │ • Via QR  ││
│  │ • View history        │                                    │ • Queue   ││
│  │ • Cannot delete data  │                                    │   only     ││
│  └───────────────────────┘                                    └───────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Token Architecture

Scales uses a **dual-token system** with device binding for all human users. Role differentiation is in the JWT `role` claim, not token lifetime.

#### Access Token (JWT) — Human users
```json
{
  "sub": "singer_abc123",
  "role": "singer",
  "venue_id": "ven_123",
  "device_id": "device_xyz789",
  "iss": "scales-api",
  "aud": "scales-app",
  "iat": 1779228000,
  "exp": 1779228900
}
```

**Lifetime**: **15 minutes** for all human roles.  
**Scope**: Determined by `role` + `venue_id` claims.

#### Refresh Token — Human users
- 7-day expiration
- Single-use (rotates on each refresh)
- Stored in secure httpOnly cookie (web) or Keychain/Keystore (mobile)

#### Service Token — M2M / service accounts
- 30-day expiration (non-rotating unless manually revoked)
- No refresh token; client-credentials grant
- Stored in HashiCorp Vault, injected at deploy time

#### Device Tokens
- Generated on first app open without signup
- Enables "queue without account" feature
- Throttled under Tier B abuse-prevention limits

### 3.3 Venue Isolation Checklist

| Layer | Implementation |
|-------|---------------|
| Database | Every query has `WHERE venue_id = :venue_id`; RLS enforces it in PostgreSQL |
| API | Path parameters validated against token `venue_id` |
| WebSocket | Connection token includes `venue_id`; messages validated server-side |
| Cache | Cache keys prefixed with `venue:{venue_id}:` |
| Files | Upload paths scoped to `/uploads/{venue_id}/` |

---

## 4. Data Classification & Encryption

### 4.1 Data Classification Matrix

| Data Type | Classification | Storage | Retention |
|-----------|-------------|---------|-----------|
| Singer email/phone | **PII - Sensitive** | Encrypted at rest | Until deletion request |
| Payment card tokens | **PCI Protected** | Stripe only | Per Stripe policy |
| Song queue data | Internal | Encrypted | 30 days |
| Performance scores | Internal | Encrypted | Venue-configurable |
| Session recordings | **PII - Sensitive** | Encrypted + access controlled | Singer-controlled |
| Venue financial data | **Confidential** | Encrypted at rest | 7 years (tax) |
| Anonymous analytics | Public | Anonymized | Indefinite |

### 4.2 Encryption Strategy

#### At Rest
- **Cloud Database (PostgreSQL)**: Field-level AES-256-GCM for PII columns. DEK per venue; KEK in HSM.
- **Recording Files (R2)**: Server-side encryption with per-singer key derivation. Access via signed URLs only.
- **Desktop App Local DB (SQLite)**: SQLCipher with AES-256-CBC. Key derived from user password + salt. Auto-lock after 5 min idle.

#### In Transit
- **TLS 1.3** minimum for all connections
- **Certificate pinning** in mobile apps (primary + backup pin)
- **HSTS** headers on web app
- **WebSocket wss://** only (no ws:// in production)

### 4.3 Key Management (HashiCorp Vault)

```yaml
secret/
├── scales/
│   ├── database/
│   │   └── postgres: {url, username, password}
│   ├── stripe/
│   │   ├── publishable_key: pk_live_xxx
│   │   ├── secret_key: sk_live_xxx
│   │   └── webhook_secret: whsec_xxx
│   ├── encryption/
│   │   ├── kek_master: auto-rotated monthly
│   │   └── deks/  # per-venue keys
│   └── signing/
│       ├── jwt_primary: {key, alg: RS256}
│       └── jwt_old: {key, alg: RS256}  # rotation grace
```

**Rotation cadence:**
- JWT signing keys: monthly, 7-day grace
- Database DEKs: annually or on suspected compromise
- API keys: on staff departure or suspected leak

---

## 5. API & Infrastructure Security

### 5.1 Rate Limiting (Two-Tier)

Rate limits are organized into two independent tiers. Both apply simultaneously; exceeding either returns HTTP 429.

#### Tier A — UX Tier (per authenticated session)

| Endpoint Class | Limit | Window |
|----------------|-------|--------|
| Public reads (songs, leaderboards) | 60 | minute |
| Song browse / search | 100 | minute |
| Social writes (favorites, check-ins) | 20 | minute |
| Venue admin CRUD | 30 | minute |
| Platform admin | 120 | minute |
| Realtime (WebSocket) | 10 | second |

#### Tier B — Abuse-Prevention Tier

| Endpoint | Limit | Window | Scope Key |
|----------|-------|--------|-----------|
| Submit song request | 3 | hour | `singer_id + venue_id` |
| Enter queue (anonymous) | 10 | hour | `device_id` |
| Check-in (new session) | 5 | hour | `device_id` |
| Auth flows | 5 | hour | `IP` |
| Password reset | 3 | hour | `IP` |
| Queue modifications (KJ) | 30 | minute | `kj_id` |

Response headers: `X-RateLimit-Tier` declares which tier triggered the 429. The Problem Detail body includes `retry_after_minutes`.

### 5.2 Input Validation

- `singer_name`: max 50 chars, `^[A-Za-z0-9 _.-]+$`, sanitized
- `email`: RFC 5322, max 254, normalized lowercase, optional MX verify
- `sms_phone`: E.164, max 15
- `user_message`: max 500, HTML-escaped, tags stripped

### 5.3 Security Headers

| Header | Value |
|--------|-------|
| Strict-Transport-Security | max-age=31536000; includeSubDomains |
| Content-Security-Policy | default-src 'self'; ... |
| X-Content-Type-Options | nosniff |
| X-Frame-Options | DENY |
| Referrer-Policy | strict-origin-when-cross-origin |

### 5.4 Defense in Depth (Infrastructure)

```
Layer 1: Network
├── VPC with private subnets
├── Security groups: least-privilege
├── AWS WAF: SQLi, XSS, rate limiting
└── AWS Shield Advanced: DDoS

Layer 2: Application
├── JWT with 15-min expiry
├── Refresh token rotation
├── Pydantic input validation
├── SQLAlchemy + parameterised queries
└── CORS whitelist per venue domain

Layer 3: Data
├── RDS encryption at rest (AES-256)
├── TLS 1.3 in transit
├── R2/S3 private by default
├── Secrets Manager rotation
└── Field-level PII encryption

Layer 4: Operations
├── CloudTrail logging
├── GuardDuty threat detection
├── Config rules compliance scanning
└── IAM roles (no long-term keys)
```

---

## 6. Compliance Framework

### 6.1 GDPR

| Requirement | Implementation |
|-------------|---------------|
| Lawful basis | Consent banners + documented legitimate interest |
| Right to access | `GET /me/export-data` (JSON/CSV ZIP bundle) |
| Right to erasure | `POST /me/delete` — soft-delete immediately, hard-delete after 30-day grace |
| Right to portability | JSON/CSV export per singer |
| Data breach notification | 72h internal process; regulatory notification flow |
| Data residency | EU singer data → Frankfurt region RDS; US → default region |

### 6.2 CCPA

| Requirement | Implementation |
|-------------|---------------|
| "Do Not Sell" | No data sales. Dedicated toggle if added later. |
| Opt-out of sharing | Per-account privacy dashboard setting |
| Deletion requests | Same pipeline as GDPR RTBF |
| Disclosure of categories | Listed in privacy policy |

### 6.3 PCI DSS (via Stripe)

**Scope is minimal** because Stripe Connect Standard handles all card data. Scales is SAQ-A compliant.

- Out of scope: Card number collection, CVV handling, token storage
- In scope: Stripe tokens received (last4, brand) — encrypt at rest; webhook signature verification

### 6.4 COPPA Assessment

Likely **does not apply** (B2B2C platform for adult venues). Triggers to monitor:
- Marketing to family venues → age gate + parental consent
- "Kids karaoke" mode added → full COPPA compliance
- Terms of Service already require age 13+

---

## 7. Incident Response Plan

### 7.1 Severity Classification

| Severity | Criteria | Response Time | Examples |
|----------|----------|---------------|----------|
| **SEV-1** | Data breach confirmed, service down, financial impact | 15 min | DB dumped, payment leak |
| **SEV-2** | Security incident suspected, degraded performance | 1 hour | Unusual API patterns |
| **SEV-3** | Minor security issue, no confirmed impact | 4 hours | Failed auth spike |
| **SEV-4** | Security question, documentation | 24 hours | Pen test feedback |

### 7.2 SEV-1 Playbook (Data Breach)

| Time | Action |
|------|--------|
| T+0 | Page on-call security engineer; open incident channel |
| T+15min | Establish facts: what data, when, who affected, how accessed |
| T+30min | Contain: revoke compromised tokens, block IPs, patch vulnerability |
| T+1hr | Assess reportability; prepare breach notification |
| T+4hrs | Notify: internal (CTO, CEO, legal), external (affected venues), regulatory (GDPR 72h) |
| T+24hrs | Recover: restore from clean backup, force password resets |
| T+7days | Post-incident: root cause analysis, process improvements |

### 7.3 Security Event Logging

Log to SIEM with 1-year retention:
- All authentication attempts (success + failure)
- All privilege changes
- All data export operations
- All failed access control checks
- All token refreshes
- All WebSocket connections/disconnections
- All queue management actions (skip, bump, delete)
- All subscription/payment changes

---

## 8. Pre-Launch Security Checklist

### Authentication & Authorization
- [ ] JWT signing uses RS256 with 2048+ bit keys
- [ ] Token expiry is 15 minutes max
- [ ] Refresh tokens rotate and are single-use
- [ ] RBAC enforced on every API endpoint
- [ ] Venue isolation verified (no cross-venue access possible)
- [ ] WebSocket connections authenticated per-message on sensitive ops
- [ ] MFA available for admin/venue manager roles
- [ ] Rate limiting implemented and tested

### Data Protection
- [ ] PII encrypted at rest (AES-256-GCM)
- [ ] TLS 1.3 enforced (no downgrade)
- [ ] Certificate pinning configured in mobile apps
- [ ] Desktop app local DB encrypted (SQLCipher)
- [ ] Backup encryption with separate keys

### API Security
- [ ] Input validation on all endpoints
- [ ] SQL injection prevention (parameterized queries)
- [ ] XSS prevention (output encoding)
- [ ] CSRF tokens for web forms
- [ ] CORS whitelist configured
- [ ] Security headers set

### Compliance
- [ ] Privacy policy published
- [ ] Terms of Service (13+ age requirement)
- [ ] Consent flows for data collection
- [ ] GDPR export + deletion endpoints
- [ ] Stripe DPA signed

### Infrastructure
- [ ] Secrets in Vault (not repo)
- [ ] Database not publicly accessible
- [ ] API gateway configured with WAF rules
- [ ] Automated security scanning in CI
- [ ] Dependency vulnerability scanning

---

## 9. Security Roadmap

| Phase | Feature | Priority |
|-------|---------|----------|
| MVP | Basic auth, TLS, SQL injection prevention | P0 |
| MVP | Venue isolation, RBAC | P0 |
| MVP | Stripe integration w/ webhook verification | P0 |
| V1.1 | External security audit | P1 |
| V1.1 | Automated pen testing in CI | P1 |
| V1.1 | Bug bounty program | P1 |
| V1.2 | Advanced MFA (biometric) | P2 |
| V2.0 | Multi-region disaster recovery | P2 |

---

## 10. Document History

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | May 2026 | Initial draft (t_47927d77) |
| 1.0 | May 2026 | Review complete |
| 1.1 | May 2026 | Reconciled token lifetimes (15m/7d) and two-tier rate limits with api_spec.md |

**Next Review:** November 2026
