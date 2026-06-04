"""PostgreSQL Row-Level Security (RLS) session helpers.

Provides a Starlette/FastAPI request contextvar and helper to set the
PostgreSQL session variable ``app.current_venue_id`` on an async DB session.
The RLS policies read this variable to enforce tenant isolation.

Usage::

    from app.core.rls import set_session_venue_id
    from app.core.db import async_session_factory

    async with async_session_factory() as session:
        await set_session_venue_id(session, venue_id)
        # every query from this session is now scoped to the venue
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_REQUEST_CTX: ContextVar[Any] = ContextVar("request_ctx", default=None)


def get_current_request() -> Any | None:
    """Return the current Starlette Request from async context, if any."""
    return _REQUEST_CTX.get()


def set_current_request(request: Any) -> None:
    """Bind the current request into the async context (called by middleware)."""
    _REQUEST_CTX.set(request)


def resolve_venue_id_from_token(request: Any) -> str | None:
    """Decode the Bearer token from *request* and return its ``venue_id`` claim."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        # Try path param fallback
        return request.path_params.get("venue_id")
    token = auth[7:]
    try:
        from app.core.security import decode_token
        claims = decode_token(token)
        if claims:
            vid = claims.get("venue_id")
            if vid:
                return vid
    except Exception:
        pass
    return request.path_params.get("venue_id")


async def set_session_venue_id(session: AsyncSession, venue_id: str | None) -> None:
    """Configure the session so PostgreSQL RLS policies see the venue_id.

    Safe to call even on SQLite (becomes a no-op).  On PostgreSQL we issue
    ``SET LOCAL app.current_venue_id = ...`` so the value is transaction-scoped
    and automatically reverts on commit / rollback.
    """
    # If a previous request aborted a transaction on this pooled connection,
    # any new SQL will fail with "current transaction is aborted".  Roll back
    # to a clean state first.
    try:
        await session.rollback()
    except Exception:
        pass

    if venue_id is None:
        # Unset — useful for superuser / admin operations that must see all rows
        await _execute_safe(session, "SET LOCAL app.current_venue_id = ''")
        return
    # Quote safely by using a bind parameter.  The placeholder works for both
    # PostgreSQL and SQLite because the parameter is resolved by SQLAlchemy.
    await _execute_safe(
        session, "SET LOCAL app.current_venue_id = :vid", {"vid": str(venue_id)}
    )


async def _execute_safe(session: AsyncSession, stmt: str, params: dict | None = None) -> None:
    try:
        await session.execute(text(stmt), params or {})
    except Exception:
        # Swallow on SQLite (doesn't support custom session vars) and keep going
        pass
