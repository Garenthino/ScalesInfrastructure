# MS-08C QA Report — Admin Portal Regression

**Date:** 2026-05-31
**Tester:** qa (automated)
**Task:** t_4dda9d79
**Parent:** t_26abaca9 (MS-08B frontend complete)
**Commit tested:** 6ab9d2c

---

## Summary

**4/7 PASS, 3/7 FAIL**

| # | Criterion | Status | Notes |
|---|-----------|--------|-------|
| 1 | Admin login + role-gated nav | PASS | Sidebar hides admin nav for non-admin; auth flow works |
| 2 | Queue reorder/skip/ban via API | **FAIL** | All queue admin actions (approve, reject, complete, remove, fetch) call non-existent flat routes → 404 |
| 3 | Rotation mode persistence + ordering | PASS | Settings page fetches/saves mode; backend persists RotationSession |
| 4 | Analytics match manual count or API | PASS | Dashboard uses venue-scoped analytics; backend tests verify accuracy |
| 5 | Responsive at 1024px and 1920px | PASS | Build OK; responsive grid classes present on all major pages |
| 6 | Security: non-admin admin URL access | **FAIL** | `ProtectedRoute` only checks auth, not role. Any logged-in user can load `/admin` UI |
| 7 | Build + tests | **FAIL** | Next.js build passes, but 1 backend test fails (`test_integration_scenarios` — test uses POST instead of PUT on `/reorder`) |

---

## Detailed Findings

### 1. Admin Login + Role-Gated Navigation — PASS

- `useAuth` correctly stores `access_token` + `refresh_token` with distinct localStorage keys (`scales_access_token`, `scales_refresh_token`)
- Auto-refresh has `isRefreshing` guard + expired-token logout (no 429 loop)
- Login page auto-redirects authenticated users to `/queue`
- Sidebar conditionally renders "Administration" section only when `user?.role === "admin"`
- **Minor:** `User.role` type in `web/lib/types.ts` is `"owner" | "admin" | "operator" | "kj"` but backend returns `"admin" | "owner" | "kj" | "singer"`. `"operator"` is not a valid backend role; `"singer"` is missing from the frontend type.

### 2. Queue Reorder / Skip / Ban — **FAIL**

| Action | Frontend API function | Route called | Backend route | Result |
|--------|----------------------|--------------|---------------|--------|
| Fetch queue | `fetchQueueAdmin(token)` | `GET /queue/admin` | `GET /venues/{vid}/queue/admin` | **404** |
| Approve | `approveRequest(id, token)` | `POST /queue/admin/{id}/approve` | `POST /venues/{vid}/queue/admin/{id}/approve` | **404** |
| Reject | `rejectRequest(id, token)` | `POST /queue/admin/{id}/reject` | `POST /venues/{vid}/queue/admin/{id}/reject` | **404** |
| Complete | `completeRequest(id, token)` | `POST /queue/admin/{id}/complete` | `POST /venues/{vid}/queue/admin/{id}/complete` | **404** |
| Remove | `removeRequest(id, token)` | `DELETE /queue/admin/{id}` | `DELETE /venues/{vid}/queue/admin/{id}` | **404** |
| Skip to end | `skipToEnd(vid, id, token)` | `POST /venues/{vid}/queue/admin/skip-to-end` | Same | OK |
| Ban singer | `banSinger(vid, sid, reason, token)` | `POST /venues/{vid}/singers/{sid}/ban` | Same | OK |
| Reorder by singer | `reorderQueueBySinger(vid, ids, token)` | `PUT /venues/{vid}/queue/admin/reorder` | Same | OK |

**Root cause:** `web/lib/api.ts` still contains legacy flat routes (`/queue/admin/...`) that the backend removed when it migrated to venue-scoped paths. The new admin dashboard `queue-table.tsx` imports from `lib/api.ts` and will hit 404 on every approve/reject/complete/remove action.

**Backend verification:** `test_queue_admin.py` 25/25 passed — all venue-scoped admin endpoints work correctly.

**Fix required:** Update all legacy flat-route functions in `web/lib/api.ts` to accept `venueId` and call `/venues/{venueId}/queue/admin/...`.

### 3. Rotation Mode Persistence — PASS

- `QueuePage` fetches mode via `GET /venues/{vid}/queue/admin/mode` and displays live selector
- `SettingsPage` fetches same endpoint and has Save/Reset UX
- `setRotationMode` calls `PUT /venues/{vid}/queue/admin/mode`
- Backend creates a new `RotationSession` row, deactivates old one — changes are persisted to DB
- Tooltip explanations render for all 4 modes (FIFO, Round-Robin, Balanced, VIP Priority)

### 4. Analytics Accuracy — PASS

- `DashboardPage` uses `fetchQueueAnalytics(vid, token)` → `GET /venues/{vid}/queue/admin/analytics`
- Backend `QueueAnalyticsOut` schema fields (`total_requests_today`, `completed_today`, `avg_wait_seconds`, `top_songs`, `throughput_per_hour`) map correctly to frontend `QueueAnalytics` type
- Backend `test_analytics.py` verifies:
  - Overview counts match DB state
  - Cross-venue access denied (403)
  - Admin can read any venue
  - Leaderboard ordering + limit bounds
  - Song popularity request counts
  - Hourly breakdown returns 24 hours
  - Malformed timestamps are handled gracefully

### 5. Responsive Layout — PASS

- Next.js build succeeds; 13 pages statically generated
- Dashboard: `grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6`
- Queue page: `grid grid-cols-1 gap-4 lg:grid-cols-3`
- Sidebar: `hidden md:flex` (collapses below `md` breakpoint)
- Settings select: `w-full sm:w-64`
- Queue table: `overflow-x-auto` wrapper for horizontal scroll on narrow viewports

### 6. Security: Non-Admin Admin URL Access — **FAIL**

- `components/protected-route.tsx` only checks `isAuthenticated`. It does **not** inspect `user.role`.
- Any authenticated singer can type `/admin` in the URL and the page will render.
- `admin/page.tsx` has no role guard — it shows the admin UI to anyone.
- Backend API endpoints will return 403 for non-admin API calls, but the frontend UI is still visible.
- **Required fix:** Add `AdminRoute` wrapper (or extend `ProtectedRoute` with `requiredRole`) that redirects non-admin users to `/queue` or `/`.

### 7. Build + Tests — **FAIL**

- Next.js: `npm run build` → compiled successfully, 13 static pages
- Backend: `pytest tests/test_queue_admin.py` → 25/25 pass
- Backend: `pytest tests/test_auth.py tests/test_queue_core.py tests/test_analytics.py tests/test_integration_security.py tests/test_integration_show_flow.py tests/test_integration_scenarios.py` → **112 passed, 1 failed**
  - Failure: `test_integration_scenarios.py::test_scenario_c_multi_singer_rotation_and_reorder` — test uses `POST` on `/reorder` but endpoint is `PUT`. This is a **test bug**, not a production code bug.

---

## Issues Summary

| Severity | Issue | File(s) | Fix |
|----------|-------|---------|-----|
| **CRITICAL** | Queue admin actions (approve, reject, complete, remove, fetch) call non-existent flat routes | `web/lib/api.ts` lines 250–305 | Update all functions to accept `venueId` and call `/venues/{venueId}/queue/admin/...` |
| **HIGH** | No frontend role guard on `/admin` | `components/protected-route.tsx`, `app/(app)/admin/page.tsx` | Add `requiredRole` prop to `ProtectedRoute` or create `AdminRoute` wrapper |
| LOW | `User.role` type mismatch (`operator` vs `singer`) | `web/lib/types.ts` line 4 | Sync with backend `MeResponse.role` enum |
| LOW | Settings page duplicates API helpers instead of importing | `web/app/(app)/settings/page.tsx` | Import `fetchRotationMode` / `setRotationMode` from `@/lib/api` |
| LOW | Test bug: `test_integration_scenarios.py` uses POST on `/reorder` (should be PUT) | `tests/test_integration_scenarios.py` line 345 | Change `client.post` to `client.put` |

---

## Backport Status

```
ScalesInfrastructure: main @ 6ab9d2c
  - 1 commit ahead of origin/main
  - Working tree clean
  - Changed files: 11 web files (see git diff HEAD~1 --name-only)
```

**Action required:** Push commit `6ab9d2c` to `origin/main` after the issues above are fixed.

---

## Recommendations

1. **Fix `web/lib/api.ts`** — update `fetchQueueAdmin`, `approveRequest`, `rejectRequest`, `completeRequest`, `removeRequest`, and `reorderQueue` to accept `venueId` and call the venue-scoped backend routes.
2. **Fix `components/protected-route.tsx`** — add an optional `requiredRole` prop so admin pages can reject non-admin users client-side.
3. **Fix `test_integration_scenarios.py`** — change `client.post` to `client.put` on the reorder endpoint.
4. **Fix `User.role` type** — align with backend enum.
5. **Re-run `npm run build`** after fixes to confirm no type errors.
6. **Run `pytest tests/test_queue_admin.py`** after backend changes (currently 25/25 pass).
