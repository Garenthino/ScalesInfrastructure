# Scales Infrastructure Architecture

> Cloud infrastructure and deployment architecture for the Scales karaoke platform.

---

## 1. Executive Summary

**Cloud Provider: AWS (Amazon Web Services)**

**Rationale:**
- **Mature multi-tenant database services:** RDS PostgreSQL with row-level security support
- **Real-time WebSocket/SSE:** API Gateway WebSocket API + ElastiCache Redis
- **SQLite sync capabilities:** S3 for file storage, Lambda for processing pipelines
- **Flutter CI/CD:** AWS Amplify + CodePipeline with Flutter/Android emulator support
- **Cost predictability:** Reserved instance pricing, Savings Plans for predictable workload
- **Operational maturity:** Comprehensive CloudWatch, X-Ray tracing, Security Hub compliance

---

## 2. Service Topology Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              SCales Karaoke Platform                                │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌─────────────┐                                                                    │
│  │   Users     │                                                                    │
│  │ ┌─────────┐ │                                                                    │
│  │ │ Mobile  │ │                                                                    │
│  │ │ Flutter │ │                     ┌─────────────────────────────┐                 │
│  │ └────┬────┘ │                     │      AWS Region             │                 │
│  │      │      │                     │  ┌─────────────────────┐   │                 │
│  │ ┌────┴────┐ │                     │  │   CloudFront CDN    │   │                 │
│  │ │   KJ    │ │─────────────────────│  │  (Global Edge)      │   │                 │
│  │ │ Desktop │ │                     │  └──────────┬──────────┘   │                 │
│  │ └─────────┘ │         ┌───────────┤             │              │                 │
│  └─────────────┘         │ S3 +     │             ▼              │                 │
│                          │  Lambda  │         ┌────────┐        │                 │
│                          │  Sync    │         │ Route  │        │                 │
│                          └──────────│         │ 53     │        │                 │
│                                     │         └───┬────┘        │                 │
│                                     │             │              │                 │
│                                     │             ▼              │                 │
│                                     │  ┌──────────────────────┐  │                 │
│                                     │  │ API Gateway (REST)   │  │                 │
│                                     │  │ + WAF                │  │                 │
│                                     │  └──────────┬───────────┘  │                 │
│                                     │             │              │                 │
│    ┌──────────────────────┐         │             ▼              │                 │
│    │ Firebase /         │         │  ┌────────────────────┐   │                 │
│    │ OneSignal          │◄────────│  │ API Gateway        │   │                 │
│    │ Push Notifications │         │  │ (WebSocket)        │   │                 │
│    └──────────────────────┘         │  └─────────┬──────────┘   │                 │
│                                     │            │              │                 │
│                                     │            │              │                 │
│                          ┌──────────┼────────────┼──────────┐  │                 │
│                          │  VPC     │            │    VPC   │  │                 │
│                          │ ┌────────┴────────────▼────────┐ │  │                 │
│                          │ │       ECS / Fargate         │ │  │                 │
│                          │ │     ┌─────────┐ ┌─────────┐   │ │  │                 │
│                          │ │     │ API     │ │ WebSocket│  │ │  │                 │
│                          │ │     │ Service │ │ Service  │  │ │  │                 │
│                          │ │     │ (REST)  │ │ (RTC)    │  │ │  │                 │
│                          │ │     └────┬────┘ └────┬────┘   │ │  │                 │
│                          │ │          │           │        │ │  │                 │
│                          │ │          │           │        │ │  │                 │
│                          │ │     ┌────┴───────────┴───┐     │ │  │                 │
│                          │ │     │   ElastiCache    │     │ │  │                 │
│                          │ │     │   Redis Cluster  │     │ │  │                 │
│                          │ │     │   (Real-time)    │     │ │  │                 │
│                          │ │     └──────────────────┘     │ │  │                 │
│                          │ │              │               │ │  │                 │
│                          │ └──────────────┼───────────────┘ │  │                 │
│                          └──────────────────┼───────────────┘  │                 │
│                                             │                  │                 │
│                          ┌───────────────────┘                  │                 │
│                          │                                     │                 │
│                          ▼                                     │                 │
│    ┌────────────────────────────────────────────────────────┐   │                 │
│    │                 RDS Aurora PostgreSQL                 │   │                 │
│    │  ┌───────────────────────────────────────────────────┐  │   │                 │
│    │  │  ┌─────────────┐  ┌─────────────┐  ┌───────────┐│  │   │                 │
│    │  │  │  Reader     │  │   Writer    │  │ Reader    ││  │   │                 │
│    │  │  │  Instance   │  │  Instance   │  │ Instance  ││  │   │                 │
│    │  │  └─────────────┘  └─────────────┘  └───────────┘│  │   │                 │
│    │  └───────────────────────────────────────────────────┘  │   │                 │
│    │  ┌───────────────────────────────────────────────────┐  │   │                 │
│    │  │ Row-Level Security (RLS) per venue_id tenant    │  │   │                 │
│    │  │ Separate schemas for tenant isolation option  │  │   │                 │
│    │  └───────────────────────────────────────────────────┘  │   │                 │
│    └────────────────────────────────────────────────────────┘   │                 │
│                              │                                   │                 │
│                              ▼                                   │                 │
│    ┌──────────────────────────────────────────────────────────┐ │                 │
│    │ S3 Buckets                                             │ │                 │
│    │ ├─ venues/{id}/song-metadata/                         │ │                 │
│    │ ├─ venues/{id}/user-avatars/                          │ │                 │
│    │ ├─ venues/{id}/export-files/                          │ │                 │
│    │ ├─ kj-app-backups/                                    │ │                 │
│    │ └─ ci-build-artifacts/                                │ │                 │
│    └──────────────────────────────────────────────────────────┘ │                 │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Multi-Tenant Deployment Pattern

### 3.1 Approach: **Shared Infrastructure with Row-Level Security**

**Choice Rationale:**
|| Approach | Pros | Cons | Decision |
||----------|------|------|----------|
|| Shared DB + RLS (venue_id) | Cost-efficient, simpler migrations, easy ops, single sync config | Must enforce RLS policies; shared resources | **PRIMARY** |
|| Dedicated DB per tenant | True isolation, easier per-tenant scale, clean compliance | Prohibitively expensive at 1000s | Future "Enterprise" tier only (see ADR-004) |

**Note:** An earlier draft considered schema-per-tenant. It was evaluated and set aside in favor of RLS. See ADR-004 for the full ratification. Schema-per-tenant was never implemented.

> **Updated 2026-05-19:** This strategy was ratified by ADR-004. The original t_f9f964d4 document recommended schema-per-tenant; that was revised. All schema DDL, middleware, and sync configs now assume RLS with `venue_id`. See `ADR-004-multi-tenancy-strategy.md` for rationale.

### 3.2 Implementation

**Database Layer (PostgreSQL RLS):**
```sql
-- Enable RLS on all tenant tables
ALTER TABLE songs ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE queue_items ENABLE ROW LEVEL SECURITY;

-- Create policy that restricts to authenticated venue
CREATE POLICY venue_isolation ON songs
    USING (venue_id = current_setting('app.current_venue_id')::UUID);

-- Application sets tenant context per request
SET app.current_venue_id = 'venue-uuid-from-jwt';
```

**Compute Layer (Shared ECS with tenant routing):**
- Single ECS cluster running FastAPI containers
- JWT token includes `venue_id` claim
- Middleware extracts tenant and sets DB context
- Container CPU/memory limits isolate noisy neighbors

**Alternative for VIP Tenants:**
- Dedicated ECS service + dedicated RDS reader
- Separate S3 prefix with bucket policy
- Costs: +$200-500/month per VIP tenant

---

## 4. Scaling Strategy for Peak Loads

### 4.1 Traffic Pattern Analysis

| Pattern | Frequency | Magnitude | Strategy |
|-----------|-----------|-------------|----------|
| Baseline | Always | 1x | Standard capacity |
| Evening surge | Weekdays 7-11pm | 3-5x | Auto-scaling ready |
| Weekend peak | Fri-Sat night | 10-20x | Warmed capacity + burst |
| Holiday surge | New Year's, karaoke nights | 50x+ | Emergency scaling manual |

### 4.2 Scaling Mechanisms

**Auto-Scaling Configuration:**
```yaml
ECS Service Auto Scaling:
  target_tracking:
    metric: ECS_CPU_UTILIZATION
    target_value: 70%
  scale_out:
    cooldown: 60s
    adjustment: +2 tasks (up to 50)
  scale_in:
    cooldown: 300s  # Prevent thrashing
    adjustment: -1 task (minimum 2)

RDS Aurora:
  reader_instances:
    minimum: 1
    maximum: 5
    scale_metric: CPU > 70% or Connections > 80%
```

**Pre-warming Strategy (Friday/Saturday):**
- Scheduled Auto Scaling: Scale out to 10 tasks at 6 PM Fri/Sat
- RDS: Pre-create 2 reader instances by 5 PM
- CloudFront: Invalidate cache at 5 PM for fresh assets
- Redis: Flush old session data, ensure memory available

**WebSocket Scaling:**
- API Gateway WebSocket API: Serverless, auto-scales to 1000s of connections
- Redis pub/sub for cross-container message routing
- Connection affinity via API Gateway `$connectionId`

---

## 5. Backup and Disaster Recovery

### 5.1 RPO/RTO Targets

| Component | RPO | RTO | Strategy |
|-----------|-----|-----|----------|
| PostgreSQL | 5 minutes | 15 minutes | Aurora continuous backup + cross-region replica |
| KJ App SQLite | 1 minute | 5 minutes | Continuous sync to S3, hot standby mode |
| File Storage | 0 (sync) | 2 hours | S3 cross-region replication |
| Configuration | 1 hour | 30 minutes | Infrastructure as Code + S3 backup |

### 5.2 Backup Architecture

**PostgreSQL (Aurora):**
```
┌──────────────────┐    ┌──────────────────┐
│ Primary Region   │    │ DR Region        │
│ (us-east-1)      │    │ (us-west-2)      │
│                  │    │                  │
│ Aurora Cluster ──┼────┼─► Cross-Region  │
│ ├─ Writer       │    │    Replica       │
│ ├─ Reader 1     │    │                  │
│ └─ Reader 2     │    │ Snapshot daily   │
│                  │    └──────────────────┘
│ Automated        │
│ snapshots: 35 days│
└──────────────────┘
```

**KJ App SQLite Sync Pipeline:**
```
KJ Desktop App
      │
      ├─ Every 30 seconds: Diff sync to S3
      ├─ Real-time: WebSocket status reports
      └─ On crash: Upload remaining WAL

S3 Bucket: kj-app-backups/
  ├─ venues/{id}/sqlite/changesets/
  ├─ venues/{id}/sqlite/full-backups/
  └─ venue-registry.json (last-seen timestamps)

Lambda Function: sqlite-sync-processor
  - Receives incremental changes
  - Validates against schema
  - Applies to PostgreSQL (idempotent)
  - Triggers conflict resolution if needed
```

### 5.3 Disaster Recovery Runbook

**Scenario 1: Primary RDS Failure:**
1. Automated: Failover to read replica (RTO: ~60s for Aurora)
2. Manual if needed: Promote cross-region replica (RTO: 15 min)
3. Update Route53 DNS to point to DR region
4. Notification via SNS to ops team

**Scenario 2: KJ App Crash During Event:**
1. User launches backup KJ app (hot standby mode)
2. App fetches latest SQLite from S3
3. WebSocket reconnects, syncs queue state
4. Manual intervention: Rebuild main KJ if needed

---

## 6. CI/CD Pipeline Architecture

### 6.1 Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     CI/CD Orchestration                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐        │
│   │   GitHub    │───▶│ CodePipeline│───▶│   Stage     │        │
│   │   Webhook   │    │ Trigger     │    │   Deploy    │        │
│   └─────────────┘    └─────────────┘    └─────────────┘        │
│                                                 │              │
│                                                 ▼              │
│   ┌─────────────────────────────────────────────────────┐     │
│   │              Parallel Build Matrix                   │     │
│   │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐  │     │
│   │  │   Backend    │ │ Flutter Web  │ │ Flutter App  │  │     │
│   │  │   (Docker)   │ │   Portal     │ │   (Android)  │  │     │
│   │  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘  │     │
│   │         │                │                │          │     │
│   │         ▼                ▼                ▼          │     │
│   │  ECR Push         S3 Upload           Play Store    │     │
│   │  ├─ staging       ├─ staging           └─ review    │     │
│   │  └─ prod          └─ prod                          │     │
│   └─────────────────────────────────────────────────────┘     │
│                            │                                   │
│                            ▼                                   │
│   ┌────────────────────────────────────────────────────────┐  │
│   │                Deployment Strategies                  │  │
│   │  ┌────────────────────────────────────────────────┐  │  │
│   │  │ Backend API: Blue/Green via ECS                 │  │  │
│   │  │ 1. Deploy new task definition to inactive env │  │  │
│   │  │ 2. Health checks pass → Route53 weight shift    │  │  │
│   │  │ 3. Rollback: instant DNS revert                 │  │  │
│   │  └────────────────────────────────────────────────┘  │  │
│   │  ┌────────────────────────────────────────────────┐  │  │
│   │  │ Web Portal: Rolling via S3 + CloudFront        │  │  │
│   │  │ 1. Build to versioned S3 prefix                 │  │  │
│   │  │ 2. CloudFront cache invalidation               │  │  │
│   │  │ 3. Instant rollback: alias S3 prefix            │  │  │
│   │  └────────────────────────────────────────────────┘  │  │
│   │  ┌────────────────────────────────────────────────┐  │  │
│   │  │ Mobile App: Phased rollout via Play Store      │  │  │
│   │  │ 1. Internal test track → 5% → 20% → 100%      │  │  │
│   │  │ 2. Automated rollback on crash rate spike    │  │  │
│   │  └────────────────────────────────────────────────┘  │  │
│   └────────────────────────────────────────────────────────┘  │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### 6.2 Environment Strategy

| Environment | Purpose | Deployment Trigger | Data |
|-------------|---------|-------------------|------|
| `dev` | Local development, hot-reload | Manual docker-compose | Local seed data |
| `staging` | Pre-prod validation, QA | Every merge to `main` | Anonymized prod snapshot |
| `prod` | Live customer traffic | Manual approval post-staging | Live production |

---

## 7. Cost Estimation

### 7.1 Assumptions

- Average venue: 50 concurrent users on weekends
- Peak venue: 200 concurrent users
- Data per venue: ~500 MB (songs, queue history, settings)
- CDN traffic: 100 GB/month baseline, 500 GB during peaks

### 7.2 Cost Breakdown by Scale

| Service | 10 Venues | 100 Venues | 1000 Venues | Notes |
|---------|-----------|------------|-------------|-------|
| **Compute (ECS Fargate)** | $45/mo | $450/mo | $4,500/mo | 2 base tasks, auto-scale |
| **RDS Aurora Serverless v2** | $80/mo | $300/mo | $2,500/mo | Writer + 1 reader |
| **ElastiCache Redis** | $35/mo | $100/mo | $400/mo | cache.t3.medium base |
| **S3 Storage** | $5/mo | $25/mo | $200/mo | 5GB → 500GB with growth |
| **S3 Data Transfer** | $10/mo | $50/mo | $400/mo | SQLite sync traffic |
| **CloudFront CDN** | $20/mo | $100/mo | $800/mo | Assets + venue skins |
| **API Gateway** | $15/mo | $100/mo | $900/mo | Per-request billing |
| **AWS Secrets Manager** | $5/mo | $20/mo | $100/mo | Per-secret pricing |
| **Monitoring (CloudWatch)** | $10/mo | $50/mo | $300/mo | Logs + metrics + alarms |
| **Reserve: Support, misc** | $25/mo | $50/mo | $200/mo | AWS Business Support |
| **TOTAL** | **~$250/mo** | **~$1,245/mo** | **~$10,200/mo** | |

### 7.3 Per-Venue Economics

| Scale | Monthly Cost | Per-Venue Cost | Model Fit |
|-------|--------------|----------------|-----------|
| 10 venues | $250 | $25 | Loss leader tier |
| 100 venues | $1,245 | $12.45 | Profitable at $30/venue |
| 500 venues | $5,500 | $11 | Sweet spot for $25/venue pricing |
| 1000 venues | $10,200 | $10.20 | Economies of scale kick in |

**Pricing Recommendation:**
- Basic tier: $29/venue/month (covers 100-venue cost + margin)
- Pro tier: $49/venue/month (dedicated reader, faster support)
- Enterprise: $99/venue/month (dedicated compute, 24/7 hotline)

### 7.4 Cost Optimization Strategies

1. **Reserved capacity:** 1-year RDS Reserved Instances save ~40%
2. **Spot instances:** Non-critical batch jobs (reporting, analytics)
3. **S3 Intelligent-Tiering:** Auto-archive old backups to glacier
4. **CloudFront caching:** Aggressive cache headers on static assets
5. **Connection pooling:** PgBouncer to minimize idle DB connections

---

## 8. Security Architecture

### 8.1 Defense in Depth

```
┌──────────────────────────────────────────────────────────┐
│ Layer 1: Network Security                                │
│ ├─ VPC with private subnets for all compute              │
│ ├─ Security groups: least-privilege, no 0.0.0.0/0       │
│ ├─ AWS WAF: SQLi, XSS, rate limiting rules               │
│ └─ AWS Shield Advanced: DDoS protection                │
├──────────────────────────────────────────────────────────┤
│ Layer 2: Application Security                            │
│ ├─ JWT tokens with short expiry (15 min)                 │
│ ├─ Refresh token rotation                                │
│ ├─ Input validation (Pydantic schemas)                   │
│ ├─ SQL injection prevention (SQLAlchemy + RLS)           │
│ └─ CORS whitelist per venue domain                       │
├──────────────────────────────────────────────────────────┤
│ Layer 3: Data Security                                   │
│ ├─ RDS encryption at rest (AES-256)                      │
│ ├─ TLS 1.3 in transit                                    │
│ ├─ S3 bucket policies (private by default)             │
│ ├─ Secrets Manager for credentials (rotation)          │
│ └─ Field-level encryption for PII (SSN, payment)       │
├──────────────────────────────────────────────────────────┤
│ Layer 4: Operational Security                            │
│ ├─ CloudTrail logging (API calls)                        │
│ ├─ GuardDuty threat detection                            │
│ ├- Config rules (compliance scanning)                    │
│ └─ IAM roles (no long-term access keys)                  │
└──────────────────────────────────────────────────────────┘
```

### 8.2 Secrets Management

```yaml
AWS Secrets Manager:
  rotation_policy: automatic_30_days
  
  secrets:
    scales/database/master:
      - username: master_user
      - password: <auto-generated>
      
    scales/venues/{venue_id}/api:
      - venue_api_key: <uuid>
      
    scales/jwt/signing:
      - private_key: <ed25519 private>
      - public_key: <ed25519 public>
      
    scales/firebase/admin:
      - service_account_json: <base64>
```

---

## 9. Monitoring and Observability

### 9.1 Metrics Stack

| Layer | Tool | Key Metrics |
|-------|------|-------------|
| Infrastructure | CloudWatch | CPU, memory, disk, network |
| Application | CloudWatch + X-Ray | Request latency, error rate, traces |
| Database | RDS Enhanced Monitoring | Query duration, connection count, locks |
| Business | Custom CloudWatch | Active sessions, queue depth, sync lag |
| Alerting | CloudWatch Alarms → SNS → OpsGenie | P1 (phone), P2 (email), P3 (Slack) |

### 9.2 Key SLIs/SLOs

| SLI | SLO | Measurement |
|-----|-----|-------------|
| API response time | p99 < 200ms | CloudWatch Lambda Insights |
| WebSocket connection success | > 99.9% | API Gateway metrics |
| SQLite sync lag | < 30 seconds | Custom heartbeat metric |
| Database availability | > 99.95% | RDS uptime |
| Mobile app crash-free rate | > 99.5% | Firebase Crashlytics |

---

## 10. Migration Path

### 10.1 Phase 1: MVP (0-10 venues)
- Single AZ RDS (cost savings)
- 2 ECS tasks minimum
- S3 standard storage
- No CDN (direct S3)

### 10.2 Phase 2: Growth (10-100 venues)
- Multi-AZ Aurora
- CloudFront + WAF
- Redis for session caching
- Cross-region backup (async)

### 10.3 Phase 3: Scale (100-1000 venues)
- Read replicas across AZs
- Redis Cluster mode
- Dedicated VIP tenant infrastructure
- Automated cost optimization

---

## 11. Architecture Decision Records

### ADR-001: AWS over GCP/Azure
**Status:** Accepted
**Context:** GCP has better Kubernetes (GKE), Azure has better enterprise integration. AWS wins on managed PostgreSQL reliability and Flutter CD ecosystem.

### ADR-002: Aurora Serverless v2 over Provisioned
**Status:** Accepted
**Context:** Venues have spikey usage. Serverless handles idle→burst automatically without over-provisioning. 30% cost premium worth it for operational simplicity.

### ADR-003: Row-Level Security over Separate DBs
**Status:** Accepted
**Context:** An earlier draft explored schema-per-tenant. That was evaluated and set aside in favor of RLS with venue_id. RLS keeps costs manageable at 1000 tenants (under $30K/year) while maintaining data isolation per venue. See ADR-004 for the full ratification.

---

*Generated: 2026-05-19*
*Next review: Upon reaching 50 venues (estimated Q3 2026)*
