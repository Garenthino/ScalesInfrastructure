"""MS-10A: Rate limiting, audit logging, query optimization, request tracing."""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import AuditLog, Venue, Singer, Song, QueueRequest, CheckInSession
from app.core.security import hash_password


# ---------------------------------------------------------------------------
# Rate limiting under load
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_rate_limit_unauthed(client, monkeypatch):
    """Unauthed client is blocked after exceeding per-IP limit."""
    monkeypatch.setattr(settings, "RATE_LIMIT_REQUESTS", 5)
    monkeypatch.setattr(settings, "RATE_LIMIT_UNAUTHED_REQUESTS", 2)
    monkeypatch.setattr(settings, "RATE_LIMIT_WINDOW", 60)

    from app.middleware import security as sec_mod
    sec_mod._buckets.clear()

    for _ in range(2):
        r = await client.get("/health")
        assert r.status_code == 200

    r = await client.get("/health")
    assert r.status_code == 429
    assert "Retry-After" in r.headers


@pytest.mark.anyio
async def test_rate_limit_authed(client, jwt_encode, monkeypatch):
    """Authed user gets their own bucket separate from IP."""
    monkeypatch.setattr(settings, "RATE_LIMIT_REQUESTS", 5)
    monkeypatch.setattr(settings, "RATE_LIMIT_UNAUTHED_REQUESTS", 2)
    monkeypatch.setattr(settings, "RATE_LIMIT_WINDOW", 60)

    from app.middleware import security as sec_mod
    sec_mod._buckets.clear()

    token = jwt_encode(str(uuid.uuid4()), role="singer")
    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(5):
        # /v1/auth/me returns 401 for synthetic token, but rate-limit enforced first
        r = await client.get("/v1/auth/me", headers=headers)
        assert r.status_code in (200, 401)

    r = await client.get("/v1/auth/me", headers=headers)
    assert r.status_code == 429
    assert "Retry-After" in r.headers


@pytest.mark.anyio
async def test_rate_limit_authed_singers_me(client, jwt_encode, monkeypatch):
    """Authed /venues/{id}/singers/me/* endpoints are rate limited."""
    monkeypatch.setattr(settings, "RATE_LIMIT_REQUESTS", 5)
    monkeypatch.setattr(settings, "RATE_LIMIT_UNAUTHED_REQUESTS", 2)
    monkeypatch.setattr(settings, "RATE_LIMIT_WINDOW", 60)

    from app.middleware import security as sec_mod
    sec_mod._buckets.clear()

    token = jwt_encode(str(uuid.uuid4()), role="singer")
    headers = {"Authorization": f"Bearer {token}"}
    venue_id = str(uuid.uuid4())
    for _ in range(5):
        r = await client.get(f"/v1/venues/{venue_id}/singers/me/stats", headers=headers)
        assert r.status_code in (200, 401, 403)

    r = await client.get(f"/v1/venues/{venue_id}/singers/me/stats", headers=headers)
    assert r.status_code == 429
    assert "Retry-After" in r.headers


@pytest.mark.anyio
async def test_rate_limit_kj_sync_unaffected(client, monkeypatch):
    """KJ M2M sync traffic using x-api-key is not rate limited."""
    monkeypatch.setattr(settings, "RATE_LIMIT_REQUESTS", 2)
    monkeypatch.setattr(settings, "RATE_LIMIT_UNAUTHED_REQUESTS", 2)
    monkeypatch.setattr(settings, "RATE_LIMIT_WINDOW", 60)

    from app.middleware import security as sec_mod
    sec_mod._buckets.clear()

    headers = {"x-api-key": "fake-kj-api-key"}
    for _ in range(5):
        r = await client.get("/v1/kj/sync/queue/pull", headers=headers)
        # Should be allowed through; route returns 401 because key is fake
        assert r.status_code != 429

    r = await client.get("/v1/kj/sync/queue/pull", headers=headers)
    assert r.status_code != 429


@pytest.mark.anyio
async def test_rate_limit_resets_after_window(client, monkeypatch):
    """Rate limit bucket resets when window passes."""
    monkeypatch.setattr(settings, "RATE_LIMIT_REQUESTS", 5)
    monkeypatch.setattr(settings, "RATE_LIMIT_UNAUTHED_REQUESTS", 2)
    monkeypatch.setattr(settings, "RATE_LIMIT_WINDOW", 0)

    from app.middleware import security as sec_mod
    sec_mod._buckets.clear()

    for i in range(10):  # nosec: small loop
        r = await client.get("/health")
        assert r.status_code == 200, f"Request {i} failed"


# ---------------------------------------------------------------------------
# Request ID tracing
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_request_id_header_present(client):
    r = await client.get("/health")
    assert r.status_code == 200
    rid = r.headers.get("X-Request-ID")
    assert rid is not None
    assert len(rid) == 36


@pytest.mark.anyio
async def test_request_id_passthrough(client):
    rid = str(uuid.uuid4())
    r = await client.get("/health", headers={"X-Request-ID": rid})
    assert r.headers.get("X-Request-ID") == rid


# ---------------------------------------------------------------------------
# Connection pool tuning validation
# ---------------------------------------------------------------------------

def test_connection_pool_settings():
    assert settings.DATABASE_POOL_SIZE == 10
    assert settings.DATABASE_MAX_OVERFLOW == 20
    assert settings.DATABASE_POOL_RECYCLE == 3600


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_health_endpoint_structured(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "degraded")
    assert "version" in body
    assert "timestamp" in body
    assert "checks" in body
    assert "database" in body["checks"]


# ---------------------------------------------------------------------------
# Audit logging on protected endpoints (mocked to avoid FK races)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_audit_log_written_after_authenticated_endpoint(
    client, jwt_encode, db: AsyncSession
):
    """Any authenticated request should trigger an audit log entry."""
    vid = str(uuid.uuid4())
    venue = Venue(id=vid, name="Audit Venue", slug=f"audit-{vid[:8]}")
    db.add(venue)
    await db.commit()

    singer = Singer(
        id=str(uuid.uuid4()),
        venue_id=vid,
        stage_name="Auditor",
        email="audit@example.com",
        password_hash=hash_password("pw"),
        role="singer",
    )
    db.add(singer)
    await db.commit()

    calls = []

    async def _capture(*args, **kwargs):
        calls.append((args, kwargs))

    with patch("app.middleware.observability.log_audit", side_effect=_capture):
        token = jwt_encode(vid, role="singer", user_id=singer.id)
        r = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200

        # observability middleware dispatches via create_task; flush tasks
        await asyncio.sleep(0.2)

    assert len(calls) >= 1
    args, kwargs = calls[0]
    assert kwargs["action"] == "GET /v1/auth/me"
    assert kwargs["result"] == "success"
    assert kwargs["user_id"] == singer.id
    assert kwargs["venue_id"] == vid


# ---------------------------------------------------------------------------
# DB index validation
# ---------------------------------------------------------------------------

def test_required_indexes_exist():
    singer_idx_names = {ix.name for ix in Singer.__table__.indexes}
    assert "singer_venue_idx" in singer_idx_names

    queue_idx_names = {ix.name for ix in QueueRequest.__table__.indexes}
    assert "queue_position_idx" in queue_idx_names

    checkin_idx_names = {ix.name for ix in CheckInSession.__table__.indexes}
    assert "checkin_session_singer_idx" in checkin_idx_names
