"""ASGI middleware for observability: structured logging and metrics collection."""

from __future__ import annotations

import asyncio
import time
import urllib.parse
from typing import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.audit_service import log_audit


logger = structlog.get_logger()


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """
    Collect per-request metrics and augment structlog context with:
    - request_id
    - user_id (from Bearer token sub, if present)
    - venue_id (from token claims or request params)
    Also increments prometheus-style counters.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = time.perf_counter()

        # Resolve identity context
        user_id: str | None = None
        venue_id: str | None = None
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:]
            try:
                from app.core.security import decode_token
                claims = decode_token(token)
                if claims:
                    user_id = claims.get("sub")
                    venue_id = claims.get("venue_id")
            except Exception:
                pass

        # Fallback venue_id from path params
        if not venue_id:
            venue_id = request.path_params.get("venue_id")

        request_id = request.headers.get("x-request-id")
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            user_id=user_id,
            venue_id=venue_id,
            method=request.method,
            path=request.url.path,
        )

        from app.middleware.observability_metrics import ACTIVE_CONNECTIONS
        ACTIVE_CONNECTIONS.inc()
        try:
            response = await call_next(request)
        finally:
            ACTIVE_CONNECTIONS.dec()
        duration = time.perf_counter() - start

        from app.middleware.observability_metrics import REQUESTS_TOTAL, REQUEST_DURATION

        status_code = str(response.status_code)
        route = request.scope.get("route")
        handler = route.name if route else request.url.path
        path = urllib.parse.quote(request.url.path, safe="")

        REQUESTS_TOTAL.labels(method=request.method, handler=handler, status=status_code).inc()
        REQUEST_DURATION.labels(method=request.method, handler=handler).observe(duration)

        logger.info(
            "http_request",
            status=response.status_code,
            duration_ms=round(duration * 1000, 3),
            path=path,
            query=str(request.query_params),
        )

        # Audit log for authenticated requests (protected endpoints)
        if user_id:
            try:
                client_ip = request.headers.get("x-forwarded-for", "")
                client_ip = client_ip.split(",")[0].strip() if client_ip else (request.client.host if request.client else "")
                asyncio.create_task(
                    log_audit(
                        action=f"{request.method} {request.url.path}",
                        user_id=user_id,
                        venue_id=venue_id,
                        result="success" if response.status_code < 400 else "failure",
                        status_code=response.status_code,
                        ip_address=client_ip,
                        user_agent=request.headers.get("user-agent"),
                        request_id=request_id,
                        resource_type=route.name if route else "unknown",
                    )
                )
            except Exception:
                logger.debug("audit_log_dispatch_failed", exc_info=True)

        return response
