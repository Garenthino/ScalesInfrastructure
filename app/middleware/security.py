"""ASGI middleware for security hardening."""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from collections import defaultdict
from typing import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# In-memory rate limit store (per-process fallback when Redis is absent)
# ---------------------------------------------------------------------------

_lock = asyncio.Lock()
_buckets: dict[str, list[float]] = defaultdict(list)


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _get_identity(request: Request) -> str:
    """Return user_id from token if authenticated, else IP address."""
    auth = request.headers.get("authorization", "")
    x_api_key = request.headers.get("x-api-key", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:]
        # Use a stable hash of the full token so different tokens get different buckets
        token_hash = hashlib.sha256(token.encode()).hexdigest()[:16]
        return f"user:{token_hash}"
    if x_api_key:
        # Cloud sync clients use x-api-key — treat as authenticated with own bucket
        key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()[:16]
        return f"apikey:{key_hash}"
    return f"ip:{_get_client_ip(request)}"


async def _is_rate_limited(identity: str, is_authenticated: bool, is_read: bool = False) -> tuple[bool, int]:
    if is_authenticated and is_read:
        limit = settings.RATE_LIMIT_READ_REQUESTS
    else:
        limit = settings.RATE_LIMIT_REQUESTS if is_authenticated else settings.RATE_LIMIT_UNAUTHED_REQUESTS
    window = settings.RATE_LIMIT_WINDOW
    now = time.time()

    # Check Redis first if available
    redis_url = settings.REDIS_URL
    if redis_url:
        try:
            import redis.asyncio as aioredis

            r = aioredis.from_url(redis_url, decode_responses=True)
            key = f"ratelimit:{identity}"
            pipe = r.pipeline()
            pipe.zremrangebyscore(key, 0, now - window)
            pipe.zcard(key)
            pipe.zadd(key, {str(now): now})
            pipe.expire(key, window)
            _, count, _, _ = await pipe.execute()
            await r.close()
            if count >= limit:
                retry_after = int(window - (now % window)) or window
                return True, retry_after
            return False, 0
        except Exception:
            # Fall through to in-memory on any Redis error
            pass

    async with _lock:
        bucket = _buckets[identity]
        cutoff = now - window
        # Purge stale entries
        while bucket and bucket[0] < cutoff:
            bucket.pop(0)
        if len(bucket) >= limit:
            retry_after = int(window - (now % window)) or window
            return True, retry_after
        bucket.append(now)
        return False, 0


# ---------------------------------------------------------------------------
# Middleware classes
# ---------------------------------------------------------------------------

class RequestIDMiddleware(BaseHTTPMiddleware):
    """Inject X-Request-ID header per request and include it in logs."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add standard security headers to every response."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        if not settings.SECURITY_HEADERS_ENABLED:
            return response
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers[
            "Content-Security-Policy"
        ] = "default-src 'self'; frame-ancestors 'none';"
        if settings.ENVIRONMENT != "development":
            response.headers[
                "Strict-Transport-Security"
            ] = "max-age=63072000; includeSubDomains"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket-ish rate limiting per IP / per authenticated user."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        identity = _get_identity(request)
        auth = request.headers.get("authorization", "")
        x_api_key = request.headers.get("x-api-key", "")
        is_authenticated = auth.lower().startswith("bearer ") or bool(x_api_key)
        path = request.url.path

        # Skip rate limiting for KJ sync, health endpoints, and lightweight identity/profile reads
        if (
            path.startswith("/kj/sync/")
            or path in ("/api/health", "/docs", "/openapi.json")
            or path.endswith("/health")
            or path == "/v1/onboarding/me"
            or path == "/v1/auth/me"
            or path.startswith("/v1/venues/") and "/singers/me" in path
        ):
            return await call_next(request)

        # Authenticated read endpoints get a higher burst limit to avoid
        # throttling dashboards, queue views, and song catalogs.
        is_read = request.method in ("GET", "HEAD", "OPTIONS")
        rate_limit_key_suffix = "read" if (is_authenticated and is_read) else "write"
        limited, retry_after = await _is_rate_limited(
            f"{identity}:{rate_limit_key_suffix}",
            is_authenticated,
            is_read=is_read,
        )
        if limited:
            logger.warning(
                "rate_limit_exceeded",
                identity=identity[:32],
                path=request.url.path,
                method=request.method,
            )
            return Response(
                status_code=429,
                content='{"detail":"Too many requests"}',
                headers={
                    "Content-Type": "application/json",
                    "Retry-After": str(retry_after),
                },
            )
        return await call_next(request)


class RequestSizeMiddleware(BaseHTTPMiddleware):
    """Reject requests whose body exceeds REQUEST_MAX_BODY_SIZE_MB."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        content_length = request.headers.get("content-length")
        max_bytes = int(settings.REQUEST_MAX_BODY_SIZE_MB * 1024 * 1024)
        if content_length and int(content_length) > max_bytes:
            return Response(
                status_code=413,
                content='{"detail":"Request entity too large"}',
                headers={"Content-Type": "application/json"},
            )
        return await call_next(request)
