# MS-10C QA Report — End-to-End Production Regression & Security Test

**Date:** 2026-06-01
**Task:** t_2d4fa040
**Status:** FAIL — v1.0 GO/NO-GO = NO-GO (CRITICAL/HIGH issues found)

---

## Phase 1: Full E2E (register → check-in → request → tip → check-out)

| # | Criterion | Status | Notes |
|---|-----------|--------|-------|
| 1.1 | POST /auth/register | PASS | venue_id required; 201 |
| 1.2 | POST /auth/login | PASS | 200, tokens returned |
| 1.3 | GET /auth/me | PASS | Profile returned with venue_id |
| 1.4 | POST /checkin | PASS | 200 with body (table_number) |
| 1.5 | GET /songs list | **FAIL CRITICAL** | 500 Internal Server Error |
| 1.6 | GET /songs/search | **FAIL CRITICAL** | 500 Internal Server Error |
| 1.7 | POST /queue request | **FAIL** | No songs available (blocked by 500) |
| 1.8 | POST /tips | **FAIL** | 404 — endpoint not at /tips but /payments/tip |
| 1.9 | GET /singers/me/queue | **FAIL** | 404 — endpoint not found |
| 1.10 | POST /checkout | PASS | 200, check-in session ended |
| 1.11 | GET /checked-in (singer→403) | PASS | Correctly 403 for singer role |

### Root Cause — Songs 500
The `app/routers/songs.py` `list_songs()` queries `Song.category` and `Song.year` filters. The `app/models/__init__.py` `Song` model **declares** these columns (`category = Column(Text)`, `year = Column(Integer)`), but the **production DB** `songs` table lacks them:

```
db=# \d songs
Columns: id, venue_id, catalog_id, title, artist, album, genre, language, duration_ms,
         lyrics_url, cover_art_url, is_available, is_active, meta_json,
         created_at, updated_at, deleted_at
```

**Missing columns:** `category`, `year`

SQLAlchemy generates `WHERE songs.category = $1` → PostgreSQL: `column songs.category does not exist` → 500.

Additionally, zero songs exist in `songs` table for the test venue, so queue requests would fail downstream even if the 500 were fixed.

### Root Cause — Tips 404
The correct endpoint is `POST /venues/{venue_id}/payments/tip`, not `/venues/{venue_id}/tips`. The task spec expected `/tips`.

### Root Cause — /singers/me/queue 404
The `singers.py` router is mounted at `/venues/{venue_id}/singers`. The endpoints `/me/queue`, `/me/queue/history`, `/me/stats`, `/me/achievements` DO exist in the source code (`app/routers/singers.py` lines 489, 533, 740, 1121), but in production they return 404. This suggests either:
(a) The deployed image does not contain the latest code with these endpoints, or
(b) The router was not included in `api_router` at build time.

---

## Phase 2: Rate Limit

| # | Criterion | Status | Notes |
|---|-----------|--------|-------|
| 2.1 | Exceed threshold → 429 | **FAIL HIGH** | 15 rapid /auth/me requests all returned 200; no rate limiting observed from client vantage. Backend may have rate limits only on specific endpoints (register/login) but not on authenticated reads. |

---

## Phase 3: SQL Injection

| # | Criterion | Status | Notes |
|---|-----------|--------|-------|
| 3.1 | /auth/login email | PASS | 422 validation error, no data leak |
| 3.2 | /auth/register stage_name | PASS | No injection, 422 on some payloads |
| 3.3 | /songs/search q | **FAIL HIGH** | 500 when SQLi payload sent. The 500 is actually from the missing `category` column bug, not from injection. But the 500 status (rather than safe rejection) marks it as a server error — the endpoint crashes on ANY query with the `q` parameter because it hits the `category`/`year` query path. |
| 3.4 | /singers/checkin table_number | PASS | Payload accepted but no injection effect (200) |
| 3.5 | Overall | **PARTIAL** | 3/4 probes safe; 1 probe returns 500 (not a SQLi vuln per se but a crash) |

---

## Phase 4: XSS

| # | Criterion | Status | Notes |
|---|-----------|--------|-------|
| 4.1 | Script tag in register stage_name | PASS | Response does not reflect raw script tag in /auth/me |

---

## Phase 5: Load Test (20 concurrent logins)

| # | Criterion | Status | Notes |
|---|-----------|--------|-------|
| 5.1 | 20 concurrent logins | PASS | 20/20 success in 8.0s, no 429 or 503 |

---

## Phase 6: Backup Recovery

| # | Criterion | Status | Notes |
|---|-----------|--------|-------|
| 6.1 | Backup scripts exist | **FAIL MEDIUM** | `/home/scales/ScalesInfrastructure/scripts/backup_db.sh` and `rollback.sh` not found on production VPS. These were added to the repo in commit `f590257` but may not have been deployed to the server. |

---

## Phase 7: SSL/TLS

| # | Criterion | Status | Notes |
|---|-----------|--------|-------|
| 7.1 | HSTS header | PASS | `strict-transport-security: max-age=63072000; includeSubDomains` present on API responses |
| 7.2 | X-Frame-Options | PASS | `DENY` present |
| 7.3 | SSL cert valid | PASS | Cert expires Aug 25 2026 GMT; chain valid |
| 7.4 | PFS (cipher check) | PASS | Modern TLS (verified via openssl s_client) |

---

## Phase 8: Monitoring

| # | Criterion | Status | Notes |
|---|-----------|--------|-------|
| 8.1 | Sentry SDK import | PASS | `app/main.py` contains `sentry-sdk[fastapi]` integration |
| 8.2 | Sentry event reception | **NOT TESTED** | Cannot trigger production error safely. SDK is wired but reception not verified. |

---

## GO/NO-GO Verdict: NO-GO

**Blocking issues (CRITICAL/HIGH):**
1. **Songs endpoint 500** — `category` and `year` columns declared in model but missing in production DB. This crashes every song list/search request.
2. **Rate limit not enforced on authenticated reads** — 15 rapid requests all 200. At minimum, `/auth/me` should be rate-limited to prevent enumeration.
3. **Backup scripts not deployed** — Repo has them, but they are absent from `/home/scales/ScalesInfrastructure/scripts/` on the production VPS.

**Non-blocking failures:**
- Tips endpoint path mismatch (moved to `/payments/tip`; docs should reflect this)
- `/singers/me/*` endpoints 404 in production (deployed code mismatch)

---

## Fix Tasks Created

| Fix Task | Component | Root Cause |
|----------|-----------|------------|
| t_FX_SONGS_DB | Database | Add missing `category` and `year` columns to `songs` table or remove from model query |
| t_FX_RATE_LIMIT | Backend | Rate limit not active on authenticated read endpoints |
| t_FX_DEPLOY_SCRIPTS | DevOps | Backup/rollback scripts not deployed to VPS |

