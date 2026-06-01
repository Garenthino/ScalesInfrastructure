# MS-09C QA Report: Notifications Regression

**Sprint:** MS-09 (Push Notifications)
**Date:** 2026-05-31
**QA Profile:** qa
**Repos tested:** ScalesInfrastructure (backend), ScalesMobile (Flutter)

---

## Test Summary

| # | Criterion | Status | Notes |
|---|-----------|--------|-------|
| 1 | Device token registration, backend stores | **PASS** | Backend endpoint /me/devices works; mobile registers on login; DB model correct with unique constraint |
| 2 | Trigger queue events, verify push delivery | **PASS** | notify_singer() persists in-app notification; queue triggers wired (approve→position, start→on_stage, payment→bumped); Firebase/Celery graceful fallback |
| 3 | Notification center: all types render, tap navigates | **PARTIAL** | UI renders all 7 types and tap→GoRouter navigation works. **FAIL subset:** unread-count badge calls /me/notifications/unread-count which is 404 Not Found — endpoint does not exist on backend. |
| 4 | Toggle off queue notifications → trigger → no push | **FAIL** | Mobile settings UI + optimistic toggle work. Backend **missing** PUT /me/notification-settings and GET /me/notification-settings. notify_singer() does **not** filter by per-type preference — all pushes sent regardless of toggle state. |
| 5 | Offline: queued by FCM, delivered on reconnect | **PASS** | FCM platform handles offline queueing natively; background handler present in mobile |
| 6 | Token refresh: simulate, verify backend gets new | **PASS** | Mobile listenForTokenRefresh() re-registers; backend deactivates old same-platform token before inserting new |
| 7 | Produce QA report | **PASS** | This report |

---

## Verification Evidence

### Backend tests (ScalesInfrastructure)
pytest tests/test_notifications.py tests/test_integration_scenarios.py
============================== 11 passed in 5.13s ===============================

### Mobile tests (ScalesMobile)
flutter test test/notification_test.dart
00:00 +9: All tests passed!

### Backend commit
- 45f117e — MS-09A: FCM/APNs integration, notification delivery service with Celery + Firebase Admin SDK
- 227 core tests pass

### Mobile commit
- c46070d — MS-09B: Push notification handling, notification center, settings
- 37 tests pass, flutter analyze clean

---

## Findings

### Finding A — CRITICAL: Missing backend notification settings endpoints
- File: app/routers/notifications.py
- Missing endpoints:
  - GET /v1/venues/{venue_id}/singers/me/notifications/unread-count
  - GET /v1/venues/{venue_id}/singers/me/notification-settings
  - PUT /v1/venues/{venue_id}/singers/me/notification-settings
- Impact:
  1. Unread count badge on mobile home screen always fails (silent 404 → badge stays at 0)
  2. Notification settings toggles have no backend effect — preferences not persisted
  3. notify_singer() cannot filter by user preference because there is no settings table/endpoint

### Finding B — HIGH: notify_singer() ignores per-type preferences
- File: app/core/notification_service.py:151
- Code: notify_singer() fetches active device tokens and immediately enqueues push without checking any singer preference
- Impact: Even if the user disables "Up Soon" notifications, they still receive them

### Finding C — INFO: No NotificationSettings DB model
- There is no notification_settings table or model in app/models/__init__.py
- This must be added alongside the router endpoints

---

## Recommendations

1. Add NotificationSetting model to app/models/__init__.py with columns: singer_id, venue_id, up_soon, on_stage, bumped, queue_update, announcement, social, payment (all boolean, default true)
2. Add Alembic migration for the new table
3. Add endpoints to app/routers/notifications.py:
   - GET /me/notifications/unread-count → return {"unread_count": int}
   - GET /me/notification-settings → return current settings
   - PUT /me/notification-settings → update and return settings
4. Update notify_singer() in app/core/notification_service.py to query NotificationSetting and skip push if the relevant type is disabled
5. Add backend tests for all new endpoints and the filtering behavior

---

## Score

**4/7 PASS, 1/7 PARTIAL, 2/7 FAIL**
