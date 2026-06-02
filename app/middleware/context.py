"""ASGI middleware to inject the current request into async context.

Makes the Starlette Request available to DB session helpers via
``app.core.rls.get_current_request()`` so ``get_db`` can auto-resolve
the venue_id for RLS without every router passing it explicitly.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.rls import set_current_request


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Make ``request`` resolvable from async context."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        set_current_request(request)
        return await call_next(request)
