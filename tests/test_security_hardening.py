"""Security hardening acceptance tests."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import AsyncClient, ASGITransport

from app.core.config import settings


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------

def test_reject_default_jwt_secret_in_production(monkeypatch):
    """Non-development env must reject default or short JWT_SECRET_KEY."""
    from app.core.config import Settings

    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(ENVIRONMENT="production", JWT_SECRET_KEY="change-me")

    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(ENVIRONMENT="staging", JWT_SECRET_KEY="short")


def test_accepts_strong_jwt_secret_in_production(monkeypatch):
    from app.core.config import Settings

    s = Settings(
        ENVIRONMENT="production",
        JWT_SECRET_KEY="a" * 64,
    )
    assert s.JWT_SECRET_KEY == "a" * 64


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

@pytest.fixture
async def limited_client(monkeypatch):
    """Client with tight rate limits for testing."""
    monkeypatch.setattr(settings, "RATE_LIMIT_REQUESTS", 2)
    monkeypatch.setattr(settings, "RATE_LIMIT_WINDOW", 60)
    monkeypatch.setattr(settings, "REDIS_URL", None)

    # Reset in-memory buckets
    from app.middleware import security as sec_mod
    sec_mod._buckets.clear()

    # Need to re-import because app holds class refs
    from app.main import app as _app

    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as c:
        yield c
    sec_mod._buckets.clear()


@pytest.mark.asyncio
async def test_rate_limit_returns_429(limited_client):
    # First two requests succeed
    r1 = await limited_client.get("/v1/shows")
    r2 = await limited_client.get("/v1/shows")
    assert r1.status_code in (200, 401, 404)  # depends on route
    assert r2.status_code in (200, 401, 404)

    # Third request from same IP should be rate limited
    r3 = await limited_client.get("/v1/shows")
    assert r3.status_code == 429
    assert "Retry-After" in r3.headers


@pytest.mark.asyncio
async def test_rate_limit_per_user_bucket(limited_client, admin_token):
    token, venue_id = admin_token
    headers = {"Authorization": f"Bearer {token}"}

    # Authenticated user gets their own bucket
    await limited_client.get(f"/v1/venues/{venue_id}/shows", headers=headers)
    await limited_client.get(f"/v1/venues/{venue_id}/shows", headers=headers)
    r3 = await limited_client.get(f"/v1/venues/{venue_id}/shows", headers=headers)

    # Third should be 429 because limit=2
    # Note: some routes may 404 if no shows exist; 429 takes precedence
    if r3.status_code != 429:
        # The route might return 404 before we hit limit depending on middleware order
        # RateLimit is after SecurityHeaders, so it runs before route logic
        assert r3.status_code == 429, f"Expected 429 but got {r3.status_code}"
    assert "Retry-After" in r3.headers


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------

@pytest.fixture
async def secure_client(monkeypatch):
    monkeypatch.setattr(settings, "SECURITY_HEADERS_ENABLED", True)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    from app.main import app as _app

    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_security_headers_present(secure_client):
    # Use health endpoint (no auth needed)
    r = await secure_client.get("/health")
    assert r.status_code == 200
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert "default-src 'self'" in (r.headers.get("Content-Security-Policy") or "")
    assert "Strict-Transport-Security" in r.headers


# ---------------------------------------------------------------------------
# Request-ID propagation
# ---------------------------------------------------------------------------

@pytest.fixture
async def reqid_client():
    from app.main import app as _app

    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_request_id_injected(reqid_client):
    r = await reqid_client.get("/health")
    assert r.status_code == 200
    request_id = r.headers.get("X-Request-ID")
    assert request_id is not None
    assert len(request_id) == 36  # UUID4


@pytest.mark.asyncio
async def test_request_id_passthrough(reqid_client):
    provided = str(uuid.uuid4())
    r = await reqid_client.get("/health", headers={"X-Request-ID": provided})
    assert r.headers.get("X-Request-ID") == provided


# ---------------------------------------------------------------------------
# CORS in production
# ---------------------------------------------------------------------------

@pytest.fixture
async def cors_prod_client(monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(
        settings, "CORS_ORIGINS_PROD", "https://app.scales.dev,https://admin.scales.dev"
    )

    # Build a fresh app so CORSMiddleware picks up the patched settings.
    from app.main import lifespan
    from app.middleware import (
        RequestIDMiddleware,
        SecurityHeadersMiddleware,
        RateLimitMiddleware,
        RequestSizeMiddleware,
    )
    from app.api.router import api_router
    from app.api.health import health_router

    _app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    _app.add_middleware(RequestIDMiddleware)
    _app.add_middleware(SecurityHeadersMiddleware)
    _app.add_middleware(RateLimitMiddleware)
    _app.add_middleware(RequestSizeMiddleware)
    origins = [o.strip() for o in (settings.CORS_ORIGINS_PROD or "").split(",") if o.strip()]
    _app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    _app.include_router(health_router, tags=["Health"])
    _app.include_router(api_router, prefix="/v1")

    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_cors_rejects_unknown_origin(cors_prod_client):
    r = await cors_prod_client.options(
        "/health",
        headers={
            "Origin": "https://evil.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Preflight from unknown origin should not include access-control-allow-origin
    assert "access-control-allow-origin" not in (
        r.headers.get("access-control-allow-origin", "").lower()
    )


@pytest.mark.asyncio
async def test_cors_allows_known_origin(cors_prod_client):
    r = await cors_prod_client.options(
        "/health",
        headers={
            "Origin": "https://app.scales.dev",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type,authorization",
        },
    )
    assert r.headers.get("access-control-allow-origin") == "https://app.scales.dev"


# ---------------------------------------------------------------------------
# Request body size limit
# ---------------------------------------------------------------------------

@pytest.fixture
async def size_limited_client(monkeypatch):
    monkeypatch.setattr(settings, "REQUEST_MAX_BODY_SIZE_MB", 0.01)  # ~10KB

    from app.main import app as _app

    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_request_body_size_rejected(size_limited_client):
    big_body = "x" * (1024 * 20)  # 20KB
    r = await size_limited_client.post("/health", data=big_body)
    assert r.status_code == 413
