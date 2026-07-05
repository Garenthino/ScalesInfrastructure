# Mobile Identity Sprint Plan

## Goal
Replace the current per-venue-only singer model with a global mobile account so a new user can sign up once, join any venue later, and have a consistent identity. Give KJs a way to link a non-mobile singer from the KJ device program to a mobile-account singer so history (queue, payments, favorites, achievements) is preserved.

## Created Kanban Tasks

| ID | Task | Lane | Depends on |
|---|---|---|---|
| t_71b6e954 | Add accounts table and migrate singers to venue membership model | backend | — |
| t_77d8c3e7 | Global account registration endpoint | backend | t_71b6e954 |
| t_5600569d | Global account login and me endpoints | backend | t_71b6e954 |
| t_2ad55995 | Join venue with global account | backend | t_77d8c3e7, t_5600569d |
| t_9a14a6c1 | KJ-to-mobile singer linking and history merge | backend | t_71b6e954 |
| t_b8a0b192 | Real-time singer updates to KJ devices | backend | t_2ad55995, t_9a14a6c1 |
| t_0c418a6e | Flutter global auth repository and storage | frontend | t_77d8c3e7, t_5600569d |
| t_9587421a | Mobile global-account onboarding screens | frontend | t_0c418a6e |
| t_ce0dc895 | Mobile profile edit and multi-venue switcher | frontend | t_0c418a6e |
| t_0289e82c | KJ portal singer linking UI | frontend | t_9a14a6c1 |
| t_1311f685 | QA global identity, venue join, KJ linking | qa | t_2ad55995, t_9a14a6c1, t_b8a0b192 |
| t_3e4bece0 | Deploy mobile identity backend to production | devops | t_71b6e954, t_1311f685 |

## Resume State
- Plan created: 2026-07-04.
- Schema migration committed: `013719e` — accounts table, account_id on singers, unique(account_id, venue_id), linked_singer_id, singer_link_merge_logs, backfill for existing singers.
- Global account endpoints committed: `22bc07e` — POST /accounts/register, /accounts/login, /accounts/me, /accounts/refresh. QA passed via ASGI client.
- Venue join committed: `20342e5` — POST /venues/{venue_id}/join creates per-venue Singer from account token; GET /venues/{venue_id}/singers/me added. QA passed end-to-end.
- Next task to start: **t_9a14a6c1** (KJ-to-mobile singer linking and history merge).
- Safe checkpoint: after each task finishes, commit and run `hermes kanban complete <id>`.

## Quota-Resilience Notes
- Before each major implementation push, update this file with the current in-progress task and any uncommitted changes.
- If the API quota maxes out and Kanban workers error, run the skill `kanban-quota-resilience` to cleanly pause and resume.

## Resume State Log
1. 2026-07-04: t_71b6e954 schema done and pushed.
2. 2026-07-04: t_77d8c3e7 and t_5600569d global account endpoints done and pushed.
3. 2026-07-04: t_2ad55995 venue join done and pushed.
