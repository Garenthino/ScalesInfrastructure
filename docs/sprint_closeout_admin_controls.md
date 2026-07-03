# Sprint Closeout: Admin Controls + Stripe Phase 2 (2026-07-03)

## Completed admin-controls sprint

| Task | Assignee | Status | Evidence |
|------|----------|--------|----------|
| Admin dashboard analytics cards | backend | done | commit c028a34 |
| Admin audit log for venue actions | backend | done | commit 20260629_170100 |
| Admin notes per venue | backend | done | commit e04135815a62 |
| Admin venue detail drawer | frontend | done | commit 15f68ae |
| QA: admin detail drawer + dashboard | qa | done | docs/qa/admin_detail_dashboard_qa.json |
| QA: admin audit log + notes | qa | done | docs/qa/admin_audit_notes_qa.json |
| QA: admin venue purge + anonymization | qa | done | docs/qa/admin_venue_purge_qa.json |
| FIX: purge FK/audit-log bug | backend | done | commit 139fb59 |

## What shipped
- `/admin` portal: venue list, detail drawer, status editing, impersonation, soft-delete, restore, purge.
- Admin audit log records status changes, deletes, restores, impersonations, provisions, and purges.
- Venue purge: hard-delete when no billing history; billing-aware anonymization when payments/orders exist (financial records retained, PII scrubbed).
- VPS `.git/objects` + `docs/qa` ownership fixed so automated deploys work again.
- `alembic_version.version_num` widened to `varchar(255)` to support longer migration IDs.

## Stripe Phase 2 status
- Backend checkout/subscription lifecycle code committed: `b030ac1`.
- Webhook route `/api/v1/stripe/webhook` deployed and responding.
- **Blocked on real Stripe credentials** (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID_BASIC`, `STRIPE_PRICE_ID_ENTERPRISE`).
- Frontend billing page and admin billing dashboard cards are queued and waiting for backend/devops completion.

## Follow-up tasks on the board
- t_a52217ef: songs endpoint 500 (missing category/year columns in production DB)
- t_aca91cc5: fix rate limiting on authenticated read endpoints
- t_79be62af: deploy backup and rollback scripts to production VPS
- t_1b523f33: verify and deploy notification settings endpoints + per-type push filtering
- t_2de30e2c: Stripe Phase 2 frontend venue billing page
- t_989a4018: Stripe Phase 2 admin billing dashboard
- t_845efe8d: Stripe Phase 2 QA end-to-end subscription flow

## Recommended next sprint priorities
1. Provide Stripe secrets so t_992b995b / t_b8dde5b2 can verify webhook signature validation and complete.
2. Ship t_a52217ef and t_aca91cc5 to close the MS-10C regression items.
3. Begin frontend Stripe billing page once backend checkout endpoint is verified.
