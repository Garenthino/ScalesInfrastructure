# Scales: Loyalty & Gamification Engine

A configurable, multi-tenant loyalty system designed for venue-based entertainment experiences.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           API Layer                                     │
├─────────────────────────────────────────────────────────────────────────┤
│  /loyalty/points/earn        /loyalty/points/redeem                     │
│  /loyalty/tiers              /loyalty/quests                            │
│  /loyalty/analytics          /loyalty/fraud                             │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
┌─────────────────────────────────────────────────────────────────────────┐
│                         Service Layer                                   │
├────────────┬────────────┬────────────┬────────────┬───────────────────────┤
│   Rules    │   Points   │   Quests   │   Tiers    │      Fraud            │
│   Engine   │  Service   │   Engine   │  Service   │    Detection          │
└────────────┴────────────┴────────────┴────────────┴───────────────────────┘
                                    │
┌─────────────────────────────────────────────────────────────────────────┐
│                        Data Layer                                       │
├────────────┬────────────┬────────────┬────────────┬─────────────────────┤
│   Points   │   Tiers    │   Quests   │  Sessions  │    Analytics         │
└────────────┴────────────┴────────────┴────────────┴─────────────────────┘
```

## Core Entities

### 1. Points System
- **Earn Rules**: Configurable triggers and rates per venue
- **Point Balance**: Ledger-style accounting with immutable history
- **Expiry Rules**: Optional TTV (time-to-void) per venue configuration
- **Redemption**: Catalog of rewards with dynamic pricing

### 2. Tier System
- **Tier Levels**: Bronze → Silver → Gold → Platinum (venue-defined names)
- **Perks**: Discounts, priority access, exclusive content
- **Qualification**: Points earned OR lifetime spend threshold
- **Retention**: Grace periods prevent immediate downgrade

### 3. Quest Engine
- **Check-in Quests**: Visit streaks, location diversity
- **Exploration Quests**: Genre discovery, artist variety
- **Social Quests**: Referrals, group check-ins, share actions
- **Seasonal Quests**: Birthday bonuses, holiday events

### 4. Anti-Fraud
- **Rate Limiting**: Per-user, per-IP, per-device limits
- **Duplicate Detection**: Fingerprinting for replay attacks
- **Velocity Checks**: Unusual earning patterns trigger review
- **Device Reputation**: Shared device detection

## API Design Principles

1. **Venue-scoped**: Every call includes `venue_id` for multi-tenancy
2. **Async-first**: Point calculations, fraud scoring happen in background
3. **Idempotent**: All mutation endpoints accept idempotency keys
4. **Observable**: Structured logs, metrics at all boundaries

## Database Design

See `schema.sql` for full DDL. Key tables:
- `loyalty_config` - Venue-level settings and rules
- `point_balance` - Current balances with row-level locking
- `point_transactions` - Immutable audit log
- `tiers` - Tier definitions and thresholds
- `quests` - Active quest configurations
- `quest_progress` - Per-user progress tracking
- `fraud_events` - Flagged activities for review
