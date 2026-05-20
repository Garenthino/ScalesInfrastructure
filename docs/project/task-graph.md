Scales Epic: System Architecture — Task Graph
==================================================

Phase 1 (PARALLEL) — Specialist Research
--------------------------------------------------
All six tasks run concurrently. No dependencies between them.

t_f9f964d4 — Technology Stack Research & Key Decisions
  Profile: researcher
  Scope: Rank all 10 key decisions (real-time, backend stack, DB, sync,
         multi-tenancy, payments, GDPR, push notifications, file storage)
  Outcome: tech-decisions.md with GO / CONDITIONAL GO / NO GO rankings

t_97abe5ff — API Specification & Backend Architecture
  Profile: backend
  Scope: Full REST API inventory (venue, songs, singers, queue, loyalty,
         merchandise, social, analytics, exports, KJ sync)
  Outcome: api_spec.md with endpoint definitions + real-time event schemas

t_c512b8f6 — Mobile App & KJ Desktop Architecture
  Profile: frontend
  Scope: Flutter mobile offline-first architecture + KJ desktop app stack
         (Electron/Tauri/WinUI/Flutter Desktop)
  Outcome: frontend_arch.md with state management, screen inventory,
           data flows, conflict resolution

t_15b21353 — Infrastructure & Deployment Architecture
  Profile: devops
  Scope: Cloud topology, multi-tenant hosting, scaling, CI/CD,
         backup/DR, cost estimation
  Outcome: infra_arch.md with service topology, deployment patterns,
           scaling strategy

t_47927d77 — Security Architecture & Compliance Review
  Profile: security
  Scope: Auth/AuthZ, threat model, encryption, payments, GDPR/CCPA,
         PCI scope, incident response
  Outcome: security_arch.md with STRIDE threat model, compliance checklist

t_b3c1b205 — Database Schema Design
  Profile: cto
  Scope: Full multi-tenant schema, ER diagram, SQLite ↔ PostgreSQL
         compatibility, sync classification per table
  Outcome: db_schema.md with table definitions, indexes, sync rules

Phase 2 (SERIAL) — Synthesis
--------------------------------------------------
Depends on ALL Phase 1 tasks completing.

t_8d5af726 — Architecture Synthesis & Final Document
  Profile: planner
  Parents: [all 6 above]
  Scope: Resolve conflicts, assemble master System Architecture Document
         plus derived deliverables (API spec, DB schema, component
         diagrams, tech stack, security review)

Deliverables
--------------------------------------------------
Final workspace will contain:
  system_architecture.md — master document
  api_specification.md   — OpenAPI-style endpoint reference
  database_schema.md     — ER diagrams + table definitions
  component_diagrams.md  — interaction flows
  technology_stack.md    — cohesive stack with justifications
  security_architecture.md — security + compliance summary
