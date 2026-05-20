# Scales Documentation Hub

Complete technical documentation for the Scales karaoke ecosystem.

## Quick Links

| Repository | Purpose | Link |
|------------|---------|------|
| **ScalesMobile** | Flutter mobile apps | [GitHub](https://github.com/Garenthino/ScalesMobile) |
| **ScalesInfrastructure** | Backend, API, web portal | [GitHub](https://github.com/Garenthino/ScalesInfrastructure) |
| **DragonHost2-Hermes** | Windows KJ software | Private |

---

## Document Index

### API Specification
📄 **[API Specification](api/api_spec.md)** — Complete REST API with authentication, endpoints, rate limits, and error handling.

### Database & Data Models
📄 **[Data Models](db/data_models.md)** — Unified canonical models, CRDT sync strategy, SQLite↔PostgreSQL alignment.

### Infrastructure & Architecture
- 📄 **[Portal Architecture](infrastructure/portal_architecture.md)** — Multi-tenant web dashboard (React + FastAPI + Socket.IO)
- 📄 **[Portal Backend](infrastructure/portal_backend.md)** — FastAPI REST API structure and endpoints

### Security
📄 **[Security Overview](security/overview.md)** — Authentication flows, encryption standards, GDPR, audit logging, compliance (PCI-DSS, SOC-2).

### Gamification
📄 **[Loyalty Design](gamification/loyalty_design.md)** — Points system, streak mechanics, venue-specific events, redemption flows.

---

## Architecture Decision Records

| ADR | Decision | Status |
|-----|----------|--------|
| ADR-001 | API-First Design | ✅ Ratified |
| ADR-002 | Offline-First Sync with CRDTs | ✅ Ratified |
| ADR-003 | Unified Data Schema (SQLite↔PG) | ✅ Ratified |
| ADR-004 | Multi-Tenancy via RLS | ✅ Ratified |
| ADR-005 | White-Label Architecture | ✅ Ratified |

---

## Cross-Repository Links

```
┌─────────────────────────────────────────────────────────────┐
│  ScalesMobile          ScalesInfrastructure                 │
│  ─────────────         ───────────────────                  │
│  ├─ docs/architecture  ├─ docs/api                          │
│  │   └─ overview.md    ├─ docs/db                             │
│  │   └─ white_label.md ├─ docs/security                       │
│  └─ apps/*             ├─ docs/infrastructure                 │
│                        └─ docs/gamification                 │
└─────────────────────────────────────────────────────────────┘
```

---

*Last updated: May 2026*
