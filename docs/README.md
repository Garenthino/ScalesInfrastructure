# Scales Infrastructure — Architecture Documentation Index

> **Project**: Scales Karaoke Platform  
> **Last Updated**: May 19, 2026  
> **Status**: Phase 1 Complete (Synthesis)

## Document Map

| Document | Scope | Lines |
|---|---|---|
| [`system_architecture.md`](system_architecture.md) | Master system overview, actors, data flow, deployment topology | 300 |
| [`api/api_specification.md`](api/api_specification.md) | Full REST/WebSocket/SSE API spec with auth, rate limits, endpoints | 726 |
| [`api/openapi.yaml`](api/openapi.yaml) | Machine-readable OpenAPI 3.1 spec (generated from tables above) | — |
| [`db/schema.md`](db/schema.md) | PostgreSQL schema — 27 tables, ER relationships, indexes, constraints | 1227 |
| [`components/component_diagrams.md`](components/component_diagrams.md) | 4 interaction flows + failure-mode annotations | 258 |
| [`decisions/technology_stack.md`](decisions/technology_stack.md) | Language, framework, infra choices with rationale | 209 |
| [`decisions/adr-index.md`](decisions/adr-index.md) | Architecture Decision Records (ADRs) from specialist research | — |
| [`security/security_architecture.md`](security/security_architecture.md) | STRIDE threat model, RLS policies, compliance, incident response | 435 |
| [`infrastructure/infra_arch.md`](infrastructure/infra_arch.md) | Cloud layout, CI/CD, monitoring, disaster recovery | — |
| [`integrations/kj-integration.md`](integrations/kj-integration.md) | KJ booth ↔ backend sync protocol, offline resilience | — |
| [`gamification/loyalty-design.md`](gamification/loyalty-design.md) | Points, tiers, achievements, reward mechanics | — |
| [`project/task-graph.md`](project/task-graph.md) | Original Phase 1 kanban decomposition graph | — |

## Cross-References

- **Security considerations** are threaded through every document. Start with [`security/security_architecture.md`](security/security_architecture.md).
- **Database decisions** are grounded in [`db/schema.md`](db/schema.md) and referenced from [`api/api_specification.md`](api/api_specification.md).
- **Tech choices** are justified in [`decisions/technology_stack.md`](decisions/technology_stack.md) and [`decisions/adr-index.md`](decisions/adr-index.md).
- **Rate limiting** is defined in [`api/api_specification.md`](api/api_specification.md) §Rate Limiting.
- **Real-time events** (WebSocket/SSE) are in [`api/api_specification.md`](api/api_specification.md) §Real-Time Event Schemas.

## Key Architectural Decisions

| ID | Decision | Resolution |
|---|---|---|
| B-1 | Backend language | Hybrid FastAPI + Node.js/Socket.IO ratified |
| B-2 | Real-time protocol | Socket.IO with Redis adapter, rooms, fallback chain |
| B-3 | Token lifetimes | 15m access + 7d refresh for humans; 30d M2M service token |
| B-4 | Rate limits | Two-tier: Tier A UX per-minute + Tier B abuse-prevention per-hour |

## Source

These documents were synthesized from 8 parallel specialist tasks during Phase 1 of the Scales Epic. See [`project/task-graph.md`](project/task-graph.md) for the original decomposition.
