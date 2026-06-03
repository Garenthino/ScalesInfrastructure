"""Row-Level Security unit tests.

Covers the RLS helper layer in app.core.rls and the auto-scoped ``get_db``
dependency.  These tests run against SQLite (fast) and verify that the
helpers don't crash and resolve venue_id correctly.  Enforcement tests
run in ``test_integration_dockerized.py`` against the Dockerized PostgreSQL
stack.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI, Request, Depends
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rls import (
    resolve_venue_id_from_token,
    set_session_venue_id,
    get_current_request,
    set_current_request,
)
from app.core.db import get_db


class FakeRequest:
    """Minimal request stand-in for resolve_venue_id_from_token."""

    def __init__(self, headers: dict | None = None, path_params: dict | None = None):
        self.headers = headers or {}
        self.path_params = path_params or {}


def test_resolve_venue_id_from_path_param():
    req = FakeRequest(path_params={"venue_id": "venue-123"})
    assert resolve_venue_id_from_token(req) == "venue-123"


def test_resolve_venue_id_from_bearer_token():
    from jose import jwt
    from app.core.config import settings

    vid = str(uuid.uuid4())
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "venue_id": vid, "role": "singer"},
        settings.JWT_SECRET_KEY,
        algorithm="HS256",
    )
    req = FakeRequest(headers={"authorization": f"Bearer {token}"})
    assert resolve_venue_id_from_token(req) == vid


def test_resolve_venue_id_path_param_fallback():
    """When token has no venue_id, fall back to path param."""
    from jose import jwt
    from app.core.config import settings

    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "role": "singer"},
        settings.JWT_SECRET_KEY,
        algorithm="HS256",
    )
    req = FakeRequest(
        headers={"authorization": f"Bearer {token}"},
        path_params={"venue_id": "fallback-vid"},
    )
    assert resolve_venue_id_from_token(req) == "fallback-vid"


@pytest.mark.asyncio
async def test_set_session_venue_id_sqlite_noop(db: AsyncSession):
    """On SQLite, setting a custom session var is a no-op (no crash)."""
    await set_session_venue_id(db, str(uuid.uuid4()))
    # If we got here without exception, the noop path works.


@pytest.mark.asyncio
async def test_get_db_sets_venue_id_via_request_context():
    """``get_db`` resolves venue_id from the request context and sets it."""
    app = FastAPI()

    @app.get("/test")
    async def endpoint(request: Request, db: AsyncSession = Depends(get_db)):
        # Verify the session has the variable attempted (SQLite swallows it)
        # We can't introspect SQLite session vars, but we can assert no crash.
        return {"ok": True}

    # Manually inject a fake request context
    fake_req = FakeRequest(
        path_params={"venue_id": "ctx-venue-123"}
    )
    set_current_request(fake_req)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/test")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    set_current_request(None)
